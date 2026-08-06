"""
后端 .py → .so 编译脚本 (Cython)
递归编译 backend/ 下所有 .py 文件（含 tools/ 子包）
用法: python deploy/compile_so.py build_ext --inplace
"""

import os
import sys
import glob
import shutil
import json
from setuptools import setup, Extension
from Cython.Build import cythonize

# ── 配置 ──
# 所有可能的 Handler 模块
ALL_HANDLER_FILES = {
    "xunfei_realtime_handler.py",
    "qwen_audio_realtime_handler.py",
    "qwen_omni_realtime_handler.py",
    "omni_realtime_client.py",
    "local_voice_handler.py",
}

# 基础不编译的文件和目录
EXCLUDE_FILES = {"main.py", "compile_so.py", "__init__.py", "voice_worker.py", "_virtualenv.py", "activate_this.py"}
EXCLUDE_DIRS = {"build", "dist", "temp_py_backup", "__pycache__", "venv", ".venv"}

# ── 定位目录 ──
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
os.chdir(project_root)

# ── 编译所有的 Handler 模块，确保完整功能和全模型支持 ──
print(f"📦 全量编译所有 Backend Handler 模块: {sorted(list(ALL_HANDLER_FILES))}")

# ── 递归收集需要编译的 backend 目录下 .py 文件 ──
def collect_py_files(target_dir: str) -> list:
    """递归收集 target_dir 下所有需编译的 .py 文件"""
    results = []
    for dirpath, dirnames, filenames in os.walk(target_dir):
        # 过滤排除的子目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.startswith("_virtualenv") or fn.startswith("activate_this") or fn.startswith("."):
                continue
            if fn.endswith(".py") and fn not in EXCLUDE_FILES:
                rel_path = os.path.relpath(os.path.join(dirpath, fn), project_root)
                results.append(rel_path)
    return sorted(results)

py_files = collect_py_files("backend")

if not py_files:
    print("⚠️ 未找到需要编译的 .py 文件")
    sys.exit(0)

print("=" * 56)
print("  Cython 编译: .py → .so")
print("=" * 56)
print(f"项目根目录: {project_root}")
print(f"将编译以下 {len(py_files)} 个文件:")
for f in py_files:
    print(f"  • {f}")
print()

# ── Cython 编译 ──
ext_modules = [
    Extension(
        os.path.splitext(f)[0].replace(os.sep, "."),
        [f],
        extra_compile_args=["-O3", "-Wno-unused-function", "-Wno-unreachable-code"],
    )
    for f in py_files
]

extensions = cythonize(
    ext_modules,
    language_level="3",
    compiler_directives={
        "boundscheck": False,
        "wraparound": False,
        "annotation_typing": False,  # 允许 FastAPI 使用 Query/Path/Body 等对象作为类型注解默认值
    },
)

setup(
    name="voice_robot_backend",
    ext_modules=extensions,
    package_dir={"": "."},
    packages=["backend", "backend.tools"],
    script_args=["build_ext", "--inplace"],
)

# ── 编译后清理 ──
print()
print("-" * 56)
print("编译完成，开始清理中间 C 文件...")

# 1. 删除 .c 中间文件
for py_file in py_files:
    c_file = os.path.splitext(py_file)[0] + ".c"
    if os.path.isfile(c_file):
        os.remove(c_file)
        print(f"  🗑️ 删除中间文件: {c_file}")

# 2. 检查编译结果
compiled_count = 0
for py_file in py_files:
    module_name = os.path.splitext(py_file)[0]
    parent_dir = os.path.dirname(py_file) or "."
    so_pattern = os.path.join(parent_dir, f"{os.path.basename(module_name)}.cpython-*.so")
    so_files = glob.glob(so_pattern)
    if so_files:
        compiled_count += 1
        for sf in so_files:
            print(f"  ✅ {py_file} → {sf}")
    else:
        print(f"  ❌ {py_file} 编译失败（未找到 .so）")

# 3. 删除 build 目录
if os.path.exists("build"):
    shutil.rmtree("build")
    print("  🗑️ 删除 build/ 目录")

print()
print("=" * 56)
print(f"✅ 完成！成功编译 {compiled_count}/{len(py_files)} 个模块")
print("=" * 56)
