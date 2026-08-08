@echo off
chcp 65001 >nul
echo ================================================================
echo    【前端桌面端专属打包】PySide6 客户端 (.py -^> .pyd/.so -^> EXE)
echo ================================================================
echo.

cd /d "%~dp0\.."

if exist uv.exe (
    uv run python deploy/build_pyside.py
) else (
    python deploy/build_pyside.py
)

if %ERRORLEVEL% equ 0 (
    echo.
    echo ================================================================
    echo  ✅ 桌面前端构建成功！产物位于 dist/pyside_app/xiaoan_voice_desktop
    echo ================================================================
) else (
    echo.
    echo  ❌ 桌面前端构建失败，请检查上面输出日志。
)

pause
