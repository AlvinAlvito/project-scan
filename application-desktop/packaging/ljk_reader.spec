# -*- mode: python ; coding: utf-8 -*-
# Paket aplikasi LJK Reader (folder siap pakai, tanpa perlu Python).
# Jalankan dari folder proyek:  .venv\Scripts\pyinstaller packaging\ljk_reader.spec --noconfirm
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "ljk" / "ref"), "ljk/ref")],   # sidik jari blok
    hiddenimports=["app.window", "app.kunci_tab", "app.scan_tab", "app.review_tab", "app.imageview"],
    excludes=["tkinter", "matplotlib", "IPython", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LJK Reader",
    console=False,          # aplikasi jendela, tanpa layar hitam
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LJK Reader", upx=False)
