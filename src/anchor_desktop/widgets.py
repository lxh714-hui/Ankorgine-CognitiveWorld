import hashlib
from enum import Enum

from PySide6.QtCore import Qt, QSettings, Signal, QTimer, QPoint, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QScrollArea,
                               QVBoxLayout, QWidget, QPushButton, QToolButton)


SETTINGS_FORMAT = QSettings.Format.IniFormat
SETTINGS_SCOPE = QSettings.Scope.UserScope
SETTINGS_ORGANIZATION = "Anchor Cognitive World"
SETTINGS_APPLICATION = "Anchor Desktop"
ARCHIVE_STATE_KEY = "archive/state"


def archive_settings() -> QSettings:
    return QSettings(SETTINGS_FORMAT, SETTINGS_SCOPE, SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


def hidden_world_ids():
    value = archive_settings().value("catalog/hidden_world_ids", [])
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, (list, tuple)) else ()


def save_hidden_world_ids(values):
    settings = archive_settings()
    settings.setValue("catalog/hidden_world_ids", list(values))
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("package visibility settings could not be saved")


def configure_narrative_text(widget):
    """Share plain-text metrics without adding breaks or changing selection."""
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setIndent(0)
    widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    widget.setContentsMargins(0, 0, 0, 0)
    widget.setStyleSheet("padding:3px 0; margin:0; border:0;")


class OpeningSkipButton(QToolButton):
    """Geometry-only icon: no font glyph, icon asset or native button painting."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("openingSkip")
        self.setToolTip("跳过动画")
        self.setAccessibleName("跳过动画")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(28, 28)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event):
        # Deliberately do not call QToolButton.paintEvent / style.drawControl.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        emphasized = self.underMouse() or self.hasFocus() or self.isChecked()
        if emphasized or self.isDown():
            painter.setPen(QPen(QColor("#686868"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 4, 4)
        color = "#f2f2f2" if self.isDown() else "#dedede" if emphasized else "#b4b4b4"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.translate(self.width() / 2 - 9, self.height() / 2 - 6)
        for x in (0, 7):
            painter.drawPolygon(QPolygonF([QPointF(x, 0), QPointF(x + 6, 6), QPointF(x, 12)]))
        painter.drawRect(QRectF(16, 0, 2, 12))


class TypewriterOpening(QWidget):
    """Plain-text animation shared by authored prose and verified initial messages."""
    finished = Signal()
    skip_requested = Signal()

    def __init__(self, text: str, parent=None, *, heading="序章", start=True):
        super().__init__(parent)
        self.setObjectName("authoredOpening")
        self._text, self._cursor, self._finished = text, 0, False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if heading:
            title = QLabel(heading)
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            layout.addWidget(title)
        self.text_label = QLabel("")
        configure_narrative_text(self.text_label)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.text_label)
        # A child overlay, never an item in the narrative layout.
        self.skip_button = OpeningSkipButton(self)
        self.skip_button.clicked.connect(self.skip)
        self.skip_button.hide()
        self.setMinimumSize(36, 36)
        self._position_skip()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        if start:
            self.start()

    def _position_skip(self):
        inset = 4
        self.skip_button.move(self.width() - self.skip_button.width() - inset, inset)
        # On narrow panels keep the full text width, below the small control.
        margins = (0, 36, 0, 0) if self.width() < 160 else (0, 0, 36, 0)
        if self.layout().getContentsMargins() != margins:
            self.layout().setContentsMargins(*margins)
        self.skip_button.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_skip()

    def start(self):
        self.advance()
        if not self._finished:
            self.timer.start(25)
            self.skip_button.show()
            self.skip_button.raise_()

    def advance(self):
        if self._finished:
            return
        self._cursor = min(len(self._text), self._cursor + 2)
        self.text_label.setText(self._text[:self._cursor])
        if self._cursor == len(self._text):
            self.finish()

    def finish(self):
        if self._finished:
            return
        self.timer.stop()
        self._cursor, self._finished = len(self._text), True
        self.text_label.setText(self._text)
        self.skip_button.hide()
        self.finished.emit()

    def skip(self):
        self.skip_requested.emit()
        self.finish()


class HistoryTailFollower(QWidget):
    """Coalesced layout-driven following; never poll or rerender history."""
    def __init__(self, scroll, parent=None):
        super().__init__(parent)
        self.hide()
        self.bar = scroll.verticalScrollBar()
        self.following, self._moving = True, False
        self._deferred = QTimer(self)
        self._deferred.setSingleShot(True)
        self._deferred.timeout.connect(self._follow)
        self.bar.valueChanged.connect(self._position_changed)
        self.bar.rangeChanged.connect(self.request)

    def _position_changed(self, value):
        if not self._moving:
            self.following = self.bar.maximum() - value <= 16

    def request(self, *args):
        if self.following and not self._deferred.isActive():
            self._deferred.start(0)

    def _follow(self):
        if self.following:
            self._moving = True
            try:
                self.bar.setValue(self.bar.maximum())
            finally:
                self._moving = False


class ArchiveState(str, Enum):
    EXPANDED = "expanded"
    COLLAPSED = "collapsed"


class AvatarComposer:
    """Stable avatar adapter; replace rendering without changing its identity API."""
    @staticmethod
    def identity(character_id: str) -> tuple[str, str]:
        digest = hashlib.sha256(character_id.encode("utf-8")).hexdigest()
        return f"#{digest[:6]}", f"#{digest[6:12]}"

    @classmethod
    def widget(cls, character_id: str, size: int = 56) -> QWidget:
        return AvatarGlyph(character_id, size)


class AvatarGlyph(QWidget):
    def __init__(self, character_id: str, size: int = 56) -> None:
        super().__init__()
        self.character_id = character_id
        self.colors = AvatarComposer.identity(character_id)
        self.setFixedSize(size, size)
        self.setAccessibleName(f"组合头像 {character_id}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.setPen(QPen(QColor("#a7b5b5"), 1))
        painter.setBrush(QColor(self.colors[0]))
        painter.drawEllipse(rect)
        inner = rect.adjusted(rect.width() // 4, rect.height() // 4, -rect.width() // 4, -rect.height() // 4)
        painter.setBrush(QColor(self.colors[1]))
        painter.drawEllipse(inner)


class ArchivePanel(QFrame):
    def __init__(self, gateway, world_id: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("archivePanel")
        self.gateway, self.world_id = gateway, world_id
        self.setFixedWidth(292)
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("世界档案")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        root.addLayout(head)
        self.archive_scroll = QScrollArea()
        self.archive_scroll.setWidgetResizable(True)
        self.archive_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 8, 0)
        world = gateway.read_world_projection(world_id)
        self._section(sections, "角色", [c.name for c in world.characters])
        self._section(sections, "地点", list(world.locations))
        self._section(sections, "公开世界规则", list(world.public_rules))
        self._section(sections, "玩家已知事件", list(world.known_events))
        sections.addStretch()
        self.archive_scroll.setWidget(content)
        root.addWidget(self.archive_scroll, 1)

    @staticmethod
    def _section(layout, title, items):
        label = QLabel(title)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setObjectName("archiveHeading")
        layout.addWidget(label)
        for item in items:
            text = QLabel(f"· {item}")
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            text.setObjectName("archiveItem")
            layout.addWidget(text)


class ArchiveControlBar(QWidget):
    """Fixed, full-height click target; it has no resize or drag behavior."""
    clicked = Signal()
    WIDTH = 30
    CLICK_DELAY_MS = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._hovered = False
        self._pressed = False
        self._dragged = False
        self._press_pos = QPoint()
        self._suppress_release = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(self.CLICK_DELAY_MS)
        self._click_timer.timeout.connect(self.clicked.emit)
        self._double_click_reset = QTimer(self)
        self._double_click_reset.setSingleShot(True)
        self._double_click_reset.setInterval(self.CLICK_DELAY_MS)
        self._double_click_reset.timeout.connect(self._clear_suppressed_release)
        self.setFixedWidth(self.WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("折叠/展开世界档案 (Ctrl+B)")
        self.setAccessibleName("世界档案折叠控制条")

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragged = False
            self._press_pos = event.position().toPoint()
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event):
        if self._pressed and (event.position().toPoint() - self._press_pos).manhattanLength() > 6:
            self._dragged = True
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._suppress_release:
                self._suppress_release = False
                self._double_click_reset.stop()
                self._pressed = False
                event.accept()
                return
            if self._pressed:
                self._pressed = False
                event.accept()
            else:
                event.ignore()
                return
            if not self._dragged and self.rect().contains(event.position().toPoint()):
                self._click_timer.start()
            return
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self._pressed = False
            self._suppress_release = True
            self._double_click_reset.start()
            event.accept()
            return
        event.ignore()

    def _clear_suppressed_release(self):
        self._suppress_release = False

    def chevron_segments(self):
        """Return the two strokes; their shared endpoint is the pointing tip."""
        cx, cy = self.width() / 2, self.height() / 2
        dx, dy = 4.2, 4.5
        if self._expanded:
            return (((cx + dx, cy - dy), (cx - dx, cy)),
                    ((cx - dx, cy), (cx + dx, cy + dy)))
        return (((cx - dx, cy - dy), (cx + dx, cy)),
                ((cx + dx, cy), (cx - dx, cy + dy)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor("#292b2d") if self._hovered else QColor("#232629")
        painter.fillRect(self.rect(), background)
        painter.setPen(QPen(QColor("#46494a"), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        color = QColor("#c5b89c" if self._hovered else "#929895")
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for start, end in self.chevron_segments():
            painter.drawLine(int(start[0]), int(start[1]), int(end[0]), int(end[1]))


class ArchiveWorkspace(QWidget):
    def __init__(self, gateway, world_id: str, parent=None) -> None:
        super().__init__(parent)
        self.settings = archive_settings()
        self.content = QWidget()
        self.content.setMinimumWidth(0)
        self.panel = ArchivePanel(gateway, world_id)
        self.control_bar = ArchiveControlBar()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.content, 1)
        outer.addWidget(self.control_bar, 0)
        outer.addWidget(self.panel, 0)
        self.panel.setFixedWidth(292)
        self.control_bar.clicked.connect(self.toggle)
        self.restore_state()

    def toggle(self):
        self.set_state(ArchiveState.EXPANDED if self.is_collapsed() else ArchiveState.COLLAPSED)

    def is_collapsed(self):
        return self._state is ArchiveState.COLLAPSED

    def set_collapsed(self, collapsed: bool):
        self.set_state(ArchiveState.COLLAPSED if collapsed else ArchiveState.EXPANDED)

    def set_state(self, state: ArchiveState):
        if not isinstance(state, ArchiveState):
            state = ArchiveState(state)
        self._state = state
        self.panel.setVisible(state is ArchiveState.EXPANDED)
        self.control_bar.set_expanded(state is ArchiveState.EXPANDED)
        if self.settings.status() != QSettings.Status.NoError:
            return
        self.settings.setValue(ARCHIVE_STATE_KEY, state.value)
        self.settings.sync()
        # Navigation preference is never a prerequisite for live world output.
        # A restricted user profile may reject this optional UI-only write.

    def restore_state(self):
        self.settings.sync()
        raw_state = (self.settings.value(ARCHIVE_STATE_KEY, ArchiveState.EXPANDED.value)
                     if self.settings.status() == QSettings.Status.NoError
                     else ArchiveState.EXPANDED.value)
        try:
            state = ArchiveState(raw_state)
        except ValueError:
            state = ArchiveState.EXPANDED
        if state is ArchiveState.COLLAPSED:
            self._state = ArchiveState.COLLAPSED
            self.panel.hide()
            self.control_bar.set_expanded(False)
        else:
            self._state = ArchiveState.EXPANDED
            self.panel.show()
            self.control_bar.set_expanded(True)


def apply_dark_theme(app):
    app.setStyleSheet("""
        QWidget { background:#181a1d; color:#d8dcda; font-family:'Segoe UI','Microsoft YaHei UI'; font-size:14px; }
        QMainWindow, QFrame#archivePanel { background:#202327; }
        QLabel#pageTitle { color:#e8dfc9; font-size:25px; font-weight:600; }
        QLabel#sectionTitle { color:#e8dfc9; font-size:18px; font-weight:600; }
        QLabel#archiveHeading { color:#9facaa; font-size:12px; font-weight:700; margin-top:12px; }
        QLabel#archiveItem { color:#d1d4d0; padding:3px 0; }
        QLabel#muted { color:#9ba3a2; }
        QLabel#stageStatus { color:#9ba3a2; font-size:12px; padding:3px 2px; }
        QLabel#playerInputEntry { color:#c9d9d2; padding:3px 8px; border-left:2px solid #607e76; }
        QLabel#actionEffectEntry { color:#d8dcda; padding:3px 8px; }
        QLabel#dialogueEntry { color:#e2d2af; padding:3px 8px; border-left:2px solid #9b895f; }
        QLabel#clarificationEntry, QLabel#narrativeEntry { color:#b4c1bd; padding:3px 8px; font-style:italic; }
        QLabel#statusEntry { color:#9ba3a2; padding:2px 8px; font-size:12px; }
        QPushButton { background:#30353a; border:1px solid #454c50; border-radius:5px; padding:9px 14px; }
        QPushButton:hover { background:#3b4548; border-color:#788b86; }
        QPushButton:disabled { color:#77807e; background:#25292c; border-color:#32383a; }
        QPushButton#primary { background:#526e68; border-color:#6f9088; }
        QTextEdit:focus { border-color:#78968e; }
        QLineEdit, QTextEdit, QComboBox { background:#222629; border:1px solid #454c50; border-radius:4px; padding:8px; }
        QListWidget { background:#202327; border:1px solid #363b3f; border-radius:5px; }
        QListWidget::item { padding:11px; border-bottom:1px solid #303438; }
        QListWidget::item:selected { background:#354540; }
        QScrollArea { border:0; }
        QScrollBar:vertical { width:5px; background:#202327; margin:0; border:0; }
        QScrollBar::handle:vertical { background:#58605f; border-radius:2px; min-height:22px; }
        QScrollBar::handle:vertical:hover { background:#818b88; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; border:0; background:transparent; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
        QScrollBar:horizontal { height:5px; background:#202327; margin:0; border:0; }
        QScrollBar::handle:horizontal { background:#58605f; border-radius:2px; min-width:22px; }
        QScrollBar::handle:horizontal:hover { background:#818b88; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; border:0; background:transparent; }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }
    """)
