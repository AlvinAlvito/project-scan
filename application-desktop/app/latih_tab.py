"""Tab 4: mengajari model membaca bulatan. Panitia memberi label pada contoh yang paling
membingungkan (1 = terisi, 2 = kosong, 3 = hapusan), lalu melatih ulang model.

Model hasil latih hanya menjadi "juri kedua" dan baru aktif bila lulus ujian pada label
panitia yang disisihkan (lihat ljk/belajar.py dan tools/latih_bulatan.py)."""
import json
from pathlib import Path

import cv2
from PySide6.QtCore import QProcess, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from app import theme
from app.widgets import EmptyState, ToolbarFit, divider, toolbar
from ljk import belajar as BL

ROOT = Path(__file__).resolve().parents[1]
KOLOM, BARIS = 5, 3
TOMBOL = {Qt.Key_1: "terisi", Qt.Key_2: "kosong", Qt.Key_3: "hapusan"}


def warna(label):
    """Warna teks label menurut tema aktif."""
    return {"terisi": theme.tone_hex("ok")[1], "kosong": theme.c("muted"),
            "hapusan": theme.tone_hex("warn")[1]}.get(label, theme.c("faint"))


def _pixmap(img_bgr, dpr):
    h, w = img_bgr.shape[:2]
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    pm = QPixmap.fromImage(qimg)
    pm.setDevicePixelRatio(dpr)
    return pm


class Loader(QThread):
    done = Signal(list)

    def __init__(self, rows, labels, jumlah_of):
        super().__init__()
        self.rows, self.labels, self.jumlah_of = rows, labels, jumlah_of

    def run(self):
        self.done.emit(BL.candidates(self.rows, self.labels, self.jumlah_of, BL.active_model(), limit=600))


class Tile(QFrame):
    clicked = Signal()
    labelled = Signal(str)          # label dipilih lewat tombol di kotak

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.cap = QLabel()
        self.cap.setWordWrap(True)
        self.lab = QLabel()
        self.lab.setAlignment(Qt.AlignCenter)
        for w in (self.img, self.cap, self.lab):
            v.addWidget(w)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.buttons = {}
        for key, label in (("1", "terisi"), ("2", "kosong"), ("3", "hapusan")):
            b = QPushButton(f"{key} {label.capitalize()}")
            b.setFocusPolicy(Qt.NoFocus)          # fokus tetap di tab supaya tombol keyboard jalan
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, label=label: self.labelled.emit(label))
            self.buttons[label] = b
            row.addWidget(b)
        v.addLayout(row)

    def mousePressEvent(self, e):
        self.clicked.emit()

    def show_item(self, c, label, selected, dpr):
        self.setVisible(c is not None)
        if c is None:
            return
        # ~200 px layar (logis) apa pun DPI-nya: diperbesar dari gambar baca, tajam di layar DPI tinggi
        self.img.setPixmap(_pixmap(BL.context_image(c["dir"], c["xy"], scale=2.5 * dpr), dpr))
        model = "" if c["model"] is None else f" · model {c['model']:.2f}"
        self.cap.setText(f"<b>{BL.describe(c)}</b><br>{Path(c['file']).stem[-6:]} · aturan: {c['aturan']}"
                         f" (skor {c['skor']:.2f}){model}")
        self.lab.setText(f"<b>{label.upper()}</b>" if label else "belum dilabeli")
        self.lab.setStyleSheet(f"color: {warna(label)}; font-size: 11pt")
        for name, b in self.buttons.items():
            b.setStyleSheet(f"QPushButton {{ color: {warna(name)}; font-weight: 600; padding: 6px 8px; }}")
        border = f"2px solid {theme.c('accent')}" if selected else f"1px solid {theme.c('border')}"
        self.setStyleSheet(f"Tile {{ background: {theme.c('surface')}; border: {border}; border-radius: 12px; }}")


class LatihTab(QWidget):
    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, Path(data_dir)
        self.event_id = None
        self.items, self.page, self.sel = [], 0, 0
        self.loader = None
        self.proc = None
        self.setFocusPolicy(Qt.StrongFocus)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 18, 0, 0)
        v.setSpacing(12)
        top = toolbar()
        self.scope = QComboBox()
        self.scope.addItems(["Event ini", "Semua event"])
        self.scope.setToolTip("Sumber contoh")
        self.btn_load = theme.button("Ambil contoh sulit", "target", "primary",
                                     "Tampilkan bulatan yang paling membingungkan untuk dilabeli", self.load_items)
        self.btn_train = theme.button("Latih ulang", "play", tip="Latih model dari label Anda (~1 menit)",
                                      slot=self.train)
        self.btn_report = theme.button("Laporan", "chart", tip="Hasil ujian model aktif", slot=self.report)
        for w in (self.scope, self.btn_load, divider(), self.btn_train, self.btn_report):
            top.addWidget(w)
        top.addStretch()
        v.addLayout(top)
        ToolbarFit(self, top, (self.btn_report, self.btn_train, self.btn_load))
        self.stats = QLabel("")
        self.stats.setWordWrap(True)
        self.stats.setProperty("role", "muted")
        v.addWidget(self.stats)
        help_ = QLabel("Pilih kotak (klik / panah), lalu tekan  <b>1</b> Terisi  ·  <b>2</b> Kosong  ·  "
                       "<b>3</b> Hapusan  ·  <b>0</b> Lewati  ·  <b>Backspace</b> Hapus label")
        help_.setToolTip("Terisi dihitung sebagai jawaban; hapusan/bekas tidak dihitung.\n"
                         "Lingkaran biru = bulatan yang ditanyakan.")
        help_.setWordWrap(True)
        v.addWidget(help_)

        grid_w = QWidget()
        self.grid = QGridLayout(grid_w)
        self.grid.setSpacing(12)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.tiles = []
        for k in range(KOLOM * BARIS):
            t = Tile()
            t.clicked.connect(lambda k=k: self._select(k))
            t.labelled.connect(lambda label, k=k: self._label_tile(k, label))
            self.grid.addWidget(t, k // KOLOM, k % KOLOM)
            self.tiles.append(t)
        sc = self.scroll = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(grid_w)
        self.empty = EmptyState("target", "Belum ada contoh",
                                "Klik \"Ambil contoh sulit\" untuk menampilkan bulatan yang perlu dilabeli.")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(sc)
        v.addWidget(self.stack, 1)

        nav = toolbar()
        nav.addStretch()
        self.btn_prev = theme.button("", "chevron-left", "icon", "Halaman sebelumnya", lambda: self._goto(self.page - 1))
        self.btn_next = theme.button("", "chevron-right", "icon", "Halaman berikutnya", lambda: self._goto(self.page + 1))
        self.page_lbl = QLabel("")
        self.page_lbl.setProperty("role", "muted")
        for w in (self.btn_prev, self.page_lbl, self.btn_next):
            nav.addWidget(w)
        nav.addStretch()
        v.addLayout(nav)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(170)
        self.log.setVisible(False)
        v.addWidget(self.log)
        theme.bus.changed.connect(self._show_page)
        self._show_page()

    # ---- data
    def load(self, event_id):
        self.event_id = event_id
        self.update_stats()

    def update_stats(self):
        labels = self.db.labels()
        cnt = {k: sum(1 for v in labels.values() if v == k) for k in BL.KELAS}
        uji = sum(1 for (f, _) in labels if BL.is_test_sheet(f))
        m = BL.active_model()
        model = (f"model aktif <b>{m.versi}</b>" + (" (boleh memutus kasus ragu)" if m.putus_ragu else "")
                 if m else "<b>belum ada model aktif</b> (pembacaan memakai aturan saja)")
        self.stats.setText(f"Label Anda: <b>{len(labels)}</b> (terisi {cnt['terisi']}, kosong {cnt['kosong']}, "
                           f"hapusan {cnt['hapusan']}) — {len(labels) - uji} untuk latihan, {uji} untuk ujian "
                           f"(minimal 30 latihan & 60 ujian) · {model}")

    def _rows(self):
        if self.scope.currentIndex() == 0 and self.event_id is not None:
            return list(self.db.lembar(self.event_id))
        return list(self.db.all_lembar())

    def _jumlah_of(self):
        naskah = {ev["id"]: {s.kode: s.jumlah for s in self.db.naskah(ev["id"])} for ev in self.db.events()}
        return lambda row: naskah.get(row["event_id"], {}).get(row["kode"], 180)

    def load_items(self):
        if self.loader is not None and self.loader.isRunning():
            return
        self.btn_load.setEnabled(False)
        self.btn_load.setText("Mencari contoh…")
        self.loader = Loader(self._rows(), self.db.labels(), self._jumlah_of())
        self.loader.done.connect(self._loaded)
        self.loader.start()

    def _loaded(self, items):
        self.btn_load.setEnabled(True)
        self.btn_load.setText("Ambil contoh sulit")
        self.items, self.page, self.sel = items, 0, 0
        if not items:
            QMessageBox.information(self, "Latih Model", "Tidak ada contoh. Pastikan foto sudah diproses "
                                    "(atau Proses ulang lembar lama agar gambar bacanya tersimpan).")
        self._show_page()
        self.setFocus()

    # ---- tampilan halaman
    def _page_items(self):
        n = KOLOM * BARIS
        return self.items[self.page * n:(self.page + 1) * n]

    def _show_page(self):
        labels = self.db.labels()
        dpr = self.devicePixelRatioF()
        its = self._page_items()
        for k, t in enumerate(self.tiles):
            c = its[k] if k < len(its) else None
            t.show_item(c, labels.get((c["file"], c["idx"])) if c else None, k == self.sel, dpr)
        pages = max(1, -(-len(self.items) // (KOLOM * BARIS)))
        self.page_lbl.setText(f"Halaman {self.page + 1} / {pages} · {len(self.items)} contoh")
        self.stack.setCurrentWidget(self.scroll if self.items else self.empty)
        for w in (self.btn_prev, self.page_lbl, self.btn_next):
            w.setVisible(bool(self.items))
        self.btn_prev.setEnabled(self.page > 0)
        self.btn_next.setEnabled(self.page + 1 < pages)
        if its:
            self.scroll.ensureWidgetVisible(self.tiles[self.sel])     # kotak terpilih selalu terlihat
        self.update_stats()

    def _goto(self, page):
        pages = max(1, -(-len(self.items) // (KOLOM * BARIS)))
        self.page, self.sel = max(0, min(page, pages - 1)), 0
        self._show_page()
        self.setFocus()

    def _select(self, k):
        if k < len(self._page_items()):
            self.sel = k
            self._show_page()
        self.setFocus()

    def _label_tile(self, k, label):
        """Tombol di kotak: pilih kotak itu, simpan labelnya, lanjut ke kotak berikutnya."""
        its = self._page_items()
        if k < len(its):
            self.sel = k
            self.db.set_label(its[k]["file"], its[k]["idx"], label)
            self._advance(True)
        self.setFocus()

    def keyPressEvent(self, e):
        its = self._page_items()
        if not its:
            return super().keyPressEvent(e)
        key = e.key()
        if key in TOMBOL or key == Qt.Key_Backspace:
            c = its[self.sel]
            self.db.set_label(c["file"], c["idx"], TOMBOL.get(key))
            self._advance(key != Qt.Key_Backspace)
        elif key in (Qt.Key_0, Qt.Key_Space):
            self._advance(True)
        elif key == Qt.Key_Right:
            self._select(min(self.sel + 1, len(its) - 1))
        elif key == Qt.Key_Left:
            self._select(max(self.sel - 1, 0))
        elif key == Qt.Key_Down:
            self._select(min(self.sel + KOLOM, len(its) - 1))
        elif key == Qt.Key_Up:
            self._select(max(self.sel - KOLOM, 0))
        else:
            super().keyPressEvent(e)

    def _advance(self, move):
        if move and self.sel + 1 < len(self._page_items()):
            self.sel += 1
        elif move:
            self._goto(self.page + 1)
            return
        self._show_page()

    # ---- latih
    def _tool(self):
        cfg = self.data_dir / "latih.json"
        if cfg.exists():
            c = json.loads(cfg.read_text(encoding="utf-8"))
            return Path(c["python"]), Path(c["script"])
        for root in (ROOT, Path(r"D:/SCAN/LJK-Reader")):
            py, sc = root / ".venv-latih" / "Scripts" / "python.exe", root / "tools" / "latih_bulatan.py"
            if py.exists() and sc.exists():
                return py, sc
        return None, None

    def train(self):
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            return
        py, sc = self._tool()
        if py is None:
            QMessageBox.warning(self, "Latih Model", "Alat pelatihan (lingkungan PyTorch .venv-latih) tidak ditemukan.\n"
                                f"Atur lokasinya di {self.data_dir / 'latih.json'}.")
            return
        self.log.clear()
        self.log.setVisible(True)
        self.btn_train.setEnabled(False)
        self.btn_train.setText("Melatih…")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(
            lambda: self.log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace").rstrip()))
        self.proc.finished.connect(self._trained)
        self.proc.start(str(py), ["-I", str(sc), "--data", str(self.data_dir)])

    def _trained(self, *_):
        self.btn_train.setEnabled(True)
        self.btn_train.setText("Latih ulang")
        BL.active_model()
        self.update_stats()
        self.log.appendPlainText("\nModel baru dipakai untuk foto yang diproses sesudah ini. "
                                 "Lembar lama perlu 'Proses ulang' agar ikut dinilai model.")

    def report(self):
        f = self.data_dir / "model" / "aktif.json"
        if not f.exists():
            QMessageBox.information(self, "Laporan model", "Belum ada model aktif. Pembacaan memakai aturan saja.")
            return
        info = json.loads(f.read_text(encoding="utf-8"))
        r = info.get("laporan", {})
        u = r.get("ujian", {})
        QMessageBox.information(
            self, "Laporan model",
            f"Model aktif: {info.get('versi')}\n"
            f"Ujian pada {u.get('n')} label Anda (tidak dipakai melatih):\n"
            f"  benar model {u.get('akurasi_model', 0):.1%} | aturan {u.get('akurasi_aturan', 0):.1%}\n"
            f"Boleh memutus kasus ragu: {'ya' if info.get('gerbang_b') else 'tidak'}\n"
            f"Contoh latih: {r.get('contoh')}")
