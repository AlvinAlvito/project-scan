@echo off
rem Membuat ulang paket aplikasi di dist\LJK Reader (jalankan setelah kode diperbarui)
cd /d "%~dp0"
".venv\Scripts\pyinstaller.exe" packaging\ljk_reader.spec --noconfirm --distpath dist --workpath build
echo.
echo Selesai. Aplikasi ada di: %~dp0dist\LJK Reader\LJK Reader.exe
pause
