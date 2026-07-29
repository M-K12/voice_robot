import os
import logging
from logging.handlers import TimedRotatingFileHandler

LOGS_DIR = os.path.abspath("logs")
BACKEND_LOG_DIR = os.path.join(LOGS_DIR, "backend")
FRONTEND_LOG_DIR = os.path.join(LOGS_DIR, "frontend")

frontend_logger = logging.getLogger("xiaoan.frontend")
_backend_file_handler = None
_console_handler = None

def _get_level_int(level_str: str, default: int = logging.INFO) -> int:
    if not level_str or not isinstance(level_str, str):
        return default
    lvl_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    return lvl_map.get(level_str.upper().strip(), default)

def setup_logging(console_level: str = "INFO", file_level: str = "WARNING"):
    """初始化前后端日志，支持显示等级 (console_level) 与保存等级 (file_level)"""
    global _backend_file_handler, _console_handler

    os.makedirs(BACKEND_LOG_DIR, exist_ok=True)
    os.makedirs(FRONTEND_LOG_DIR, exist_ok=True)

    console_lvl = _get_level_int(console_level, logging.INFO)
    file_lvl = _get_level_int(file_level, logging.WARNING)

    # 统一格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 1. 后端 TimedRotatingFileHandler (按天轮转，保留 60 天，等级为 file_lvl)
    backend_file_path = os.path.join(BACKEND_LOG_DIR, "backend.log")
    _backend_file_handler = TimedRotatingFileHandler(
        filename=backend_file_path,
        when="MIDNIGHT",
        interval=1,
        backupCount=60,
        encoding="utf-8"
    )
    _backend_file_handler.setLevel(file_lvl)
    _backend_file_handler.setFormatter(formatter)

    # 2. 前端 TimedRotatingFileHandler (按天轮转，保留 60 天)
    frontend_file_path = os.path.join(FRONTEND_LOG_DIR, "frontend.log")
    frontend_file_handler = TimedRotatingFileHandler(
        filename=frontend_file_path,
        when="MIDNIGHT",
        interval=1,
        backupCount=60,
        encoding="utf-8"
    )
    frontend_file_handler.setLevel(logging.INFO)
    frontend_file_handler.setFormatter(formatter)

    # 配置根日志器
    root_logger = logging.getLogger()
    # 根 Log 门限需设为 min(console, file)，确保两条链均能接收日志
    min_lvl = min(console_lvl, file_lvl)
    root_logger.setLevel(min_lvl)

    # 查找并绑定 Console StreamHandler
    for h in root_logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, TimedRotatingFileHandler):
            _console_handler = h
            break

    if _console_handler:
        _console_handler.setLevel(console_lvl)
    
    # 绑定 Backend File Handler
    existing_handler_files = [
        getattr(h, 'baseFilename', '') for h in root_logger.handlers if isinstance(h, TimedRotatingFileHandler)
    ]
    if backend_file_path not in existing_handler_files:
        root_logger.addHandler(_backend_file_handler)

    xiaoan_logger = logging.getLogger("xiaoan")
    xiaoan_logger.setLevel(min_lvl)

    # 前端 Logger 单独处理，避免写入后端日志文件
    frontend_logger.setLevel(logging.INFO)
    frontend_logger.propagate = False
    if not frontend_logger.handlers:
        frontend_logger.addHandler(frontend_file_handler)

    # 屏蔽第三方 HTTP 库的冲刷日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    logging.info(f"[Logging] 日志级别同步就绪 | 控制台显示: {logging.getLevelName(console_lvl)} | 磁盘保存: {logging.getLevelName(file_lvl)}")

def update_logging_levels(console_level: str = "INFO", file_level: str = "WARNING"):
    """动态更热更新控制台与日志文件的 Logger 级别，无需重启后端"""
    global _backend_file_handler, _console_handler

    console_lvl = _get_level_int(console_level, logging.INFO)
    file_lvl = _get_level_int(file_level, logging.WARNING)

    root_logger = logging.getLogger()
    min_lvl = min(console_lvl, file_lvl)
    root_logger.setLevel(min_lvl)

    xiaoan_logger = logging.getLogger("xiaoan")
    xiaoan_logger.setLevel(min_lvl)

    if _console_handler:
        _console_handler.setLevel(console_lvl)

    if _backend_file_handler:
        _backend_file_handler.setLevel(file_lvl)

    logging.info(f"[Logging] 热更新日志级别 -> 控制台显示: {logging.getLevelName(console_lvl)} | 磁盘保存: {logging.getLevelName(file_lvl)}")
