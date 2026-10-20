@echo off
rem Menjalankan server LJK Reader Online di laptop (uji coba lokal).
rem   http://localhost:8000        -> dari laptop ini
rem   https://<IP-laptop>:8443     -> dari HP (kamera butuh HTTPS); jalankan make_cert.py sekali dulu
cd /d "%~dp0"
if exist "data\cert.pem" (
  start "LJK Server HTTPS" ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile data\key.pem --ssl-certfile data\cert.pem
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
