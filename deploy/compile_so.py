"""
================================================================================
沙盒模式 Cython 编译引擎 (.py → .so / .pyd)
用法:
  python deploy/compile_so.py <target_dir>
  示例: python deploy/compile_so.py deploy/staging_backend/backend
================================================================================
"""

import os
import sys
import glob
import shutil
from setuptools import setup, Extension
from Cython.Build import cythonize

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)

# 解析目标目录参数
target_dir_arg = "backend"
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    target_dir_arg = sys.argv[1]

# 计算绝对路径
if os.path.isabs(target_dir_arg):
    target_dir_abs = target_dir_arg
else:
    target_dir_abs = os.path.abspath(os.path.join(project_root, target_dir_arg))

base_work_dir = os.path.dirname(target_dir_abs) if os.path.basename(target_dir_abs) in ["backend", "pyside_app"] else project_root
os.chdir(base_work_dir)

EXCLUDE_FILES = {
    "main.py",
    "compile_so.py",
    "build_backend.py",
    "build_pyside.py",
    "__init__.py",
    "_virtualenv.py",
    "activate_this.py"
}

EXCLUDE_DIRS = {
    "build", "dist", "temp_py_backup", "__pycache__",
    "venv", ".venv", "node_modules", ".git"
}


def collect_py_files(target_dir: str) -> list:
    results = []
    if not os.path.isdir(target_dir):
        return results

    for dirpath, dirnames, filenames in os.walk(target_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.startswith("_virtualenv") or fn.startswith("activate_this") or fn.startswith("."):
                continue
            if fn.endswith(".py") and fn not in EXCLUDE_FILES:
                rel_path = os.path.relpath(os.path.join(dirpath, fn), base_work_dir)
                results.append(rel_path)
    return sorted(results)


py_files = collect_py_files(target_dir_abs)

if not py_files:
    print(f"⚠️ [Cython SandBox Build] 在 [{target_dir_abs}] 目录下未找到需要编译的 .py 文件")
    sys.exit(0)

module_name_tag = os.path.basename(target_dir_abs)
print("=" * 64)
print(f"  🚀 Cython 沙盒编译: .py → .so / .pyd (工作沙盒: {target_dir_abs})")
print("=" * 64)
print(f"工作根目录: {base_work_dir}")
print(f"搜集到 {len(py_files)} 个源文件:")
for f in py_files:
    print(f"  • {f}")
print()

ext_modules = []
for f in py_files:
    mod_name = os.path.splitext(f)[0].replace(os.sep, ".")
    ext = Extension(
        mod_name,
        [f],
        extra_compile_args=["-O3", "-Wno-unused-function", "-Wno-unreachable-code"] if sys.platform != "win32" else ["/O2"]
    )
    ext_modules.append(ext)

extensions = cythonize(
    ext_modules,
    language_level="3",
    compiler_directives={
        "boundscheck": False,
        "wraparound": False,
        "annotation_typing": False,
    },
)

packages = [module_name_tag]
for root, dirs, _ in os.walk(target_dir_abs):
    for d in dirs:
        if not d.startswith(".") and d not in EXCLUDE_DIRS:
            packages.append(os.path.relpath(os.path.join(root, d), base_work_dir).replace(os.sep, "."))
packages = list(set(packages))

sys.argv = [sys.argv[0], "build_ext", "--inplace"]

setup(
    name=f"xiaoan_sandbox_{module_name_tag}",
    ext_modules=extensions,
    package_dir={"": "."},
    packages=packages,
    script_args=["build_ext", "--inplace"],
)

print()
print("-" * 64)
print("🧹 编译完成，正在清理沙盒内中间 .c / .cpp 文件...")

for py_file in py_files:
    base_path = os.path.splitext(py_file)[0]
    for ext in [".c", ".cpp"]:
        c_file = base_path + ext
        if os.path.isfile(c_file):
            try:
                os.remove(c_file)
                print(f"  🗑️ 删除中间文件: {c_file}")
            except Exception:
                pass

compiled_count = 0
for py_file in py_files:
    module_name = os.path.splitext(py_file)[0]
    parent_dir = os.path.dirname(py_file) or "."
    base_name = os.path.basename(module_name)
    
    patterns = [
        os.path.join(parent_dir, f"{base_name}.cpython-*.so"),
        os.path.join(parent_dir, f"{base_name}.cpython-*.pyd"),
        os.path.join(parent_dir, f"{base_name}.so"),
        os.path.join(parent_dir, f"{base_name}.pyd"),
    ]
    found_files = []
    for pat in patterns:
        found_files.extend(glob.glob(pat))
        
    if found_files:
        compiled_count += 1
        for sf in found_files:
            print(f"  ✅ {py_file} → {sf}")
    else:
        print(f"  ❌ {py_file} 编译失败")

if os.path.exists("build"):
    shutil.rmtree("build", ignore_errors=True)

print("=" * 64)
print(f"🎉 沙盒 Cython 编译完成！成功生成库: {compiled_count}/{len(py_files)}")
print("=" * 64)
