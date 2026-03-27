/// wake_word.rs — Porcupine 唤醒词检测模块
///
/// 使用 cpal 从默认麦克风采集 16kHz / 16-bit / 单声道 PCM，
/// 每帧（pv_porcupine_frame_length 个采样，通常 512）送入 Porcupine C 库处理。
/// 检测命中后通过 Tauri 事件总线向前端广播 "wake-word-detected"。
use std::{
    ffi::CString,
    os::raw::{c_char, c_float, c_int},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex, OnceLock,
    },
    thread::{self, JoinHandle},
};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use tauri::Emitter;

// ─────────────────────────────────────────────
// Porcupine C FFI 绑定（手写，不依赖 bindgen）
// ─────────────────────────────────────────────
#[repr(C)]
struct PvPorcupine {
    _priv: [u8; 0],
}

#[allow(non_camel_case_types)]
type pv_status_t = c_int;

#[link(name = "libpv_porcupine", kind = "raw-dylib")]
extern "C" {
    fn pv_porcupine_init(
        access_key: *const c_char,
        model_path: *const c_char,
        device: *const c_char,
        num_keywords: c_int,
        keyword_paths: *const *const c_char,
        sensitivities: *const c_float,
        object: *mut *mut PvPorcupine,
    ) -> pv_status_t;

    fn pv_porcupine_delete(object: *mut PvPorcupine);

    fn pv_porcupine_process(
        object: *mut PvPorcupine,
        pcm: *const i16,
        keyword_index: *mut c_int,
    ) -> pv_status_t;

    fn pv_porcupine_frame_length() -> c_int;
    fn pv_sample_rate() -> c_int;
}

// ─────────────────────────────────────────────
// 全局运行标志 + 线程句柄
// ─────────────────────────────────────────────
static RUNNING: AtomicBool = AtomicBool::new(false);
static HANDLE: OnceLock<Mutex<Option<JoinHandle<()>>>> = OnceLock::new();

fn handle_store() -> &'static Mutex<Option<JoinHandle<()>>> {
    HANDLE.get_or_init(|| Mutex::new(None))
}

/// 启动唤醒词检测后台线程。
/// - `access_key`   : Picovoice 控制台 Access Key
/// - `keyword_path` : .ppn 文件绝对路径（如 "你好_windows.ppn"）
/// - `model_path`   : porcupine_params.pv 模型文件路径（SDK 附带）
pub fn start(
    app: tauri::AppHandle,
    access_key: String,
    keyword_paths: Vec<String>,
    model_path: String,
) -> anyhow::Result<()> {
    if RUNNING.load(Ordering::SeqCst) {
        return Ok(()); // 已在运行
    }

    RUNNING.store(true, Ordering::SeqCst);
    let app_clone = app.clone();

    let handle = thread::spawn(move || {
        if let Err(e) = wake_loop(app_clone, &access_key, &keyword_paths, &model_path) {
            eprintln!("[wake_word] 线程退出，错误：{e}");
        }
        RUNNING.store(false, Ordering::SeqCst);
    });

    *handle_store().lock().unwrap() = Some(handle);
    Ok(())
}

/// 停止唤醒词检测线程。
pub fn stop() {
    RUNNING.store(false, Ordering::SeqCst);
    if let Some(h) = handle_store().lock().unwrap().take() {
        let _ = h.join();
    }
}

// ─────────────────────────────────────────────
// 内部：完整唤醒检测循环
// ─────────────────────────────────────────────
fn wake_loop(
    app: tauri::AppHandle,
    access_key: &str,
    keyword_paths: &[String],
    model_path: &str,
) -> anyhow::Result<()> {
    // 1. 初始化 Porcupine
    println!("[Porcupine] 开始初始化...");
    let c_key = CString::new(access_key)?;
    let c_model = CString::new(model_path)?;

    // 过滤空路径（如果用户没有设置结束唤醒词，前端传过来的可能是空字符串）
    let valid_paths: Vec<String> = keyword_paths
        .iter()
        .filter(|p| !p.trim().is_empty())
        .cloned()
        .collect();

    if valid_paths.is_empty() {
        anyhow::bail!("未设置任何有效的唤醒词路径");
    }

    // 转换所有关键字路径为 CString
    let c_keyword_paths: Vec<CString> = valid_paths
        .iter()
        .map(|p| CString::new(p.as_str()).unwrap())
        .collect();
    let keyword_ptrs: Vec<*const c_char> = c_keyword_paths.iter().map(|s| s.as_ptr()).collect();
    
    let num_keywords = valid_paths.len() as c_int;
    let sensitivities: Vec<f32> = vec![0.5; valid_paths.len()];

    let mut porcupine: *mut PvPorcupine = std::ptr::null_mut();
    let c_device = CString::new("best")?;

    let status = unsafe {
        pv_porcupine_init(
            c_key.as_ptr(),
            c_model.as_ptr(),
            c_device.as_ptr(),
            num_keywords,
            keyword_ptrs.as_ptr(),
            sensitivities.as_ptr(),
            &mut porcupine,
        )
    };
    
    if status != 0 {
        anyhow::bail!("pv_porcupine_init 失败，status={status}");
    }

    let frame_len = unsafe { pv_porcupine_frame_length() } as usize;
    let sample_rate = unsafe { pv_sample_rate() } as u32; // 通常 16000

    // 2. 音频流初始化 + 检测循环（含自动恢复）
    'audio_loop: loop {
        if !RUNNING.load(Ordering::SeqCst) { break; }

        let (tx, rx) = std::sync::mpsc::channel::<Vec<i16>>();
        let host = cpal::default_host();
        let device = match host.default_input_device() {
            Some(d) => d,
            None => {
                eprintln!("[wake_word] 未找到麦克风设备，2秒后重试...");
                let _ = app.emit("microphone-error", "未找到麦克风设备");
                std::thread::sleep(std::time::Duration::from_secs(2));
                continue 'audio_loop;
            }
        };

        let default_config = match device.default_input_config() {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[wake_word] 获取麦克风配置失败: {}，2秒后重试...", e);
                let _ = app.emit("microphone-error", "麦克风配置获取失败");
                std::thread::sleep(std::time::Duration::from_secs(2));
                continue 'audio_loop;
            }
        };

        let actual_sample_rate = default_config.sample_rate().0;
        let channels = default_config.channels();
        let sample_format = default_config.sample_format();
        let config: cpal::StreamConfig = default_config.into();

        let mic_error_flag = std::sync::Arc::new(AtomicBool::new(false));
        let mic_error_flag_clone = mic_error_flag.clone();
        let err_fn = move |err: cpal::StreamError| {
            let err_str = err.to_string();
            eprintln!("[cpal] 输入流错误：{}", err_str);
            mic_error_flag_clone.store(true, Ordering::SeqCst);
        };

        let ratio = actual_sample_rate as f32 / sample_rate as f32;

        let stream = match sample_format {
            cpal::SampleFormat::F32 => {
                let mut phase = 0.0;
                match device.build_input_stream(
                    &config,
                    move |data: &[f32], _| {
                        let mono: Vec<i16> = data.iter().step_by(channels as usize).map(|&s| (s * i16::MAX as f32) as i16).collect();
                        let mut resampled = Vec::new();
                        if actual_sample_rate == sample_rate {
                            resampled = mono;
                        } else {
                            for &sample in &mono {
                                phase += 1.0;
                                if phase >= ratio {
                                    phase -= ratio;
                                    resampled.push(sample);
                                }
                            }
                        }
                        let _ = tx.send(resampled);
                    },
                    err_fn,
                    None,
                ) {
                    Ok(s) => s,
                    Err(e) => {
                        eprintln!("[wake_word] 创建音频流失败: {}，2秒后重试...", e);
                        let _ = app.emit("microphone-error", "创建音频流失败");
                        std::thread::sleep(std::time::Duration::from_secs(2));
                        continue 'audio_loop;
                    }
                }
            },
            cpal::SampleFormat::I16 => {
                let mut phase = 0.0;
                match device.build_input_stream(
                    &config,
                    move |data: &[i16], _| {
                        let mono: Vec<i16> = data.iter().step_by(channels as usize).copied().collect();
                        let mut resampled = Vec::new();
                        if actual_sample_rate == sample_rate {
                            resampled = mono;
                        } else {
                            for &sample in &mono {
                                phase += 1.0;
                                if phase >= ratio {
                                    phase -= ratio;
                                    resampled.push(sample);
                                }
                            }
                        }
                        let _ = tx.send(resampled);
                    },
                    err_fn,
                    None,
                ) {
                    Ok(s) => s,
                    Err(e) => {
                        eprintln!("[wake_word] 创建音频流失败: {}，2秒后重试...", e);
                        let _ = app.emit("microphone-error", "创建音频流失败");
                        std::thread::sleep(std::time::Duration::from_secs(2));
                        continue 'audio_loop;
                    }
                }
            },
            cpal::SampleFormat::U16 => {
                let mut phase = 0.0;
                match device.build_input_stream(
                    &config,
                    move |data: &[u16], _| {
                        let mono: Vec<i16> = data.iter().step_by(channels as usize).map(|&s| (s as i32 - 32768) as i16).collect();
                        let mut resampled = Vec::new();
                        if actual_sample_rate == sample_rate {
                            resampled = mono;
                        } else {
                            for &sample in &mono {
                                phase += 1.0;
                                if phase >= ratio {
                                    phase -= ratio;
                                    resampled.push(sample);
                                }
                            }
                        }
                        let _ = tx.send(resampled);
                    },
                    err_fn,
                    None,
                ) {
                    Ok(s) => s,
                    Err(e) => {
                        eprintln!("[wake_word] 创建音频流失败: {}，2秒后重试...", e);
                        let _ = app.emit("microphone-error", "创建音频流失败");
                        std::thread::sleep(std::time::Duration::from_secs(2));
                        continue 'audio_loop;
                    }
                }
            },
            _ => return Err(anyhow::anyhow!("不支持的音频样本格式: {:?}", sample_format)),
        };

        if let Err(e) = stream.play() {
            eprintln!("[wake_word] 启动音频流失败: {}，2秒后重试...", e);
            let _ = app.emit("microphone-error", "启动音频流失败");
            std::thread::sleep(std::time::Duration::from_secs(2));
            continue 'audio_loop;
        }

        // 音频流创建成功，通知前端恢复
        let current_device_name = device.name().unwrap_or_default();
        eprintln!("[wake_word] 麦克风音频流已就绪 (设备: {:?})", current_device_name);
        let _ = app.emit("microphone-recovered", "麦克风已恢复");

        // 3. 检测循环
        let mut buf: Vec<i16> = Vec::new();
        let mut last_data_time = std::time::Instant::now();
        let mut last_device_check = std::time::Instant::now();
        let mut got_first_data = false;
        while RUNNING.load(Ordering::SeqCst) {
            // 检查麦克风错误标志
            if mic_error_flag.load(Ordering::SeqCst) {
                mic_error_flag.store(false, Ordering::SeqCst);
                eprintln!("[wake_word] 麦克风错误，通知前端并尝试恢复...");
                let _ = app.emit("microphone-error", "麦克风设备已断开或不可用");
                drop(stream);
                std::thread::sleep(std::time::Duration::from_secs(2));
                continue 'audio_loop;
            }
            // 每5秒检查系统默认设备是否变化
            if last_device_check.elapsed() > std::time::Duration::from_secs(5) {
                last_device_check = std::time::Instant::now();
                let check_host = cpal::default_host();
                if let Some(new_default) = check_host.default_input_device() {
                    if let Ok(new_name) = new_default.name() {
                        if new_name != current_device_name {
                            eprintln!("[wake_word] 系统默认麦克风已变更: {:?} -> {:?}，切换中...", current_device_name, new_name);
                            drop(stream);
                            continue 'audio_loop;
                        }
                    }
                }
            }
            // 检查是否长时间没收到音频数据（设备可能已失效但未报错）
            if last_data_time.elapsed() > std::time::Duration::from_secs(5) {
                eprintln!("[wake_word] 超过5秒无音频数据，重新初始化音频流...");
                let _ = app.emit("microphone-error", "麦克风无数据响应");
                drop(stream);
                std::thread::sleep(std::time::Duration::from_secs(2));
                continue 'audio_loop;
            }
            if let Ok(chunk) = rx.recv_timeout(std::time::Duration::from_millis(100)) {
                if !got_first_data {
                    eprintln!("[wake_word] 首次收到音频数据");
                    got_first_data = true;
                }
                last_data_time = std::time::Instant::now();
                buf.extend_from_slice(&chunk);
                while buf.len() >= frame_len {
                    let frame: Vec<i16> = buf.drain(..frame_len).collect();
                    let mut keyword_index: c_int = -1;
                    let st = unsafe {
                        pv_porcupine_process(porcupine, frame.as_ptr(), &mut keyword_index)
                    };
                    if st == 0 && keyword_index >= 0 {
                        let _ = app.emit("wake-word-detected", keyword_index);
                        eprintln!("[wake_word] 唤醒词触发！keyword_index={keyword_index}");
                    }
                }
            }
        }

        // RUNNING 变为 false，正常退出
        drop(stream);
        break;
    }

    // 4. 清理
    unsafe { pv_porcupine_delete(porcupine) };
    Ok(())
}
