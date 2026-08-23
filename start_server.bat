@echo off
cd /d "%~dp0"
echo Starting local web server...
start "" http://localhost:8000
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m http.server 8000
) else (
    python -m http.server 8000
)
pause
