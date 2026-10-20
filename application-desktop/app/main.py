"""LJK Reader - aplikasi desktop pembaca & rekap nilai LJK POSI (offline)."""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QStandardPaths, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import theme  # noqa: E402
from app.window import MainWindow  # noqa: E402
from ljk import belajar as BL  # noqa: E402
from ljk.db import DB  # noqa: E402


def data_dir():
    """Folder data di %LOCALAPPDATA%\\LJK Reader: di luar folder program (aman saat aplikasi
    diperbarui/dibuat ulang), dipakai bersama versi .exe maupun pengembangan, dan tidak
    diblokir "Controlled folder access" Windows (yang melindungi Documents)."""
    base = os.environ.get("LOCALAPPDATA") or QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    return Path(base) / "LJK Reader"


def old_data_dirs():
    """Lokasi data versi sebelumnya (di samping .exe atau di folder proyek)."""
    out = []
    if getattr(sys, "frozen", False):
        out.append(Path(sys.executable).resolve().parent / "data")
    out.append(ROOT / "data")
    return out


def migrate(new):
    """Bila lokasi baru belum punya database, salin data lama ke sana (folder lama tidak dihapus)."""
    if (new / "ljk.db").exists():
        return None
    for old in old_data_dirs():
        if (old / "ljk.db").exists():
            shutil.copytree(old, new, dirs_exist_ok=True)
            DB(new / "ljk.db").rebase_paths(str(old), str(new))
            return old
    return None


def selftest(foto, pdf, out):
    """Uji mesin tanpa membuka jendela: baca 1 foto LJK + 1 PDF kunci, tulis hasilnya ke file.
    Dipakai untuk memastikan hasil paket .exe lengkap (OpenCV, pdfium, sidik jari blok)."""
    import traceback

    lines = []
    try:
        from ljk import kunci as KU
        from ljk import pipeline as PL
        r = PL.process(foto)
        lines.append(f"foto: {r.status} | {r.error or ''}")
        if r.read:
            lines.append(f"nama={r.read.nama} nomor={r.read.nomor} kode={r.read.kode} tanggal={r.read.tanggal}")
            lines.append("jawaban 1-40: " + "".join(a or "-" for a in r.read.jawaban[:40]))
            # gambar cek & potongan tulisan tangan versi resolusi penuh (seperti saat scan)
            import tempfile
            from ljk import service as SV
            rec = SV.process_photo(foto, tempfile.mkdtemp())
            g = Path(rec["gambar"])
            lines.append(f"gambar cek: {g.stat().st_size // 1024} KB, potongan: {len(rec['potongan'])}")
        k = KU.parse(pdf)
        lines.append(f"pdf: {k.jumlah_soal} soal, kunci={k.kunci}, masalah={k.masalah}")
        lines.append("SELFTEST OK")
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("SELFTEST GAGAL")
    Path(out).write_text("\n".join(lines), encoding="utf-8")


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--selftest":
        selftest(*sys.argv[2:])
        return
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("LJK Reader")
    theme.apply(save=False)
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    moved_from = migrate(d)
    BL.set_model_dir(d / "model")      # model juri kedua (bila ada yang lulus ujian)
    w = MainWindow(DB(d / "ljk.db"), d)
    w.show()
    if moved_from is not None:
        QTimer.singleShot(300, lambda: QMessageBox.information(
            w, "LJK Reader", f"Data aplikasi sekarang disimpan di:\n{d}\n\n"
                             f"Data lama dari {moved_from} sudah disalin ke sana (folder lama tidak dihapus)."))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
