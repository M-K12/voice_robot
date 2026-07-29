use std::sync::{Arc, Mutex};
use std::sync::atomic::AtomicBool;
use std::path::PathBuf;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use sherpa_onnx::{KeywordSpotter, KeywordSpotterConfig};
use tauri::Emitter;
use tauri::Manager;
use log::{info, warn, error, debug};

struct SendRawWrapper<T>(T);
unsafe impl<T> Send for SendRawWrapper<T> {}
unsafe impl<T> Sync for SendRawWrapper<T> {}

struct WakeWordState {
    stream: Mutex<Option<SendRawWrapper<cpal::Stream>>>,
    is_running: Arc<AtomicBool>,
}

fn process_audio(
    data: &[f32],
    input_sample_rate: u32,
    spotter: &KeywordSpotter,
    stream_kws: &Mutex<sherpa_onnx::OnlineStream>,
    app_handle: &tauri::AppHandle,
    frame_counter: &std::sync::atomic::AtomicU64,
) {
    let max_val = data.iter().fold(0.0f32, |m, &x| m.max(x.abs()));

    // 优化 6: 降频调试日志 — 每 100 帧且幅值超过阈值时才输出
    #[cfg(debug_assertions)]
    {
        let count = frame_counter.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        if count % 100 == 0 && max_val > 0.02 {
            let sum_sq = data.iter().map(|&x| x * x).sum::<f32>();
            let rms = (sum_sq / data.len() as f32).sqrt();
            debug!(
                "[KWS Debug] frame #{}, rate: {}, max_amp: {:.4}, rms: {:.4}",
                count, input_sample_rate, max_val, rms
            );
        }
    }

    if let Ok(stream_kws) = stream_kws.lock() {
        // 直接传递物理采样率，使用 sherpa-onnx 底层库原生的高质量重采样逻辑
        stream_kws.accept_waveform(input_sample_rate as i32, data);

        while spotter.is_ready(&stream_kws) {
            spotter.decode(&stream_kws);

            if let Some(res) = spotter.get_result(&stream_kws) {
                if !res.keyword.is_empty() {
                    info!("[KWS] keyword detected: {}", res.keyword);
                    // 优化 3: 发送实际命中的关键词文本，而不是固定的 0
                    let _ = app_handle.emit("wake-word-detected", res.keyword.clone());
                    spotter.reset(&stream_kws);
                }
            }
        }
    }
}


#[tauri::command]
fn start_wake_word(
    app_handle: tauri::AppHandle,
    state: tauri::State<'_, WakeWordState>,
    model_dir: String,
    keyword: String,
    max_active_paths: Option<i32>,
    num_trailing_blanks: Option<i32>,
    keywords_score: Option<f32>,
    keywords_threshold: Option<f32>,
) -> Result<(), String> {
    let kw_first_line = keyword.lines().next().unwrap_or(&keyword);
    info!("[Rust KWS] start_wake_word called with keyword: '{}...', model_dir: '{}'", kw_first_line, model_dir);
    let wake_state = state.inner();

    // 1. Ensure any running stream is stopped first
    wake_state.is_running.store(false, std::sync::atomic::Ordering::SeqCst);
    if let Ok(mut stream_opt) = wake_state.stream.lock() {
        if let Some(wrapper) = stream_opt.take() {
            let _ = wrapper.0.pause();
        }
    }

    // 2. Validate model files existence
    let mut model_path = PathBuf::from(&model_dir);
    if model_path.is_relative() {
        // 尝试多种相对路径基准，以确保开发模式（通常工作目录在 src-tauri）和独立运行模式下都能找到模型
        
        // 1. 尝试直接相对当前工作目录
        if !model_path.exists() {
            // 2. 尝试相对当前工作目录的父目录（如果是从 src-tauri 下运行）
            if let Ok(current_dir) = std::env::current_dir() {
                if let Some(parent) = current_dir.parent() {
                    let test_path = parent.join(&model_dir);
                    if test_path.exists() {
                        model_path = test_path;
                    }
                }
            }
        }

        // 3. 尝试相对于当前可执行文件（exe）的父目录的父目录（构建产物在 target/debug/ 时）
        if !model_path.exists() {
            if let Ok(exe_path) = std::env::current_exe() {
                let mut current = exe_path.as_path();
                for _ in 0..4 {
                    if let Some(parent) = current.parent() {
                        let test_path = parent.join(&model_dir);
                        if test_path.exists() {
                            model_path = test_path;
                            break;
                        }
                        current = parent;
                    } else {
                        break;
                    }
                }
            }
        }
    }

    // 动态搜索 encoder, decoder, joiner 从而支持任意 epoch-12 / epoch-13 版本的 Zipformer 模型
    let mut encoder = None;
    let mut decoder = None;
    let mut joiner = None;

    if let Ok(entries) = std::fs::read_dir(&model_path) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_file() {
                if let Some(filename) = path.file_name().and_then(|n| n.to_str()) {
                    // 优先选择普通的 .onnx 模型，过滤掉 .int8.onnx，除非只能找到 int8
                    if filename.starts_with("encoder-") && filename.ends_with(".onnx") && !filename.contains(".int8.") {
                        encoder = Some(path.clone());
                    } else if filename.starts_with("decoder-") && filename.ends_with(".onnx") && !filename.contains(".int8.") {
                        decoder = Some(path.clone());
                    } else if filename.starts_with("joiner-") && filename.ends_with(".onnx") && !filename.contains(".int8.") {
                        joiner = Some(path.clone());
                    }
                }
            }
        }
    }

    // 若未找到普通 ONNX，回退查找 int8 量化版本的 ONNX 文件
    if encoder.is_none() || decoder.is_none() || joiner.is_none() {
        if let Ok(entries) = std::fs::read_dir(&model_path) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_file() {
                    if let Some(filename) = path.file_name().and_then(|n| n.to_str()) {
                        if filename.starts_with("encoder-") && filename.ends_with(".onnx") && encoder.is_none() {
                            encoder = Some(path.clone());
                        } else if filename.starts_with("decoder-") && filename.ends_with(".onnx") && decoder.is_none() {
                            decoder = Some(path.clone());
                        } else if filename.starts_with("joiner-") && filename.ends_with(".onnx") && joiner.is_none() {
                            joiner = Some(path.clone());
                        }
                    }
                }
            }
        }
    }

    let encoder = match encoder {
        Some(e) => e,
        None => return Err(format!("Could not find encoder ONNX file in model directory (resolved: {})", model_path.display())),
    };
    let decoder = match decoder {
        Some(d) => d,
        None => return Err(format!("Could not find decoder ONNX file in model directory (resolved: {})", model_path.display())),
    };
    let joiner = match joiner {
        Some(j) => j,
        None => return Err(format!("Could not find joiner ONNX file in model directory (resolved: {})", model_path.display())),
    };

    let tokens = model_path.join("tokens.txt");
    let keywords_file = model_path.join("keywords.txt");

    if !tokens.exists() {
        return Err(format!("tokens.txt not found in directory (resolved: {})", model_path.display()));
    }

    // 若所选模型目录下缺失 keywords.txt 词表（例如中英模型中），为其自动创建一个包含默认“小安小安”拼音的词表文件
    if !keywords_file.exists() {
        let default_keywords = "x iǎo ān x iǎo ān @小安小安\n";
        if let Err(e) = std::fs::write(&keywords_file, default_keywords) {
            let err_msg = format!("keywords.txt was missing and failed to auto-create: {} (resolved: {})", e, model_path.display());
            error!("[Rust KWS] error: {}", err_msg);
            return Err(err_msg);
        }
        info!("[Rust KWS] keywords.txt missing, auto-created default for '小安小安': {}", keywords_file.display());
    }

    // 3. Create KeywordSpotter
    let mut config = KeywordSpotterConfig::default();
    config.feat_config.sample_rate = 16000;
    config.feat_config.feature_dim = 80;
    config.model_config.transducer.encoder = Some(encoder.to_string_lossy().to_string());
    config.model_config.transducer.decoder = Some(decoder.to_string_lossy().to_string());
    config.model_config.transducer.joiner = Some(joiner.to_string_lossy().to_string());
    config.model_config.tokens = Some(tokens.to_string_lossy().to_string());
    config.model_config.num_threads = 1;
    config.model_config.debug = false;
    // 使用前端传入的参数，未传则使用合理默认值
    config.max_active_paths    = max_active_paths.unwrap_or(4);
    config.num_trailing_blanks = num_trailing_blanks.unwrap_or(1);
    config.keywords_score      = keywords_score.unwrap_or(1.5);
    config.keywords_threshold  = keywords_threshold.unwrap_or(0.25);
    info!("[Rust KWS] config: max_active_paths={}, num_trailing_blanks={}, keywords_score={}, keywords_threshold={}",
        config.max_active_paths, config.num_trailing_blanks, config.keywords_score, config.keywords_threshold);
    config.keywords_file = Some(keywords_file.to_string_lossy().to_string());

    let spotter = KeywordSpotter::create(&config).ok_or_else(|| {
        let err_msg = "Failed to create KeywordSpotter engine".to_string();
        error!("[Rust KWS] error: {}", err_msg);
        err_msg
    })?;

    let spotter = Arc::new(spotter);
    let stream_kws = Arc::new(Mutex::new(spotter.create_stream()));

    // 4. Initialize cpal capture stream
    let host = cpal::default_host();
    let device = host.default_input_device().ok_or_else(|| {
        let err_msg = "No default microphone input device found".to_string();
        error!("[Rust KWS] error: {}", err_msg);
        err_msg
    })?;

    let config_orig = device.default_input_config().map_err(|e| {
        let err_msg = format!("Failed to get default microphone config: {}", e);
        error!("[Rust KWS] error: {}", err_msg);
        err_msg
    })?;

    let input_sample_rate = config_orig.sample_rate().0;
    let sample_format = config_orig.sample_format();
    let channels = config_orig.channels() as usize;

    let app_handle_clone = app_handle.clone();
    let spotter_clone = spotter.clone();
    let stream_kws_clone = stream_kws.clone();
    // 优化 6: 帧计数器，用于降频调试日志
    let frame_counter = Arc::new(std::sync::atomic::AtomicU64::new(0));

    let is_running_clone = wake_state.is_running.clone();
    is_running_clone.store(true, std::sync::atomic::Ordering::SeqCst);

    let err_fn = move |err| {
        error!("An error occurred on cpal input stream: {}", err);
    };

    let stream = match sample_format {
        cpal::SampleFormat::F32 => {
            let frame_counter_f32 = frame_counter.clone();
            device
                .build_input_stream(
                    &config_orig.into(),
                    move |data: &[f32], _: &cpal::InputCallbackInfo| {
                        if !is_running_clone.load(std::sync::atomic::Ordering::SeqCst) {
                            return;
                        }
                        let mono_data: Vec<f32> = if channels > 1 {
                            data.iter().step_by(channels).cloned().collect()
                        } else {
                            data.to_vec()
                        };
                        process_audio(
                            &mono_data,
                            input_sample_rate,
                            &spotter_clone,
                            &stream_kws_clone,
                            &app_handle_clone,
                            &frame_counter_f32,
                        );
                    },
                    err_fn,
                    None,
                )
                .map_err(|e| format!("Failed to build input stream (F32): {}", e))?
        },
        cpal::SampleFormat::I16 => {
            let frame_counter_i16 = frame_counter.clone();
            device
                .build_input_stream(
                    &config_orig.into(),
                    move |data: &[i16], _: &cpal::InputCallbackInfo| {
                        if !is_running_clone.load(std::sync::atomic::Ordering::SeqCst) {
                            return;
                        }
                        let mono_data: Vec<f32> = if channels > 1 {
                            data.iter().step_by(channels).map(|&x| x as f32 / 32768.0).collect()
                        } else {
                            data.iter().map(|&x| x as f32 / 32768.0).collect()
                        };
                        process_audio(
                            &mono_data,
                            input_sample_rate,
                            &spotter_clone,
                            &stream_kws_clone,
                            &app_handle_clone,
                            &frame_counter_i16,
                        );
                    },
                    err_fn,
                    None,
                )
                .map_err(|e| format!("Failed to build input stream (I16): {}", e))?
        },
        _ => {
            return Err(format!(
                "Unsupported microphone sample format: {:?}",
                sample_format
            ))
        }
    };

    stream
        .play()
        .map_err(|e| format!("Failed to start cpal capture stream: {}", e))?;

    if let Ok(mut stream_opt) = wake_state.stream.lock() {
        *stream_opt = Some(SendRawWrapper(stream));
    }

    info!(
        "[Rust KWS] Started successfully (model_dir: {}).",
        model_dir
    );
    Ok(())
}

#[tauri::command]
fn stop_wake_word(state: tauri::State<'_, WakeWordState>) -> Result<(), String> {
    let wake_state = state.inner();
    wake_state
        .is_running
        .store(false, std::sync::atomic::Ordering::SeqCst);
    if let Ok(mut stream_opt) = wake_state.stream.lock() {
        if let Some(wrapper) = stream_opt.take() {
            let _ = wrapper.0.pause();
        }
    }
    info!("[Rust KWS] Rust KWS stopped.");
    Ok(())
}

#[tauri::command]
fn frontend_log(level: String, message: String) {
    match level.as_str() {
        "ERROR" => error!("[Frontend] {}", message),
        "WARN" => warn!("[Frontend] {}", message),
        "DEBUG" => debug!("[Frontend] {}", message),
        _ => info!("[Frontend] {}", message),
    }
}

/// Read a config JSON file from the configs/ directory.
/// `relative_path` is relative to the app's working directory, e.g. "configs/global.json"
/// or "configs/models/voice_e2e/qwen-audio-3.0-realtime-flash.json".
#[tauri::command]
fn read_config_file(relative_path: String) -> Result<serde_json::Value, String> {
    // Sanitize: block path traversal
    if relative_path.contains("..") {
        return Err("Invalid path: '..' is not allowed".into());
    }
    let cwd = std::env::current_dir().map_err(|e| format!("Failed to get cwd: {}", e))?;
    let mut candidate = cwd.join(&relative_path);
    
    // 如果在 current_dir 找不到，尝试在父级目录中找 (例如当前 cwd 是 src-tauri 时)
    if !candidate.exists() {
        if let Some(parent) = cwd.parent() {
            let parent_candidate = parent.join(&relative_path);
            if parent_candidate.exists() {
                candidate = parent_candidate;
            }
        }
    }

    let content = std::fs::read_to_string(&candidate)
        .map_err(|e| format!("Failed to read {}: {}", candidate.display(), e))?;
    let value: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse JSON {}: {}", candidate.display(), e))?;
    
    info!("[Rust Config] Successfully read config: {}", candidate.display());
    Ok(value)
}

#[tauri::command]
async fn open_settings_window(app_handle: tauri::AppHandle) -> Result<(), String> {
    info!("[Rust Window] open_settings_window command triggered");
    
    // 如果设置窗口已存在，强行显示并激活聚焦
    if let Some(win) = app_handle.get_webview_window("settings") {
        info!("[Rust Window] Settings window already exists, showing and focusing...");
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
        return Ok(());
    }

    // 在 Tauri v2 中，使用 WebviewUrl::App 载入子页面参数
    let settings_url = tauri::WebviewUrl::App("?page=settings".into());
    
    let builder = tauri::WebviewWindowBuilder::new(
        &app_handle,
        "settings",
        settings_url,
    )
    .title("小安 - 系统设置")
    .inner_size(640.0, 600.0)
    .resizable(false)
    .always_on_top(true)
    .decorations(true)
    .center();

    match builder.build() {
        Ok(_) => {
            info!("[Rust Window] Settings window created successfully");
            Ok(())
        }
        Err(e) => {
            let err_msg = format!("Failed to build settings window: {}", e);
            error!("[Rust Window] error: {}", err_msg);
            Err(err_msg)
        }
    }
}

#[tauri::command]
fn emit_settings_saved(app_handle: tauri::AppHandle, payload: serde_json::Value) {
    info!("[Rust Event] Broadcasting settings-saved event globally from Rust");
    let _ = app_handle.emit("settings-saved", payload);
}

#[tauri::command]
async fn close_settings_window(app_handle: tauri::AppHandle) -> Result<(), String> {
    info!("[Rust Window] close_settings_window command triggered");
    if let Some(win) = app_handle.get_webview_window("settings") {
        win.close().map_err(|e| format!("Failed to close settings window: {}", e))?;
        info!("[Rust Window] Settings window closed successfully");
    } else {
        info!("[Rust Window] Settings window not found, may already be closed");
    }
    Ok(())
}

#[tauri::command]
fn set_fullscreen(app_handle: tauri::AppHandle, fullscreen: bool) -> Result<(), String> {
    info!("[Rust Window] set_fullscreen command triggered: {}", fullscreen);
    if let Some(win) = app_handle.get_webview_window("main") {
        win.set_fullscreen(fullscreen)
            .map_err(|e| format!("Failed to set fullscreen: {}", e))?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(WakeWordState {
            stream: Mutex::new(None),
            is_running: Arc::new(AtomicBool::new(false)),
        })
        .invoke_handler(tauri::generate_handler![
            start_wake_word,
            stop_wake_word,
            frontend_log,
            read_config_file,
            open_settings_window,
            close_settings_window,
            emit_settings_saved,
            set_fullscreen
        ])
        .setup(|app| {
            app.handle().plugin(
                tauri_plugin_log::Builder::default()
                    .targets([
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir { file_name: Some("app.log".into()) }),
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Webview),
                    ])
                    .level(log::LevelFilter::Info)
                    .build(),
            )?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
