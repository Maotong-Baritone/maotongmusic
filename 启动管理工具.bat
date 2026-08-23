@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" admin_tool.py
) else (
    python admin_tool.py
)
pause
