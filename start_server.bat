@echo off
cd /d "%~dp0"
echo Starting local web server...
start "" http://localhost:8000
python -m http.server 8000
pause
