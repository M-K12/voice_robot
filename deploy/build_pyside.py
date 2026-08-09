"""
================================================================================
PySide6 桌面前端【沙盒模式 (Staging Build)】专属一键打包脚本
优势:
  1. 零原源码污染: 原始源码目录完全只读，只在临时沙盒 staging_pyside 中编译打包
  2. 源码物理隔离: 沙盒内自动抹除 .py 源码 (保留 app.py)，强迫 PyInstaller 只依赖二进制 .so / .pyd 库
  3. 绝对零残留: 打包完成后整盘销毁沙盒，源码目录绝不会留下任何 .so / .pyd / .c 垃圾
用法:
  python deploy/build_pyside.py
================================================================================
"""

import os
import sys
import shutil
import subprocess
import ast

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
os.chdir(project_root)

staging_dir = os.path.join(script_dir, "staging_pyside")
pyside_staging = os.path.join(staging_dir, "pyside_app")


def run_command(cmd, cwd=project_root):
    print(f"👉 运行指令: {cmd}")
    res = subprocess.run(cmd, shell=True, cwd=cwd)
    if res.returncode != 0:
        raise RuntimeError(f"指令执行失败 (exit code: {res.returncode}): {cmd}")


def clean_staging():
    """彻底销毁临时构建沙盒"""
    if os.path.exists(staging_dir):
        try:
            shutil.rmtree(staging_dir, ignore_errors=True)
            print("🧹 [沙盒销毁] 已彻底清空删除临时构建沙盒 directory")
        except Exception as e:
            print(f"⚠️ 清理沙盒目录提示: {e}")


def extract_third_party_imports(src_dir):
    """在擦除源码前，通过 AST 语法树解析源码中实际调用的第三方库 (跳过 Python 标准库及项目内模块)"""
    stdlib = sys.stdlib_module_names if hasattr(sys, "stdlib_module_names") else set()
    local_dirs = {d for d in os.listdir(src_dir) if os.path.isdir(os.path.join(src_dir, d))}
    
    imports = set()
    for dirpath, _, filenames in os.walk(src_dir):
        for fn in filenames:
            if fn.endswith(".py"):
                filepath = os.path.join(dirpath, fn)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        tree = ast.parse(f.read(), filename=filepath)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                top_name = alias.name.split(".")[0]
                                if top_name and top_name not in stdlib and top_name not in local_dirs and top_name not in ["backend", "pyside_app", "app"]:
                                    imports.add(top_name)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                top_name = node.module.split(".")[0]
                                if top_name and top_name not in stdlib and top_name not in local_dirs and top_name not in ["backend", "pyside_app", "app"]:
                                    imports.add(top_name)
                except Exception:
                    pass
    return imports


def main():
    print("=" * 66)
    print(" 🖥️ Voice Robot PySide6 桌面前端专属打包系统 [Staging 独立沙盒构建模式]")
    print("=" * 66)

    py_exec = sys.executable

    try:
        # 1. 准备干净的构建沙盒
        clean_staging()
        os.makedirs(staging_dir, exist_ok=True)

        print("\n【步骤 1/4】复制桌面前端源码至临时沙盒区 (原源码目录保持只读)...")
        src_pyside = os.path.join(project_root, "pyside_app")
        shutil.copytree(src_pyside, pyside_staging)
        print("  ✅ 源代码已镜像克隆至沙盒工作区")

        # 💡 在擦除源码之前，先利用 AST 解析提取源码中引用的所有第三方依赖
        third_party_deps = extract_third_party_imports(pyside_staging)
        print(f"  🔍 从源码精准分析提取到 {len(third_party_deps)} 个第三方依赖: {sorted(list(third_party_deps))}")

        # 自动切换沙盒配置中的 production_mode 为 true (仅影响打包产物，绝不触碰本地开发配置)
        try:
            import json
            cfg_path = os.path.join(project_root, "configs", "frontend_config.json")
            staging_configs_dir = os.path.join(staging_dir, "configs")
            os.makedirs(staging_configs_dir, exist_ok=True)
            staging_cfg_path = os.path.join(staging_configs_dir, "frontend_config.json")
            
            fcfg = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    fcfg = json.load(f)
            fcfg["production_mode"] = True
            with open(staging_cfg_path, "w", encoding="utf-8") as f:
                json.dump(fcfg, f, ensure_ascii=False, indent=4)
            print("  🔒 已全自动将生产打包标记写入沙盒配置: production_mode = True")
        except Exception as e:
            print(f"  ⚠️ 自动设置生产配置标记提示: {e}")

        # 2. 在沙盒内执行 Cython 编译
        print("\n【步骤 2/4】在沙盒区编译所有 Python 模块为二进制扩展 (.so/.pyd)...")
        compile_script = os.path.join(script_dir, "compile_so.py")
        run_command(f'"{py_exec}" "{compile_script}" "{pyside_staging}"', cwd=staging_dir)

        # 3. 在沙盒区内删除 .py 源码以进行打包防护 (除 app.py 入口及 __init__.py 包声明)
        print("\n【步骤 3/4】在沙盒区内清除 .py 源码，防止源码打入产物包...")
        py_deleted_count = 0
        for dirpath, _, filenames in os.walk(pyside_staging):
            for fn in filenames:
                if fn.endswith(".py") and fn not in ["app.py", "__init__.py"]:
                    p_file = os.path.join(dirpath, fn)
                    try:
                        os.remove(p_file)
                        py_deleted_count += 1
                    except Exception:
                        pass
        print(f"  🔒 沙盒内已防护清理 {py_deleted_count} 个 .py 源码文件 (仅保留 app.py 与包标识 __init__.py)")

        # 4. 调用 PyInstaller 对沙盒进行打包
        print("\n【步骤 4/4】PyInstaller 读取沙盒二进制扩展，导出终极程序包...")
        dist_app = os.path.join(project_root, "dist", "pyside_app")
        build_app = os.path.join(project_root, "build", "pyside_app")
        os.makedirs(dist_app, exist_ok=True)

        app_main = os.path.join(pyside_staging, "app.py")

        # 自动获取沙盒内编译生成的所有 Cython 二进制模块，强行收集为 hidden-import
        hidden_imports = list(third_party_deps)
        for dirpath, _, filenames in os.walk(pyside_staging):
            for fn in filenames:
                if fn.endswith(".so") or fn.endswith(".pyd"):
                    rel_path = os.path.relpath(os.path.join(dirpath, fn), pyside_staging)
                    mod_part = rel_path.split(".")[0]
                    mod_name = mod_part.replace(os.sep, "/").replace("/", ".")
                    if mod_name and not mod_name.endswith("__init__"):
                        hidden_imports.append(mod_name)
                    parts = mod_name.split(".")
                    for i in range(1, len(parts)):
                        hidden_imports.append(".".join(parts[:i]))

        hidden_args = " ".join([f'--hidden-import="{m}"' for m in set(hidden_imports)])
        print(f"  🔍 汇总生成 {len(set(hidden_imports))} 个轻量隐式导入模块指示")

        staging_configs_dir = os.path.join(staging_dir, "configs")
        app_datas = [
            (staging_configs_dir if os.path.exists(staging_configs_dir) else os.path.join(project_root, "configs"), "configs"),
            (os.path.join(project_root, "sherpa"), "sherpa"),
            (os.path.join(project_root, "backend", "assets"), "backend/assets"),
        ]
        app_data_args = " ".join([f'--add-data "{src};{dst}"' if sys.platform == "win32" else f'--add-data "{src}:{dst}"' for src, dst in app_datas if os.path.exists(src)])

        # 智能检测 PyInstaller 命令或通过 uv 补全
        has_uv = shutil.which("uv") is not None
        pyinstaller_prefix = f'"{py_exec}" -m PyInstaller'
        
        try:
            res = subprocess.run([py_exec, "-m", "PyInstaller", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode != 0 and has_uv:
                pyinstaller_prefix = "uv run --with pyinstaller python -m PyInstaller"
        except Exception:
            if has_uv:
                pyinstaller_prefix = "uv run --with pyinstaller python -m PyInstaller"

        cmd = (
            f'{pyinstaller_prefix} '
            f'--name="xiaoan_voice_desktop" '
            f'--onedir --noconfirm --clean '
            f'--distpath="{dist_app}" '
            f'--workpath="{build_app}" '
            f'--paths="{pyside_staging}" '
            f'--paths="{staging_dir}" '
            f'{hidden_args} '
            f'{app_data_args} '
            f'"{app_main}"'
        )
        run_command(cmd, cwd=staging_dir)

        print("\n" + "=" * 66)
        print("🎉🎉 桌面前端打包 100% 成功！")
        print(f" 📦 产物输出路径: {os.path.join(dist_app, 'xiaoan_voice_desktop')}")
        print("=" * 66)

    except Exception as e:
        print(f"\n❌ 桌面前端打包构建失败: {e}")
        sys.exit(1)
    finally:
        # 5. 无论成功还是失败，无条件彻底销毁沙盒
        clean_staging()


if __name__ == "__main__":
    main()
