@echo off
chcp 65001 >nul
title Maotong 后台管理
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

"%PYTHON_EXE%" -c "import flask, dotenv, waitress" >nul 2>&1
if errorlevel 1 (
    echo [启动失败] 缺少 Python 或项目依赖。
    echo 请先运行：.venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PYTHON_EXE%" admin_tool.py
if errorlevel 1 echo [服务已停止] 请查看上方错误信息。
pause
