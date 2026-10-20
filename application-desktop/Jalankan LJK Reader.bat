@echo off
rem Menjalankan LJK Reader (versi pengembangan, sebelum dibuat .exe)
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "app\main.py"
