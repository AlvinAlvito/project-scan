"""Tema aplikasi: "terang" dan "gelap", gaya "framed sheet".

Bingkai (bilah atas + sidebar) satu warna redup; isi halaman ada di lembar putih bertepi 1 px tanpa bayangan.
Warna merek hanya di status terpilih, garis tab, dan tombol utama; selebihnya abu-abu, warna dipakai untuk data.
Semua warna diambil dari palet di sini, jadi mengganti tema cukup memanggil apply().
- Tombol diberi gaya lewat properti "variant": primary | ghost | danger | icon (bawaan: biasa).
- Label diberi gaya lewat properti "role": title | h2 | subtitle | muted | section | badge (+ "tone").
- Warna sel tabel memakai "tone" (ok, warn, error, info, chosen) lewat app.colors.paint().
"""
import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QPushButton, QTableWidget

from app import icons

FONTS = Path(__file__).resolve().parent / "fonts"     # IBM Plex (lisensi OFL, lihat fonts/OFL.txt)
SANS, MONO = "IBM Plex Sans", "IBM Plex Mono"

PALETTES = {
    "terang": dict(
        frame="#f6f8fa", bg="#ffffff", surface="#ffffff", surface2="#f3f5f7", input="#ffffff", canvas="#f3f5f7",
        border="#e6e9ec", border_strong="#cdd1d6", rule="#eff1f3",
        text="#131416", muted="#5a5e63", faint="#6b7076", icon="#4a4e54",
        accent="#1e3a8a", accent_hover="#2a4aa6", accent_press="#162d6e", on_accent="#ffffff",
        accent_soft="#eef2fa", accent_text="#1e3a8a",
        hover="#f3f5f7", selection="#e9ecef",
        side_bg="#f6f8fa", side_text="#131416", side_muted="#5a5e63", side_hover="#eceff2",
        side_sel="#e3e7eb", side_border="#e6e9ec",
        danger="#c4242a", danger_soft="#ffedea",
    ),
    # gelap: abu-abu netral (bukan navy), tingkat terang membedakan permukaan
    "gelap": dict(
        frame="#0c0c0d", bg="#161618", surface="#161618", surface2="#1f1f22", input="#111113", canvas="#0f0f10",
        border="#2a2a2e", border_strong="#3f3f44", rule="#222225",
        text="#f1f1f2", muted="#b4b4b8", faint="#8e8e93", icon="#c4c4c8",
        accent="#5b8cff", accent_hover="#77a0ff", accent_press="#4677ee", on_accent="#0b1020",
        accent_soft="#1a2238", accent_text="#9dbbff",
        hover="#1f1f22", selection="#2a2a2e",
        side_bg="#0c0c0d", side_text="#f1f1f2", side_muted="#a0a0a5", side_hover="#18181a",
        side_sel="#232326", side_border="#2a2a2e",
        danger="#f0717a", danger_soft="#2c1a1d",
    ),
}

# Warna penanda (latar pucat, teks gelap dari rona yang sama) untuk status, sel tabel, dan lencana.
TONES = {
    "terang": {
        "ok": ("#dcfae5", "#14532d"), "warn": ("#fffbeb", "#92400e"), "error": ("#ffedea", "#831c1e"),
        "info": ("#eef2fa", "#1e3a8a"), "chosen": ("#1e3a8a", "#ffffff"), "neutral": ("#ebedee", "#353736"),
    },
    "gelap": {
        "ok": ("#16291d", "#5fd08f"), "warn": ("#2b2414", "#e5a93b"), "error": ("#2c1a20", "#f0717a"),
        "info": ("#1a2238", "#9dbbff"), "chosen": ("#5b8cff", "#0b1020"), "neutral": ("#232326", "#d4d4d8"),
    },
}

QSS = Template("""
* { outline: 0; }
QWidget { color: $text; font-size: 10pt; }
QMainWindow, #frame, #topbar { background: $frame; }
#sheet { background: $bg; border: 1px solid $border; border-radius: 16px; }
QDialog, QTabWidget > QWidget, QScrollArea > QWidget > QWidget { background: $bg; }
QToolTip { background: $surface; color: $text; border: 1px solid $border_strong; border-radius: 6px; padding: 6px 8px; }

/* ---------- bingkai: bilah atas + sidebar, satu warna tanpa garis di antaranya */
#sidebar { background: $side_bg; }
#sidebar[floating="true"] { border-right: 1px solid $side_border; }
#sidebar QLabel { color: $side_text; background: transparent; }
#sidebar QLabel[role="muted"], #sidebar QLabel[role="section"] { color: $side_muted; }
#sidebar QListWidget { background: transparent; border: none; padding: 0; }
#sidebar QPushButton { background: transparent; color: $side_muted; border: 1px solid transparent;
    border-radius: 8px; padding: 6px 8px; text-align: left; font-weight: 400; }
#sidebar QPushButton:hover { background: $side_hover; color: $side_text; }
#sidebar QPushButton:pressed { background: $side_sel; }
#sidebar QPushButton:disabled { color: $faint; }
#sidebar QPushButton[variant="icon"] { padding: 5px; text-align: center; }
#topbar QPushButton[variant="ghost"] { color: $muted; font-weight: 400; }
#topbar QPushButton[variant="ghost"]:hover { color: $text; background: $side_hover; }
QLineEdit#search { background: $surface; border: 1px solid $border; padding: 5px 10px; }
QLineEdit#search:focus { border-color: $accent; }

/* ---------- teks */
QLabel { background: transparent; }
QLabel[role="title"] { font-size: 16pt; font-weight: 600; }
QLabel[role="h2"] { font-size: 12pt; font-weight: 600; }
QLabel[role="h3"] { font-weight: 600; }
QLabel[role="brand"] { font-size: 10.5pt; font-weight: 600; }
QLabel[role="subtitle"], QLabel[role="muted"] { color: $muted; }
QLabel[role="section"] { color: $muted; font-size: 9pt; }
QLabel[role="empty-title"] { font-size: 13pt; font-weight: 600; }
QLabel[role="badge"] { border-radius: 10px; padding: 2px 8px; font-weight: 500; font-size: 9pt; }
QLabel[role="badge"][tone="warn"] { background: $warn_bg; color: $warn_fg; }
QLabel[role="badge"][tone="ok"] { background: $ok_bg; color: $ok_fg; }
QLabel[role="badge"][tone="error"] { background: $error_bg; color: $error_fg; }
QLabel[role="badge"][tone="info"] { background: $info_bg; color: $info_fg; }
QLabel[role="badge"][tone="neutral"] { background: $neutral_bg; color: $neutral_fg; }
QLabel[role="stat-value"] { font-size: 12pt; font-weight: 600; }
QLabel[role="stat-caption"] { color: $muted; font-size: 9.5pt; }

QFrame[role="card"], QFrame[role="stat"] { background: $surface; border: 1px solid $border; border-radius: 8px; }
QFrame[role="toolbar"] { background: transparent; }
QFrame[role="divider"] { background: $border; max-width: 1px; min-width: 1px; }
QFrame[role="well"] { background: $canvas; border: none; border-radius: 8px; }

/* kartu hitung: angka per status, sekaligus penyaring daftar lembar */
QPushButton[role="count"] { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 0; text-align: left;
    min-height: 54px; max-height: 54px; }
QPushButton[role="count"]:hover { border-color: $border_strong; background: $surface; }
QPushButton[role="count"]:checked { background: $accent_soft; border: 1px solid $accent; }

/* ---------- tombol: putih bertepi, sudut 6 px; tombol utama warna merek */
QPushButton { background: $surface; color: $text; border: 1px solid $border_strong; border-radius: 6px;
    padding: 6px 12px; min-height: 18px; font-weight: 500; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $selection; }
QPushButton:disabled { color: $faint; background: $surface2; border-color: $border; }
QPushButton:checked { background: $accent_soft; border-color: $accent; color: $accent_text; }
QPushButton::menu-indicator { image: url("$arrow_down"); subcontrol-position: right center; subcontrol-origin: padding;
    width: 12px; height: 12px; right: 8px; }
QPushButton[menu="true"] { padding-right: 28px; }
QPushButton[variant="primary"] { background: $accent; color: $on_accent; border: 1px solid $accent; font-weight: 600; }
QPushButton[variant="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[variant="primary"]:pressed { background: $accent_press; }
QPushButton[variant="primary"]:disabled { background: $accent_soft; border-color: $accent_soft; color: $faint; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; }
QPushButton[variant="ghost"]:hover { background: $hover; }
QPushButton[variant="danger"] { color: $danger; }
QPushButton[variant="danger"]:hover { background: $danger_soft; border-color: $danger; }
QPushButton[variant="icon"] { padding: 6px; min-width: 18px; }
QPushButton[role="choice"] { min-width: 18px; padding: 7px 0; font-weight: 600; }
QPushButton[role="choice"]:checked { background: $accent_soft; border-color: $accent; color: $accent_text; }

QMenu { background: $surface; border: 1px solid $border_strong; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 6px; }
QMenu::item:selected { background: $hover; color: $text; }
QMenu::item:disabled { color: $faint; }
QMenu::icon { padding-left: 10px; }
QMenu::separator { height: 1px; background: $border; margin: 4px 6px; }

/* ---------- tab: garis bawah 2 px warna merek di atas garis 1 px selebar lembar */
QTabWidget::pane { border: none; border-top: 1px solid $border; top: -1px; }
QTabBar { qproperty-drawBase: 0; background: transparent; }
QTabBar::tab { background: transparent; color: $muted; padding: 9px 0; margin-right: 24px;
    border: none; border-bottom: 2px solid transparent; font-weight: 500; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabBar::tab:disabled { color: $faint; }

/* ---------- input */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background: $input; color: $text; border: 1px solid $border_strong;
    border-radius: 6px; padding: 6px 10px; selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: $faint; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $faint; background: $surface2; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url("$arrow_down"); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border_strong; border-radius: 8px;
    padding: 4px; selection-background-color: $selection; selection-color: $text; }
QSpinBox::up-button, QSpinBox::down-button { border: none; width: 22px; background: transparent; }
QSpinBox::up-arrow { image: url("$arrow_up"); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url("$arrow_down"); width: 12px; height: 12px; }
QPlainTextEdit { font-family: "IBM Plex Mono", "Cascadia Mono", "Consolas"; font-size: 9pt; }

QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid $border_strong; background: $input; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }

QSlider { background: transparent; min-height: 22px; }
QSlider::groove:horizontal { height: 4px; background: $border_strong; border-radius: 2px; }
QSlider::sub-page:horizontal { height: 4px; background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: $accent; }
QSlider::handle:horizontal:hover { background: $accent_hover; }

/* ---------- tabel & daftar: tanpa zebra, kepala tanpa pita, garis baris tipis */
QTableView { background: $surface; alternate-background-color: $surface; border: 1px solid $border;
    border-radius: 8px; gridline-color: $rule; selection-background-color: $selection; selection-color: $text; }
QTableView::item { padding: 0 10px; border-bottom: 1px solid $rule; }
QTableView::item:selected { background: $selection; color: $text; }
QTableView QTableCornerButton::section { background: $surface; border: none; }
QHeaderView { background: transparent; }
QHeaderView::section { background: $surface; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 8px 10px; font-weight: 400; font-size: 9pt; }
QHeaderView::section:first { border-top-left-radius: 8px; }
QHeaderView::section:last { border-top-right-radius: 8px; }

QListWidget { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 4px; }
QListWidget::item { padding: 7px 10px; border-radius: 6px; }
QGroupBox QListWidget { border: none; background: transparent; padding: 0; }
QListWidget::item:hover { background: $hover; }
QListWidget::item:selected { background: $selection; color: $text; }
QListWidget#queue { background: transparent; border: none; border-top: 1px solid $border; border-radius: 0; padding: 0; }

/* bagian di panel cek: judul di bawah garis tipis, tanpa kotak */
QGroupBox { background: transparent; border: none; border-top: 1px solid $rule; margin-top: 4px;
    padding: 34px 0 6px 0; font-weight: 600; }
QGroupBox::title { subcontrol-origin: padding; subcontrol-position: top left; left: 0; top: 12px; padding: 0; color: $text; }

QProgressBar { background: $surface2; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }

QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 16px; }
QSplitter::handle:vertical { height: 16px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: $border_strong; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: $faint; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QGraphicsView { border: none; border-radius: 8px; }
QMessageBox QLabel { min-width: 280px; }
""")


class _Bus(QObject):
    changed = Signal()


bus = _Bus()
_name = "gelap"
_dir = Path(tempfile.gettempdir()) / "ljk-reader-theme"
_fonts_loaded = False


def name():
    return _name


def c(key):
    """Warna palet aktif, mis. c('accent')."""
    return PALETTES[_name][key]


def tone(key):
    """(QColor latar, QColor teks) untuk penanda key."""
    bg, fg = TONES[_name][key]
    return QColor(bg), QColor(fg)


def tone_hex(key):
    return TONES[_name][key]


def _asset(name_, color):
    _dir.mkdir(parents=True, exist_ok=True)
    f = _dir / f"{name_}-{color.lstrip('#')}.svg"
    if not f.exists():
        f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
                     f'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">{icons.PATHS[name_]}</svg>',
                     encoding="utf-8")
    return f.as_posix()


def _load_fonts():
    """Daftarkan IBM Plex yang ikut dalam paket aplikasi (sekali saja)."""
    global _fonts_loaded
    if not _fonts_loaded:
        _fonts_loaded = True
        for f in sorted(FONTS.glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(f))


def _font():
    _load_fonts()
    fams = set(QFontDatabase.families())
    for fam in (SANS, "Segoe UI Variable Text", "Segoe UI", "Inter"):
        if fam in fams:
            return QFont(fam, 10)
    return QFont()


def mono(size=10):
    _load_fonts()
    f = QFont()
    f.setFamilies([MONO, "Cascadia Mono", "Consolas", "Courier New"])
    f.setPointSize(size)
    return f


def saved():
    v = QSettings("POSI", "LJK Reader").value("tema", "gelap")
    return v if v in PALETTES else "gelap"


def apply(theme=None, save=True):
    global _name
    _name = theme or saved()
    if save:
        QSettings("POSI", "LJK Reader").setValue("tema", _name)
    p = PALETTES[_name]
    app = QApplication.instance()
    app.setFont(_font())

    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "surface"),
                      (QPalette.AlternateBase, "surface"), (QPalette.Text, "text"), (QPalette.Button, "surface"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "on_accent"), (QPalette.ToolTipBase, "surface"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "faint"), (QPalette.Link, "accent")):
        pal.setColor(role, QColor(p[key]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(p["faint"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["faint"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["faint"]))
    app.setPalette(pal)

    vals = dict(p)
    for k, (bg, fg) in TONES[_name].items():
        vals[f"{k}_bg"], vals[f"{k}_fg"] = bg, fg
    vals.update(arrow_down=_asset("chevron-down", p["muted"]), arrow_up=_asset("chevron-up", p["muted"]),
                check=_asset("check", p["on_accent"]))
    app.setStyleSheet(QSS.substitute(vals))
    refresh_all()
    bus.changed.emit()


def toggle():
    apply("terang" if _name == "gelap" else "gelap")


# ---------------------------------------------------------------- ikon & tone

def _in_sidebar(w):
    while w is not None:
        if w.objectName() == "sidebar":
            return True
        w = w.parentWidget()
    return False


def _icon_color(w):
    t = w.property("icon_tone")
    if t:
        return c(t)
    v = w.property("variant")
    if v == "primary":
        return c("on_accent")
    if v == "danger":
        return c("danger")
    if _in_sidebar(w):
        return c("side_muted")
    return c("icon")


def set_icon(w, name_, tone_=None):
    """Pasang ikon pada tombol; warnanya mengikuti tema (dan berganti saat tema berganti)."""
    w.setProperty("icon_name", name_)
    if tone_:
        w.setProperty("icon_tone", tone_)
    w.setIcon(icons.icon(name_, _icon_color(w), c("faint")))


class Button(QPushButton):
    """QPushButton dengan jarak ikon-teks yang lebih lega. Bisa diringkas jadi ikon saja (set_compact)
    saat toolbar sempit; teksnya lalu tampil di tooltip."""

    _label = ""
    _compact = False
    _tip = None

    def setText(self, text):
        self._label = text
        if self._compact:
            text = ""
        super().setText(f"  {text}" if text and self.property("icon_name") else text)

    def set_compact(self, on):
        on = bool(on and self.property("icon_name") and self._label)
        if on == self._compact:
            return
        if on:
            self._tip = self.toolTip()
            label = self._label.replace("&&", "&")
            self.setToolTip(f"{label}\n{self._tip}" if self._tip and self._tip != label else label)
        else:
            self.setToolTip(self._tip or "")
        self._compact = on
        self.setText(self._label)

    def setMenu(self, menu):
        super().setMenu(menu)
        self.setProperty("menu", menu is not None)


def button(text, icon_name=None, variant=None, tip=None, slot=None):
    b = Button()
    if icon_name:
        b.setProperty("icon_name", icon_name)
    b.setText(text)
    if variant:
        b.setProperty("variant", variant)
    if icon_name:
        set_icon(b, icon_name)
    if tip:
        b.setToolTip(tip)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.PointingHandCursor)
    return b


def repolish(w):
    """Terapkan ulang gaya setelah properti (role/tone/variant) diubah."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


TONE_ROLE = 0x0100 + 77     # Qt.UserRole + 77: nama tone yang tersimpan di sel tabel


def refresh_all():
    app = QApplication.instance()
    for w in app.allWidgets():
        if isinstance(w, QAbstractButton) and w.property("icon_name"):
            w.setIcon(icons.icon(w.property("icon_name"), _icon_color(w), c("faint")))
        elif isinstance(w, QTableWidget):
            from app.colors import repaint
            for r in range(w.rowCount()):
                for col in range(w.columnCount()):
                    it = w.item(r, col)
                    if it is not None and it.data(TONE_ROLE):
                        repaint(it)
