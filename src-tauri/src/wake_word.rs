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

    // 2. 初始化 cpal 输入流，帧缓冲通过 channel 发送给检测循环
    let (tx, rx) = std::sync::mpsc::channel::<Vec<i16>>();
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or_else(|| anyhow::anyhow!("未找到麦克风设备"))?;

    let default_config = device.default_input_config()
        .map_err(|e| anyhow::anyhow!("获取默认麦克风配置失败: {}", e))?;
    
    let actual_sample_rate = default_config.sample_rate().0;
    let channels = default_config.channels();
    let sample_format = default_config.sample_format();
    let config: cpal::StreamConfig = default_config.into();

    let err_fn = |err| eprintln!("[cpal] 输入流错误：{err}");

    // 简易动态重采样器 (Nearest-neighbor)
    let ratio = actual_sample_rate as f32 / sample_rate as f32;
    


    let stream = match sample_format {
        cpal::SampleFormat::F32 => {
            let mut phase = 0.0;
            device.build_input_stream(
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
            )?
        },
        cpal::SampleFormat::I16 => {
            let mut phase = 0.0;
            device.build_input_stream(
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
            )?
        },
        cpal::SampleFormat::U16 => {
            let mut phase = 0.0;
            device.build_input_stream(
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
            )?
        },
        _ => return Err(anyhow::anyhow!("不支持的音频样本格式: {:?}", sample_format)),
    };
    stream.play()?;

    // 3. 检测循环
    let mut buf: Vec<i16> = Vec::new();
    while RUNNING.load(Ordering::SeqCst) {
        if let Ok(chunk) = rx.recv_timeout(std::time::Duration::from_millis(100)) {
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

    // 4. 清理
    drop(stream);
    unsafe { pv_porcupine_delete(porcupine) };
    Ok(())
}
