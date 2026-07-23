@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" http://127.0.0.1:8077/
python -m uvicorn app.main:app --host 127.0.0.1 --port 8077
