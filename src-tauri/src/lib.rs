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
    stream: Arc<Mutex<Option<SendRawWrapper<cpal::Stream>>>>,
    is_running: Arc<AtomicBool>,
}

fn process_audio(
    data: &[f32],
    input_sample_rate: u32,
    spotter: &KeywordSpotter,
    stream_kws: &Mutex<sherpa_onnx::OnlineStream>,
    app_handle: &tauri::AppHandle,
    _frame_counter: &std::sync::atomic::AtomicU64,
) {
    #[cfg(debug_assertions)]
    let max_val = data.iter().fold(0.0f32, |m, &x| m.max(x.abs()));

    // 优化 6: 降频调试日志 — 每 100 帧且幅值超过阈值时才输出
    #[cfg(debug_assertions)]
    {
        let count = _frame_counter.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        if count % 100 == 0 && max_val > 0.02 {
            let sum_sq = data.iter().map(|&x| x * x).sum::<f32>();
            let rms = (sum_sq / data.len() as f32).sqrt();
            debug!(
                "[KWS Debug] frame #{}, rate: {}, max_amp: {:.4}, rms: {:.4}",
                count, input_sample_rate, max_val, rms
            );
        }
    }

    // 使用静态原子变量存储上一次成功触发的时间戳 (毫秒)，实现 1.5s 唤醒冷却防抖
    static LAST_TRIGGER_MS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

    if let Ok(stream_kws) = stream_kws.lock() {
        // 直接传递物理采样率，使用 sherpa-onnx 底层库原生的高质量重采样逻辑
        stream_kws.accept_waveform(input_sample_rate as i32, data);

        while spotter.is_ready(&stream_kws) {
            spotter.decode(&stream_kws);

            if let Some(res) = spotter.get_result(&stream_kws) {
                if !res.keyword.is_empty() {
                    let now_ms = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_millis() as u64;
                    let last_ms = LAST_TRIGGER_MS.load(std::sync::atomic::Ordering::Relaxed);

                    // 防抖限制: 1.5 秒内不重复向前端发送二次重复触发事件
                    if now_ms.saturating_sub(last_ms) > 1500 {
                        LAST_TRIGGER_MS.store(now_ms, std::sync::atomic::Ordering::Relaxed);
                        info!("[KWS] keyword detected: {}", res.keyword);
                        let _ = app_handle.emit("wake-word-detected", res.keyword.clone());
                    } else {
                        debug!("[KWS] 忽略冷却期内的重复唤醒事件: {}", res.keyword);
                    }
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
    let kw_first_line = keyword.lines().next().unwrap_or(&keyword).to_string();
    info!("[Rust KWS] start_wake_word called (async mode) with keyword: '{}...', model_dir: '{}'", kw_first_line, model_dir);
    let wake_state = state.inner();

    // 1. Ensure any running stream is stopped first
    wake_state.is_running.store(false, std::sync::atomic::Ordering::SeqCst);
    if let Ok(mut stream_opt) = wake_state.stream.lock() {
        if let Some(wrapper) = stream_opt.take() {
            let _ = wrapper.0.pause();
        }
    }

    // Emit initial loading status to frontend
    let _ = app_handle.emit("kws-status", "loading");

    let is_running_arc = wake_state.is_running.clone();
    let stream_mutex = wake_state.stream.clone();
    let app_handle_status = app_handle.clone();
    let app_handle_for_init = app_handle.clone();

    // Spawn an independent background OS thread for ONNX model IO, session creation, and cpal initialization
    std::thread::spawn(move || {
        let run_init = move || -> Result<SendRawWrapper<cpal::Stream>, String> {
            // 2. Validate model files existence
            let mut model_path = PathBuf::from(&model_dir);
            if model_path.is_relative() {
                if !model_path.exists() {
                    if let Ok(current_dir) = std::env::current_dir() {
                        if let Some(parent) = current_dir.parent() {
                            let test_path = parent.join(&model_dir);
                            if test_path.exists() {
                                model_path = test_path;
                            }
                        }
                    }
                }

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

            let mut encoders: Vec<std::path::PathBuf> = Vec::new();
            let mut decoders: Vec<std::path::PathBuf> = Vec::new();
            let mut joiners:  Vec<std::path::PathBuf> = Vec::new();

            if let Ok(entries) = std::fs::read_dir(&model_path) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_file() {
                        if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                            if      name.starts_with("encoder-") && name.ends_with(".onnx") { encoders.push(path); }
                            else if name.starts_with("decoder-") && name.ends_with(".onnx") { decoders.push(path); }
                            else if name.starts_with("joiner-")  && name.ends_with(".onnx") { joiners.push(path); }
                        }
                    }
                }
            }

            let sort_by_epoch = |a: &std::path::PathBuf, b: &std::path::PathBuf| -> std::cmp::Ordering {
                let a_has = a.file_name().and_then(|n| n.to_str()).map(|s| s.contains("epoch-12")).unwrap_or(false);
                let b_has = b.file_name().and_then(|n| n.to_str()).map(|s| s.contains("epoch-12")).unwrap_or(false);
                match (a_has, b_has) {
                    (true, false) => std::cmp::Ordering::Less,
                    (false, true) => std::cmp::Ordering::Greater,
                    _ => a.cmp(b),
                }
            };
            encoders.sort_by(sort_by_epoch);
            decoders.sort_by(sort_by_epoch);
            joiners.sort_by(sort_by_epoch);

            let encoder = encoders.into_iter().next()
                .ok_or_else(|| format!("Could not find encoder ONNX file in model directory (resolved: {})", model_path.display()))?;
            let decoder = decoders.into_iter().next()
                .ok_or_else(|| format!("Could not find decoder ONNX file in model directory (resolved: {})", model_path.display()))?;
            let joiner  = joiners.into_iter().next()
                .ok_or_else(|| format!("Could not find joiner ONNX file in model directory (resolved: {})", model_path.display()))?;

            let tokens = model_path.join("tokens.txt");
            let keywords_file = model_path.join("keywords.txt");

            if !tokens.exists() {
                return Err(format!("tokens.txt not found in directory (resolved: {})", model_path.display()));
            }

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
            config.model_config.num_threads = 2;
            config.model_config.debug = false;
            config.max_active_paths    = max_active_paths.unwrap_or(4);
            config.num_trailing_blanks = num_trailing_blanks.unwrap_or(2);
            config.keywords_score      = keywords_score.unwrap_or(1.5);
            config.keywords_threshold  = keywords_threshold.unwrap_or(0.25);
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

            let spotter_clone = spotter.clone();
            let stream_kws_clone = stream_kws.clone();
            let frame_counter = Arc::new(std::sync::atomic::AtomicU64::new(0));

            is_running_arc.store(true, std::sync::atomic::Ordering::SeqCst);

            let err_fn = move |err| {
                error!("An error occurred on cpal input stream: {}", err);
            };

            let app_handle_cb = app_handle_for_init.clone();
            let is_running_cb = is_running_arc.clone();

            let stream = match sample_format {
                cpal::SampleFormat::F32 => {
                    let frame_counter_f32 = frame_counter.clone();
                    device
                        .build_input_stream(
                            &config_orig.into(),
                            move |data: &[f32], _: &cpal::InputCallbackInfo| {
                                if !is_running_cb.load(std::sync::atomic::Ordering::SeqCst) {
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
                                    &app_handle_cb,
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
                                if !is_running_cb.load(std::sync::atomic::Ordering::SeqCst) {
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
                                    &app_handle_cb,
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

            Ok(SendRawWrapper(stream))
        };

        match run_init() {
            Ok(stream_wrapper) => {
                if let Ok(mut stream_opt) = stream_mutex.lock() {
                    *stream_opt = Some(stream_wrapper);
                }
                info!("[Rust KWS] Asynchronous KWS initialization completed successfully.");
                let _ = app_handle_status.emit("kws-status", "ready");
            }
            Err(err_msg) => {
                error!("[Rust KWS] Asynchronous init failed: {}", err_msg);
                let _ = app_handle_status.emit("kws-status", format!("error: {}", err_msg));
            }
        }
    });

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
    
    // 无论窗口是否可见，一律先关闭旧实例，等待注册表注销后再重建
    // 这样可彻底避免 HMR 导致 WebView 失效的白屏问题
    if let Some(win) = app_handle.get_webview_window("settings") {
        info!("[Rust Window] Closing existing settings window before recreating...");
        let _ = win.close();
        // close() 异步执行，阻塞等待 Tauri 注册表完成注销，避免 "already exists" 竞态
        std::thread::sleep(std::time::Duration::from_millis(300));
        info!("[Rust Window] Stale settings window closed, proceeding to create new one...");
    }

    info!("[Rust Window] Settings window not found in registry, creating dynamically...");
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
    .additional_browser_args("--use-fake-ui-for-media-stream")
    .center();

    match builder.build() {
        Ok(win) => {
            info!("[Rust Window] Settings window created successfully");
            let _ = win.show();
            let _ = win.set_focus();
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
fn close_settings_window(app_handle: tauri::AppHandle) -> Result<(), String> {
    info!("[Rust Window] close_settings_window command triggered");
    if let Some(win) = app_handle.get_webview_window("settings") {
        // 使用 close() 完全销毁窗口（而非 hide()），避免 HMR 热更新后 WebView 实例失效导致再次打开时白屏
        let _ = win.close();
        info!("[Rust Window] Settings window closed and destroyed successfully");
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
            stream: Arc::new(Mutex::new(None)),
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
            #[cfg(target_os = "linux")]
            {
                std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
                std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
                std::env::set_var("LIBGL_ALWAYS_SOFTWARE", "1");
            }
            #[cfg(target_os = "linux")]
            if let Some(window) = app.get_webview_window("main") {
                use webkit2gtk::PermissionRequestExt;
                use webkit2gtk::WebViewExt;
                let _ = window.with_webview(|webview| {
                    let gtk_webview = webview.inner();
                    gtk_webview.connect_permission_request(|_, req| {
                        info!("[Linux WebKit] 自动批准媒体设备权限请求");
                        req.allow();
                        true
                    });
                });
            }

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
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    info!("[Rust Window] 主窗口已销毁，清理后台资源并退出");
                    std::thread::spawn(|| {
                        // 关闭 stderr (fd 2)，抑制 WebView2/Chromium 析构时打印的
                        // Chrome_WidgetWin_0 UnregisterClass 噪音日志。
                        // 使用 C 运行时 _close()，无需额外依赖。
                        #[cfg(target_os = "windows")]
                        unsafe {
                            extern "C" { fn _close(fd: i32) -> i32; }
                            _close(2);
                        }
                        std::thread::sleep(std::time::Duration::from_millis(150));
                        std::process::exit(0);
                    });
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
