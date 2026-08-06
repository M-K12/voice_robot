# -*- mode: python ; coding: utf-8 -*-

import os

# 动态定位目录
deploy_dir = os.path.abspath(SPECPATH)
project_root = os.path.dirname(deploy_dir)
backend_dir = os.path.join(project_root, 'backend')

from PyInstaller.utils.hooks import collect_dynamic_libs

# 自动搜集 sherpa_onnx 及其依赖库目录 (sherpa_onnx.libs) 中的所有 .so 动态库
sherpa_binaries = collect_dynamic_libs('sherpa_onnx')
try:
    import site
    for site_dir in site.getsitepackages():
        libs_dir = os.path.join(site_dir, 'sherpa_onnx.libs')
        if os.path.isdir(libs_dir):
            for f in os.listdir(libs_dir):
                if f.endswith('.so') or '.so.' in f:
                    sherpa_binaries.append((os.path.join(libs_dir, f), '.'))
except Exception:
    pass

a = Analysis(
    [os.path.join(backend_dir, 'main.py')],
    pathex=[backend_dir],
    binaries=[
        (os.path.join(backend_dir, '*.so'), '.'),   # Cython 编译后的 .so 模块
        (os.path.join(backend_dir, 'tools', '*.so'), 'tools'),
    ] + sherpa_binaries,
    datas=[
        (os.path.join(project_root, '.env'), '.'),
        (os.path.join(backend_dir, 'assets'), 'assets'),
    ],
    hiddenimports=[
        # ── 项目自身模块 (.so) ──
        'address_corrector', 'amap_service', 'audio_manager',
        'fengyu_service', 'knowledge_service', 'local_voice_handler',
        'logger_setup', 'moji_service', 'omni_realtime_client',
        'qwen_audio_realtime_handler', 'qwen_omni_realtime_handler',
        'sse_hub', 'utils', 'weather_mock', 'weather_router',
        'weather_service', 'xunfei_realtime_handler',
        'tools', 'tools.handlers', 'tools.schemas',

        # ── 第三方依赖 (编译为 .so 后 PyInstaller 无法自动发现) ──
        'httpx', 'httpx._transports', 'httpx._transports.default',
        'httpcore', 'httpcore._async', 'httpcore._sync',
        'h11',
        'dashscope',
        'dashscope.audio', 'dashscope.audio.asr',
        'dashscope.audio.tts_v2',
        'openai', 'openai.resources',
        'numpy',
        'dotenv',
        'fastapi', 'fastapi.middleware', 'fastapi.middleware.cors',
        'uvicorn', 'uvicorn.config', 'uvicorn.main',
        'starlette', 'starlette.websockets', 'starlette.middleware',
        'pydantic', 'pydantic_core',
        'sherpa_onnx',
        'anyio', 'anyio._backends', 'anyio._backends._asyncio',
        'sniffio',
        'certifi', 'idna', 'charset_normalizer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend',
)
