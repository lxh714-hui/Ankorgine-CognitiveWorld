import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QStackedWidget

from .engine import UnavailableEngineGateway
from .product_gateway import DesktopProductGateway
from .navigation import NavigationStack, Route
from .pages import PAGE_TYPES
from .widgets import apply_dark_theme


class MainWindow(QMainWindow):
    def __init__(self, gateway=None):
        super().__init__()
        self.setWindowTitle("Anchor Cognitive World")
        self.resize(1240, 800)
        self.gateway = gateway if gateway is not None else UnavailableEngineGateway()
        self.navigation = NavigationStack()
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._widgets = {}
        self._render_current()
        self.shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.shortcut.activated.connect(self.toggle_archive)

    def _render_current(self):
        route = self.navigation.current
        cached = self._widgets.get(id(route))
        if cached:
            refresh_saves = getattr(cached, "refresh_saves", None)
            if callable(refresh_saves):
                refresh_saves()
            self.stack.setCurrentWidget(cached)
            return
        page_type = PAGE_TYPES.get(route.page)
        if page_type is None:
            return
        page = page_type(self.gateway, route)
        page.navigate.connect(self.navigate)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self._widgets[id(route)] = page

    def navigate(self, page, params):
        if page == "__reset_worlds__":
            for widget in self._widgets.values():
                self.stack.removeWidget(widget)
                widget.deleteLater()
            self._widgets.clear()
            self.navigation = NavigationStack(Route("worlds"))
            self._render_current()
            return
        if page == "__back__":
            if len(self.navigation.routes) > 1:
                popped = self.navigation.current
                self.navigation.pop()
                widget = self._widgets.pop(id(popped), None)
                if widget:
                    self.stack.removeWidget(widget)
                    widget.deleteLater()
                self._render_current()
            return
        self.navigation.push(page, **params)
        self._render_current()

    def toggle_archive(self):
        page = self.stack.currentWidget()
        if self.navigation.current.page == "stage":
            self.navigate("archive", {"world_id": page.world_id, "save_id": page.save_id})
        elif self.navigation.current.page == "archive":
            self.navigate("__back__", {})

    def closeEvent(self, event):
        close = getattr(self.gateway, "close", None)
        if callable(close):
            close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("Anchor Cognitive World")
    app.setApplicationName("Anchor Desktop")
    apply_dark_theme(app)
    try:
        gateway = DesktopProductGateway()
    except (OSError, ValueError, PermissionError):
        gateway = UnavailableEngineGateway()
        gateway.status_message = "世界包未通过本地检查，无法进入世界。"
    window = MainWindow(gateway)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
