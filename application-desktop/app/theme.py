"""Tema aplikasi: "gelap" dan "terang" (biru tua + putih).

Semua warna diambil dari palet di sini, jadi mengganti tema cukup memanggil apply().
- Tombol diberi gaya lewat properti "variant": primary | ghost | danger | icon (bawaan: biasa).
- Label diberi gaya lewat properti "role": title | subtitle | muted | section | badge (+ "tone").
- Warna sel tabel memakai "tone" (ok, warn, error, info, chosen) lewat app.colors.paint().
"""
import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QPushButton, QTableWidget

from app import icons

PALETTES = {
    "gelap": dict(
        bg="#0e1116", surface="#151a21", surface2="#1b212a", input="#10141a", canvas="#0a0c10",
        border="#252c37", border_strong="#353e4d",
        text="#e8ebf1", muted="#8c95a7", faint="#566073", icon="#b8c0ce",
        accent="#5b8cff", accent_hover="#77a0ff", accent_press="#4677ee", on_accent="#ffffff",
        accent_soft="#1d2a45", accent_text="#9dbbff",
        hover="#1f2631", selection="#22314d",
        side_bg="#0a0d11", side_text="#e8ebf1", side_muted="#768096", side_hover="#151a22",
        side_sel="#1b2538", side_border="#1a1f28",
        danger="#f87171", danger_soft="#3a1a1d",
    ),
    "terang": dict(
        bg="#f2f5f9", surface="#ffffff", surface2="#f6f8fb", input="#ffffff", canvas="#e4e9f0",
        border="#dbe2ec", border_strong="#c3cddb",
        text="#0f1d33", muted="#5b6a80", faint="#9aa6b8", icon="#2c4266",
        accent="#1e3a8a", accent_hover="#2a4aa6", accent_press="#162d6e", on_accent="#ffffff",
        accent_soft="#e4ebf8", accent_text="#1e3a8a",
        hover="#edf1f7", selection="#dfe8f7",
        side_bg="#0f2747", side_text="#f1f5fb", side_muted="#93a8c6", side_hover="#17355d",
        side_sel="#234a80", side_border="#0f2747",
        danger="#c62828", danger_soft="#fdecec",
    ),
}

# Warna penanda (latar, teks) untuk status, sel tabel, dan lencana.
TONES = {
    "gelap": {
        "ok": ("#12301f", "#6ee7a0"), "warn": ("#3a2a0f", "#fbbf5a"), "error": ("#3d171a", "#fca5a5"),
        "info": ("#172846", "#9dbbff"), "chosen": ("#5b8cff", "#ffffff"), "neutral": ("#1f2631", "#b8c0ce"),
    },
    "terang": {
        "ok": ("#e2f5ea", "#146c43"), "warn": ("#fff2d9", "#8a5600"), "error": ("#fde7e7", "#b42318"),
        "info": ("#e4ebf8", "#1e3a8a"), "chosen": ("#1e3a8a", "#ffffff"), "neutral": ("#edf1f7", "#2c4266"),
    },
}

QSS = Template("""
* { outline: 0; }
QWidget { color: $text; font-size: 10pt; }
QMainWindow, QDialog, #content, QTabWidget > QWidget, QScrollArea > QWidget > QWidget { background: $bg; }
QToolTip { background: $surface2; color: $text; border: 1px solid $border_strong; border-radius: 6px; padding: 6px 8px; }

/* ---------- sidebar */
#sidebar { background: $side_bg; border-right: 1px solid $side_border; }
#sidebar QLabel { color: $side_text; background: transparent; }
#sidebar QLabel[role="muted"], #sidebar QLabel[role="section"] { color: $side_muted; }
#sidebar QListWidget { background: transparent; border: none; }
#sidebar QPushButton { background: transparent; color: $side_text; border: 1px solid transparent;
    border-radius: 8px; padding: 9px 12px; text-align: left; }
#sidebar QPushButton:hover { background: $side_hover; }
#sidebar QPushButton:pressed { background: $side_sel; }
#sidebar QPushButton:disabled { color: $side_muted; }
#sidebar QPushButton[variant="primary"] { background: $accent; color: $on_accent; text-align: center; font-weight: 600; }
#sidebar QPushButton[variant="primary"]:hover { background: $accent_hover; }
#sidebar QPushButton[variant="icon"] { padding: 8px; text-align: center; border: 1px solid $side_hover; }

/* ---------- teks */
QLabel { background: transparent; }
QLabel[role="title"] { font-size: 15pt; font-weight: 600; }
QLabel[role="brand"] { font-size: 13pt; font-weight: 700; }
QLabel[role="subtitle"], QLabel[role="muted"] { color: $muted; }
QLabel[role="section"] { color: $muted; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
QLabel[role="empty-title"] { font-size: 13pt; font-weight: 600; }
QLabel[role="badge"] { border-radius: 11px; padding: 3px 10px; font-weight: 600; font-size: 9pt; }
QLabel[role="badge"][tone="warn"] { background: $warn_bg; color: $warn_fg; }
QLabel[role="badge"][tone="ok"] { background: $ok_bg; color: $ok_fg; }
QLabel[role="badge"][tone="error"] { background: $error_bg; color: $error_fg; }
QLabel[role="badge"][tone="info"] { background: $info_bg; color: $info_fg; }
QLabel[role="badge"][tone="neutral"] { background: $neutral_bg; color: $neutral_fg; }
QLabel[role="stat-value"] { font-size: 17pt; font-weight: 700; }
QLabel[role="stat-value"][tone="ok"] { color: $ok_fg; }
QLabel[role="stat-value"][tone="warn"] { color: $warn_fg; }
QLabel[role="stat-value"][tone="error"] { color: $error_fg; }
QLabel[role="stat-value"][tone="info"] { color: $info_fg; }
QLabel[role="stat-caption"] { color: $muted; font-size: 9pt; }

QFrame[role="card"], QFrame[role="stat"] { background: $surface; border: 1px solid $border; border-radius: 12px; }
QFrame[role="toolbar"] { background: transparent; }
QFrame[role="divider"] { background: $border; max-width: 1px; min-width: 1px; }

/* ---------- tombol */
QPushButton { background: $surface2; color: $text; border: 1px solid $border; border-radius: 8px;
    padding: 8px 16px; min-height: 20px; font-weight: 500; }
QPushButton:hover { background: $hover; border-color: $border_strong; }
QPushButton:pressed { background: $selection; }
QPushButton:disabled { color: $faint; background: $surface; border-color: $border; }
QPushButton:checked { background: $accent_soft; border-color: $accent; color: $accent_text; }
QPushButton[variant="primary"] { background: $accent; color: $on_accent; border: 1px solid $accent; font-weight: 600; }
QPushButton[variant="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[variant="primary"]:pressed { background: $accent_press; }
QPushButton[variant="primary"]:disabled { background: $accent_soft; border-color: $accent_soft; color: $faint; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; }
QPushButton[variant="ghost"]:hover { background: $hover; }
QPushButton[variant="danger"] { color: $danger; }
QPushButton[variant="danger"]:hover { background: $danger_soft; border-color: $danger; }
QPushButton[variant="icon"] { padding: 7px; min-width: 22px; }

/* ---------- tab */
QTabWidget::pane { border: none; border-top: 1px solid $border; top: -1px; }
QTabBar { qproperty-drawBase: 0; background: transparent; }
QTabBar::tab { background: transparent; color: $muted; padding: 11px 18px; margin-right: 4px;
    border: none; border-bottom: 2px solid transparent; font-weight: 600; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabBar::tab:disabled { color: $faint; }

/* ---------- input */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background: $input; color: $text; border: 1px solid $border;
    border-radius: 8px; padding: 7px 10px; selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: $border_strong; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $faint; background: $surface; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url("$arrow_down"); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border_strong; border-radius: 8px;
    padding: 4px; selection-background-color: $selection; selection-color: $text; }
QSpinBox::up-button, QSpinBox::down-button { border: none; width: 22px; background: transparent; }
QSpinBox::up-arrow { image: url("$arrow_up"); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url("$arrow_down"); width: 12px; height: 12px; }
QPlainTextEdit { font-family: "Cascadia Mono", "Consolas"; font-size: 9pt; }

QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid $border_strong; background: $input; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }

QSlider { background: transparent; min-height: 22px; }
QSlider::groove:horizontal { height: 4px; background: $border_strong; border-radius: 2px; }
QSlider::sub-page:horizontal { height: 4px; background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: $accent; }
QSlider::handle:horizontal:hover { background: $accent_hover; }

/* ---------- tabel & daftar */
QTableView { background: $surface; alternate-background-color: $surface2; border: 1px solid $border;
    border-radius: 12px; gridline-color: $border; selection-background-color: $selection; selection-color: $text; }
QTableView::item { padding: 0 10px; border-bottom: 1px solid $border; }
QTableView::item:selected { background: $selection; color: $text; }
QTableView QTableCornerButton::section { background: $surface2; border: none; }
QHeaderView { background: transparent; }
QHeaderView::section { background: $surface2; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 9px 10px; font-weight: 600; font-size: 9pt; }
QHeaderView::section:first { border-top-left-radius: 12px; }
QHeaderView::section:last { border-top-right-radius: 12px; }

QListWidget { background: $surface; border: 1px solid $border; border-radius: 10px; padding: 4px; }
QListWidget::item { padding: 8px 10px; border-radius: 6px; }
QGroupBox QListWidget { border: none; background: transparent; padding: 0; }
QListWidget::item:hover { background: $hover; }
QListWidget::item:selected { background: $selection; color: $text; }

QGroupBox { background: $surface; border: 1px solid $border; border-radius: 12px; margin-top: 26px;
    padding: 14px 14px 12px 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 4px; top: 2px;
    padding: 0 4px; color: $muted; }

QProgressBar { background: $surface2; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }

QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 10px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: $border_strong; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: $faint; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QGraphicsView { border: 1px solid $border; border-radius: 12px; }
QMessageBox QLabel { min-width: 280px; }
""")


class _Bus(QObject):
    changed = Signal()


bus = _Bus()
_name = "gelap"
_dir = Path(tempfile.gettempdir()) / "ljk-reader-theme"


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


def _font():
    fams = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Inter"):
        if fam in fams:
            return QFont(fam, 10)
    return QFont()


def mono(size=10):
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Consolas", "Courier New"])
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
                      (QPalette.AlternateBase, "surface2"), (QPalette.Text, "text"), (QPalette.Button, "surface2"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "on_accent"), (QPalette.ToolTipBase, "surface2"),
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
        return c("side_text")
    return c("icon")


def set_icon(w, name_, tone_=None):
    """Pasang ikon pada tombol; warnanya mengikuti tema (dan berganti saat tema berganti)."""
    w.setProperty("icon_name", name_)
    if tone_:
        w.setProperty("icon_tone", tone_)
    w.setIcon(icons.icon(name_, _icon_color(w), c("faint")))


class Button(QPushButton):
    """QPushButton dengan jarak ikon-teks yang lebih lega."""

    def setText(self, text):
        super().setText(f"  {text}" if text and self.property("icon_name") else text)


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
