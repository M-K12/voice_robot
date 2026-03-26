mod livekit_manager;
mod wake_word;

use std::sync::Arc;
use tokio::sync::Mutex;
use livekit_manager::LivekitManager;

#[tauri::command]
async fn start_wake_word(
    app: tauri::AppHandle,
    access_key: String,
    keyword_paths: Vec<String>,
    model_path: String,
) -> Result<(), String> {
    wake_word::start(app, access_key, keyword_paths, model_path)
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn stop_wake_word() -> Result<(), String> {
    wake_word::stop();
    Ok(())
}

#[tauri::command]
async fn set_fullscreen(window: tauri::Window, fullscreen: bool) -> Result<(), String> {
    window.set_fullscreen(fullscreen).map_err(|e| e.to_string())
}

#[tauri::command]
async fn set_always_on_top(window: tauri::Window, on_top: bool) -> Result<(), String> {
    window.set_always_on_top(on_top).map_err(|e| e.to_string())
}

#[tauri::command]
async fn start_livekit_connection(
    url: String,
    token: String,
    state: tauri::State<'_, Arc<Mutex<LivekitManager>>>,
) -> Result<(), String> {
    let mut manager = state.lock().await;
    manager.connect(&url, &token).await
}

#[tauri::command]
async fn stop_livekit_connection(
    state: tauri::State<'_, Arc<Mutex<LivekitManager>>>,
) -> Result<(), String> {
    let mut manager = state.lock().await;
    manager.disconnect().await;
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Arc::new(Mutex::new(LivekitManager::new())))
        .invoke_handler(tauri::generate_handler![
            start_wake_word,
            stop_wake_word,
            set_fullscreen,
            set_always_on_top,
            start_livekit_connection,
            stop_livekit_connection,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
