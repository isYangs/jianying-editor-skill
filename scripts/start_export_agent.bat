@echo off
chcp 65001 >nul
title JianYing Export Agent

echo ╔════════════════════════════════════════════════════════════╗
echo ║       JianYing Windows Export Agent                       ║
echo ╠════════════════════════════════════════════════════════════╣

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ║  ❌ Python 未安装                                         ║
    echo ╚════════════════════════════════════════════════════════════╝
    echo.
    echo 请先安装 Python: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查依赖
echo ║  检查依赖...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo ║  📦 正在安装依赖...
    pip install fastapi uvicorn pyJianYingDraft requests
)

REM 启动服务
echo ║  ✅ 启动 Export Agent 服务...
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo 监听地址: http://0.0.0.0:8765
echo 停止服务: 按 Ctrl+C
echo.
echo API 端点:
echo   GET  /          - 服务信息
echo   GET  /health    - 健康检查
echo   GET  /drafts    - 列出草稿
echo   POST /export    - 启动导出任务
echo.
echo ================================================================
echo.

REM 切换到脚本目录
cd /d "%~dp0"

REM 启动 Python 服务
python -m uvicorn scripts.core.windows_export_agent:app --host 0.0.0.0 --port 8765 --reload

pause
