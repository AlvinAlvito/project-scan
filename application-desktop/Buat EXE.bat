@echo off
rem Membuat ulang paket aplikasi di dist\LJK Reader (jalankan setelah kode diperbarui; tutup aplikasinya dulu)
rem --clean: tanpa ini PyInstaller memakai ulang .exe lama bila hanya isi file ikon yang diganti
cd /d "%~dp0"
".venv\Scripts\pyinstaller.exe" packaging\ljk_reader.spec --noconfirm --clean --distpath dist --workpath build
echo.
echo Selesai. Aplikasi ada di: %~dp0dist\LJK Reader\LJK Reader.exe
pause
