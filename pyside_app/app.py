import os
import sys
import json
import time

# 记录应用启动时刻时间戳
START_TIME = time.time()

# 将根目录添加到 sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# 标准规范做法：在非 Windows (Linux/macOS) 平台上，ONNX Runtime 的 .so 需以 RTLD_GLOBAL 标志预载暴露符号，供依赖 C++ 扩展 (sherpa_onnx) 链接
import ctypes

def _init_onnxruntime_symbols():
    try:
        import onnxruntime
        if sys.platform != "win32" and hasattr(onnxruntime, "__file__"):
            capi_dir = os.path.join(os.path.dirname(onnxruntime.__file__), "capi")
            if os.path.exists(capi_dir):
                for fn in os.listdir(capi_dir):
                    if fn.startswith("libonnxruntime.so"):
                        try:
                            ctypes.CDLL(os.path.join(capi_dir, fn), mode=getattr(ctypes, "RTLD_GLOBAL", 1))
                        except Exception:
                            pass
    except ImportError:
        pass

_init_onnxruntime_symbols()

import signal
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from loguru import logger

from pyside_app.core.audio_kws import AudioKwsThread
from pyside_app.core.audio_aec import AECProcessor
from pyside_app.core.bot_engine import VoiceBotEngine
from pyside_app.core.config_helper import load_app_config
from pyside_app.core.hotkey_manager import GlobalHotkeyManager
from pyside_app.ui.main_window import MainWindow


def get_kws_model_dir():
    # 从 configs/kws_config.json 动态读取
    config_file = os.path.join(PROJECT_ROOT, "configs", "kws_config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                model_dir = data.get("sherpa_model_dir", "")
                if model_dir and os.path.exists(model_dir):
                    return model_dir
        except Exception as e:
            logger.warning(f"读取 kws_config.json 失败: {e}")

    # 默认路径
    default_dir = os.path.join(PROJECT_ROOT, "sherpa", "models", "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01")
    return default_dir


def configure_logger():
    """从 configs/global.json 动态配置 loguru 控制台日志输出级别"""
    logger.remove()
    global_config_path = os.path.join(PROJECT_ROOT, "configs", "global.json")
    console_log_level = "INFO"
    if os.path.exists(global_config_path):
        try:
            with open(global_config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                console_log_level = cfg.get("log_level", "INFO").upper()
        except Exception:
            pass
    logger.add(sys.stderr, level=console_log_level)


def main():
    configure_logger()
    logger.info("🚀 启动小安语音机器人...")

    # 1. 创建应用程序单例
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)

    # 2. 查找模型目录与创建 KWS 线程
    model_dir = get_kws_model_dir()
    logger.info(f"KWS 唤醒模型解析目标: {model_dir}")
    kws_thread = AudioKwsThread(model_dir=model_dir)

    # 3. 读取前端设置并创建全局热键管理器
    frontend_cfg = load_app_config()
    silent_startup = bool(frontend_cfg.get("silent_startup", False))
    shortcut_str = str(frontend_cfg.get("global_shortcut", "Alt+X"))

    hotkey_mgr = GlobalHotkeyManager(shortcut_str=shortcut_str)

    # 4. 创建主业务引擎与主界面窗口
    bot_engine = VoiceBotEngine()
    window = MainWindow(bot_engine=bot_engine, kws_thread=kws_thread, hotkey_mgr=hotkey_mgr)
    window.resize(1120, 720)

    # 🔇 SpeexDSP AEC 回声消除初始化
    # 从设置页读取 aec_filter_length，没有配置则默认 2048 (外置音筒+桌面麦 128ms 回声尾)
    aec_filter_length = int(frontend_cfg.get("aec_filter_length", 2048))
    aec_processor = AECProcessor(filter_length=aec_filter_length)
    # 将 AEC 处理器注入播放器 (Far-end 推送) 与 KWS 线程 (Near-end 处理)
    bot_engine.audio_player._stream_player.set_aec_processor(aec_processor)
    kws_thread.set_aec_processor(aec_processor)
    logger.info(f"🔇 AEC 回声消除应用就绪: {aec_processor}")

    hotkey_mgr.signal_hotkey_triggered.connect(window.toggle_visibility)
    hotkey_mgr.register_qt_shortcut(window)
    hotkey_mgr.start_global_listener()

    # 5. 注册 SIGINT (Ctrl+C) 优雅退出处理器
    signal.signal(signal.SIGINT, lambda *args: app.quit())
    sig_timer = QTimer()
    sig_timer.start(300)
    sig_timer.timeout.connect(lambda: None)  # 激活 GIL 允许 Python 捕获 SIGINT 信号

    def cleanup():
        logger.info("🛑 正在优雅清理后台子线程与 WebSocket 连接...")
        try:
            hotkey_mgr.stop_global_listener()
            kws_thread.stop()
            bot_engine.close()
        except Exception:
            pass

    app.aboutToQuit.connect(cleanup)

    # 6. 静默启动控制与唤醒
    if silent_startup and QSystemTrayIcon.isSystemTrayAvailable():
        logger.info(f"🌙 [静默启动模式] 已开启静默驻留系统托盘 (按快捷键 '{shortcut_str}' 可随时唤醒，极低资源消耗)")
    else:
        if bool(frontend_cfg.get("start_fullscreen", False)):
            window.showFullScreen()
        else:
            window.show()

    kws_thread.start()

    cost_ms = (time.time() - START_TIME) * 1000
    logger.info(f"⚡ [极速启动完成] 从程序加载到 GUI 呈现共耗时: {cost_ms:.2f} ms")

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        logger.info("👋 接收到 Ctrl+C 终止信号，程序已安全退出。")
        sys.exit(0)


if __name__ == "__main__":
    main()
