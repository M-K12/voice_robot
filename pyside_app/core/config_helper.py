import os
import json
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def get_configs_dir() -> str:
    """独立定位 configs 配置文件路径，完全解耦后端代码"""
    candidates = [
        os.path.join(sys.executable if getattr(sys, 'frozen', False) else PROJECT_ROOT, "configs"),
        os.path.join(PROJECT_ROOT, "configs"),
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.isdir(c):
            return c
    return os.path.join(PROJECT_ROOT, "configs")


def load_app_config() -> dict:
    """
    前端专属极轻量配置读取器，彻底零依赖 backend/ 任何代码。
    依次合并 global.json, frontend_config.json, kws_config.json 与 model_config.json。
    """
    config = {}
    cfg_dir = get_configs_dir()
    
    # 依次读取四大通用配置文件
    for json_name in ["global.json", "frontend_config.json", "kws_config.json", "model_config.json"]:
        path = os.path.join(cfg_dir, json_name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        config.update(data)
            except Exception:
                pass
                
    return config
