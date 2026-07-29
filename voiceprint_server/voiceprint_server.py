"""
Xiaoan Voiceprint Cloud Hosting Service v2.0
专门用于托管和提供阿里云 DashScope 实时语音 API 声纹音频文件的 FastAPI 公网托管服务。
部署端口：8777
"""

import os
import shutil
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from fastapi import FastAPI, Request, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(
    title="Xiaoan Voiceprint Cloud Hosting Service",
    description="专门用于托管和提供阿里云 DashScope 实时语音 API 声纹音频文件的 FastAPI 公网服务",
    version="2.0.0"
)

# 开启全跨域支持 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据与音频存储目录
BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "voiceprints"

STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# 挂载静态音频服务目录：让 DashScope 可以直接 GET http://8.141.83.146:8777/voiceprints/xxx.wav
app.mount("/voiceprints", StaticFiles(directory=str(STORAGE_DIR)), name="voiceprints")


def _get_request_base_url(request: Request) -> str:
    """获取标准的 HTTP/HTTPS 协议 Base URL"""
    base_url = str(request.base_url).rstrip("/")
    if base_url.startswith("ws://"):
        base_url = "http://" + base_url[5:]
    elif base_url.startswith("wss://"):
        base_url = "https://" + base_url[6:]
    return base_url


def _role_dir(role_name: str) -> Path:
    """返回角色子目录路径，不做创建操作"""
    return STORAGE_DIR / role_name


def _build_sample_url(base_url: str, role_name: str, filename: str) -> str:
    """构造公网访问 URL，格式为: {base_url}/voiceprints/{role_name}/{filename}"""
    return f"{base_url}/voiceprints/{role_name}/{filename}"


@app.get("/health")
def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "Xiaoan Voiceprint Cloud Hosting Service",
        "version": "2.0.0",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


@app.get("/api/voiceprints", response_model=List[Dict[str, Any]])
def list_voiceprints(request: Request):
    """获取所有已托管声纹角色及最新 5 个采样公网 URL 矩阵（基于物理文件系统遍历）"""
    base_url = _get_request_base_url(request)
    result = []
    
    if not STORAGE_DIR.exists():
        return result

    for item in STORAGE_DIR.iterdir():
        if not item.is_dir():
            continue
            
        role_name = item.name
        
        # 遍历读取该角色目录下的音频文件
        audio_files = [f for f in item.iterdir() if f.is_file() and f.suffix.lower() in [".wav", ".mp3", ".m4a", ".pcm"]]
        
        # 按修改时间倒序排列（最新在最前面）
        audio_files_sorted = sorted(audio_files, key=lambda f: f.stat().st_mtime, reverse=True)
        
        formatted_samples = []
        for f in audio_files_sorted:
            fname = f.name
            mtime_str = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            formatted_samples.append({
                "id": fname,
                "filename": fname,
                "created_at": mtime_str,
                "url": _build_sample_url(base_url, role_name, fname)
            })
            
        latest_5 = formatted_samples[:5]
        sample_urls = [s["url"] for s in latest_5]

        # 角色目录创建/更新时间
        role_created_at = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        
        result.append({
            "id": role_name,
            "name": role_name,
            "sample_count": len(formatted_samples),
            "latest_file": latest_5[0]["filename"] if latest_5 else "",
            "urls": sample_urls,
            "samples": formatted_samples,
            "created_at": role_created_at
        })
        
    return result


@app.post("/api/voiceprints")
async def upload_voiceprint(
    request: Request,
    name: str = Form(...),
    custom_filename: str = Form(None),
    file: UploadFile = File(...)
):
    """
    上传并保存声纹 WAV 文件至角色子目录（voiceprints/{role_name}/{filename}）。
    按物理文件修改时间执行 FIFO 5个采样滑动淘汰算法。
    """
    role_name = name.strip() or "未命名角色"
    role_dir = _role_dir(role_name)
    role_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S")
    
    if custom_filename and custom_filename.strip():
        filename = custom_filename.strip()
    else:
        filename = f"{timestamp_str}.wav"

    save_path = role_dir / filename

    try:
        contents = await file.read()
        if len(contents) < 100:
            raise HTTPException(status_code=400, detail="音频文件过小，无效的音频数据")

        with open(save_path, "wb") as f:
            f.write(contents)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存声纹音频文件失败: {str(e)}")

    # 物理文件 FIFO 淘汰规则：单角色目录超 5 个音频文件时清理最老的物理文件
    audio_files = [f for f in role_dir.iterdir() if f.is_file() and f.suffix.lower() in [".wav", ".mp3", ".m4a", ".pcm"]]
    audio_files_sorted = sorted(audio_files, key=lambda f: f.stat().st_mtime)  # 从旧到新
    
    while len(audio_files_sorted) > 5:
        oldest_file = audio_files_sorted.pop(0)
        try:
            oldest_file.unlink()
            print(f"[Cloud FIFO] 超过5份限制，已自动清理旧采样物理文件: {role_name}/{oldest_file.name}")
        except Exception as del_e:
            print(f"[Cloud FIFO Warning] 清理旧采样物理文件失败: {del_e}")

    base_url = _get_request_base_url(request)
    public_url = _build_sample_url(base_url, role_name, filename)
    print(f"\033[92m[Voiceprint Cloud] 成功保存声纹角色『{role_name}』采样: {filename} -> {public_url}\033[0m")

    return {
        "id": role_name,
        "name": role_name,
        "filename": filename,
        "url": public_url,
        "message": "声纹上传与云端托管成功"
    }


@app.delete("/api/voiceprints/{vp_id}")
def delete_voiceprint(vp_id: str):
    """删除指定角色及其在公网 8777 服务器上的整个角色音频目录"""
    role_name = vp_id.strip()
    role_dir = _role_dir(role_name)

    if not role_dir.exists() or not role_dir.is_dir():
        raise HTTPException(status_code=404, detail="未找到对应的声纹角色目录")

    try:
        shutil.rmtree(role_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除角色目录失败: {str(e)}")

    return {"status": "success", "message": f"成功删除公网声纹角色及音频文件目录: {role_name}"}


if __name__ == "__main__":
    # 默认监听所有网卡的 8777 端口
    uvicorn.run(app, host="0.0.0.0", port=8777)
