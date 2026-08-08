@echo off
chcp 65001 >nul
echo ================================================================
echo    【后端专属打包】FastAPI 服务 (.py -^> .pyd/.so -^> EXE)
echo ================================================================
echo.

cd /d "%~dp0\.."

if exist uv.exe (
    uv run python deploy/build_backend.py
) else (
    python deploy/build_backend.py
)

if %ERRORLEVEL% equ 0 (
    echo.
    echo ================================================================
    echo  ✅ 后端构建成功！产物位于 dist/backend/xiaoan_backend
    echo ================================================================
) else (
    echo.
    echo  ❌ 后端构建失败，请检查上面输出日志。
)

pause
