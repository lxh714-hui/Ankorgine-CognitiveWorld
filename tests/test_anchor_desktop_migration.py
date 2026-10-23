"""M0.5 desktop shell: no fabricated world or synchronous Core submission."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea

from anchor_desktop.app import MainWindow
from anchor_desktop.engine import EngineGateway, UnavailableEngineGateway
from anchor_desktop.models import ActionEffectProjection, SaveSlot, WorldProjection
from anchor_desktop.navigation import Route
from anchor_desktop.pages import PAGE_TYPES, SaveListPage, StagePage, WorldDetailPage
from anchor_desktop.product_gateway import DisplayEntry
from anchor_desktop.widgets import ArchiveWorkspace, AvatarComposer, apply_dark_theme


@pytest.fixture(autouse=True)
def isolated_desktop_settings(tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))


class ProjectedTestGateway:
    """Test-only projection; it has no world-writing or synthetic Event methods."""

    def __init__(self):
        self.world = WorldProjection(
            "fixture-world", "Fixture World", "test projection", "test notice",
            (), (), (), (), "", "", "", "",
        )

    def list_worlds(self):
        return (self.world,)

    def read_world_projection(self, world_id, save_id=None):
        assert world_id == self.world.world_id
        return self.world

    def list_saves(self, world_id):
        return ()

    def list_timelines(self, save_id):
        return ()

    def available_targets(self, world_id):
        return ()

    def subscribe_performance(self, callback):
        return lambda: None


def test_default_shell_has_no_fabricated_world_or_save(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.gateway, UnavailableEngineGateway)
    assert isinstance(window.gateway, EngineGateway)
    assert window.gateway.list_worlds() == ()
    window.navigate("worlds", {})
    labels = [item.text() for item in window.stack.currentWidget().findChildren(QLabel)]
    assert any("尚未配置世界包" in value for value in labels)
    assert window.navigation.current.page == "worlds"


def test_all_source_pages_and_avatar_component_are_preserved():
    assert set(PAGE_TYPES) == {
        "home", "worlds", "world_detail", "saves", "stage", "archive",
        "history", "timeline", "settings", "management",
    }
    assert AvatarComposer.identity("character-a") == AvatarComposer.identity("character-a")
    assert AvatarComposer.identity("character-a") != AvatarComposer.identity("character-b")


def test_all_migrated_pages_can_construct_from_read_only_projection(qtbot):
    gateway = ProjectedTestGateway()
    for page_name, page_type in PAGE_TYPES.items():
        params = {"world_id": "fixture-world", "save_id": None}
        page = page_type(gateway, Route(page_name, params))
        qtbot.addWidget(page)
        assert page is not None


def test_unconnected_commands_cannot_report_success(qtbot):
    gateway = ProjectedTestGateway()
    detail = WorldDetailPage(gateway, Route("world_detail", {"world_id": "fixture-world"}))
    qtbot.addWidget(detail)
    buttons = detail.findChildren(QPushButton)
    assert detail.save_button.text() == "当前无可用存档"
    assert not detail.save_button.isEnabled()
    assert all(not widget.isEnabled() for widget in buttons if widget.text() == "进入运行舞台")

    stage = StagePage(gateway, Route("stage", {"world_id": "fixture-world", "save_id": None}))
    qtbot.addWidget(stage)
    assert stage.input_area.isReadOnly()
    assert not stage.submit.isEnabled()
    assert [button.isEnabled() for button in stage.stage_buttons] == [True, False, False, False]
    stage.input_area.setPlainText("fixture action")
    stage.submit_action()
    assert "未提交行动" in stage.response.text()
    stage._on_performance({"effect": "untrusted arbitrary mapping"})
    assert stage._history_placeholder is not None
    stage._on_performance(ActionEffectProjection(subject="fixture", effect="typed display field"))
    assert stage._history_placeholder is None
    entries = [item for item in stage.findChildren(QLabel) if item.objectName() == "actionEffectEntry"]
    assert len(entries) == 1
    assert entries[0].text() == "fixture  ·  typed display field"


def test_world_detail_keeps_new_world_entry_when_save_catalog_is_unreadable(qtbot):
    class UnreadableCatalog(ProjectedTestGateway):
        def list_saves(self, world_id):
            raise PermissionError("private storage path")

        def begin_world(self, world_id):
            return None

    page = WorldDetailPage(UnreadableCatalog(), Route("world_detail", {"world_id": "fixture-world"}))
    qtbot.addWidget(page)
    assert page.entry_button.isEnabled()
    assert page.save_button.text() == "存档暂不可用"
    assert not page.save_button.isEnabled()
    assert any("无法核验本地存档" in item.text() for item in page.findChildren(QLabel))
    assert all("private storage path" not in item.text() for item in page.findChildren(QLabel))


def test_world_detail_save_entry_distinguishes_empty_valid_and_unavailable(qtbot):
    class MutableCatalog(ProjectedTestGateway):
        saves = ()
        unavailable = False

        def list_saves(self, world_id):
            if self.unavailable:
                raise PermissionError("private catalog path")
            return self.saves

    gateway = MutableCatalog()
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    window.navigate("world_detail", {"world_id": "fixture-world"})
    detail = window.stack.currentWidget()
    assert detail.save_button.text() == "当前无可用存档"
    assert not detail.save_button.isEnabled()
    QTest.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)
    assert window.navigation.current.page == "world_detail"

    gateway.saves = (SaveSlot("save-secret", "fixture-world", "手动存档", "now", 1),)
    window.navigate("home", {})
    window.navigate("__back__", {})
    assert window.stack.currentWidget() is detail
    assert detail.save_button.text() == "选择存档"
    assert detail.save_button.isEnabled()
    detail.save_button.click()
    assert window.navigation.current.page == "saves"

    gateway.unavailable = True
    window.navigate("__back__", {})
    assert window.stack.currentWidget() is detail
    assert detail.save_button.text() == "存档暂不可用"
    assert not detail.save_button.isEnabled()
    assert all("private catalog path" not in item.text() for item in detail.findChildren(QLabel))


def test_save_list_reports_catalog_permission_failure_without_raw_error(qtbot):
    class UnreadableCatalog(ProjectedTestGateway):
        def list_saves(self, world_id):
            raise PermissionError("private storage path")

    page = SaveListPage(UnreadableCatalog(), Route("saves", {"world_id": "fixture-world"}))
    qtbot.addWidget(page)
    assert not page.restore_button.isEnabled()
    texts = [item.text() for item in page.findChildren(QLabel)]
    assert any("存档列表暂不可用" in text for text in texts)
    assert all("private storage path" not in text for text in texts)


def test_stage_history_keeps_keyboard_scrolling_with_narrow_dark_scrollbar(qtbot, qapp):
    original_style = qapp.styleSheet()
    try:
        apply_dark_theme(qapp)
        assert "QScrollBar:vertical { width:5px" in qapp.styleSheet()
        stage = StagePage(ProjectedTestGateway(), Route("stage", {"world_id": "fixture-world"}))
        qtbot.addWidget(stage)
        stage.show()
        for index in range(24):
            stage._append_history_line(f"可展示的第 {index} 条记录。", "actionEffectEntry")
        bar = stage.history_scroll.verticalScrollBar()
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
        bar.setValue(0)
        bar.setFocus()
        QTest.keyClick(bar, Qt.Key.Key_Down)
        assert bar.value() > 0
    finally:
        qapp.setStyleSheet(original_style)


def test_stage_uses_history_as_main_area_and_groups_input_controls(qtbot):
    class ActiveGateway(ProjectedTestGateway):
        def submit_input(self, text):
            return "accepted"

        def leave_world(self):
            return None

    stage = StagePage(ActiveGateway(), Route("stage", {"world_id": "fixture-world"}))
    qtbot.addWidget(stage)
    assert stage.findChild(QFrame, "narrativeScene") is None
    assert stage.findChild(QScrollArea, "stageScroll") is None
    assert stage.history_scroll.maximumHeight() > 1000
    assert stage.layout.indexOf(stage.history_scroll) < stage.layout.indexOf(stage.response)
    assert stage.layout.indexOf(stage.response) < stage.layout.indexOf(stage.interaction)
    assert stage.input_area.parentWidget() is stage.interaction
    assert stage.submit.parentWidget() is stage.interaction
    assert stage.leave_button.parentWidget() is stage.interaction
    assert stage.response.maximumHeight() <= 30
    stage.show()
    qtbot.wait(10)
    assert stage.leave_button.width() == stage.interaction.contentsRect().width()


def test_stage_history_stays_at_older_position_when_new_items_arrive(qtbot):
    stage = StagePage(ProjectedTestGateway(), Route("stage", {"world_id": "fixture-world"}))
    qtbot.addWidget(stage)
    stage.resize(680, 480)
    stage.show()
    for index in range(70):
        stage._append_history_line(f"已授权记录 {index}", "actionEffectEntry")
    qtbot.waitUntil(lambda: stage.history_scroll.verticalScrollBar().maximum() > 100, timeout=2000)
    qtbot.wait(10)
    bar = stage.history_scroll.verticalScrollBar()
    bar.setValue(20)
    stage._append_history_line("后来的已授权记录", "actionEffectEntry")
    qtbot.wait(10)
    assert bar.value() < bar.maximum() - 20
    assert [item.text() for item in stage.findChildren(QLabel)
            if item.objectName() == "actionEffectEntry"][-1] == "后来的已授权记录"


def test_stage_history_accepts_only_known_display_types(qtbot):
    class DisplayGateway(ProjectedTestGateway):
        entries = ()

        def read_display(self):
            entries, self.entries = self.entries, ()
            return entries

    gateway = DisplayGateway()
    stage = StagePage(gateway, Route("stage", {"world_id": "fixture-world"}))
    qtbot.addWidget(stage)
    gateway.entries = (
                DisplayEntry("fact", "已确认的环境描述。"),
                DisplayEntry("dialogue", "已经授权的角色言语。"),
                DisplayEntry("clarification", "请说明方向。"),
                DisplayEntry("unknown", "instance:private:door_open"),
            )

    stage._append_display()
    entries = [item for item in stage.findChildren(QLabel)
               if item.objectName() in {"actionEffectEntry", "dialogueEntry", "clarificationEntry"}]
    assert [item.text() for item in entries] == ["已确认的环境描述。", "已经授权的角色言语。", "请说明方向。"]
    assert all("instance:" not in item.text() for item in stage.findChildren(QLabel))


def test_stage_back_click_keeps_page_when_session_close_fails(qtbot):
    class FailingClose(ProjectedTestGateway):
        def leave_world(self):
            raise RuntimeError("private close detail")

    stage = StagePage(FailingClose(), Route("stage", {"world_id": "fixture-world"}))
    qtbot.addWidget(stage)
    stage.show()
    navigation = []
    stage.navigate.connect(lambda page, params: navigation.append(page))
    QTest.mouseClick(stage.back_button, Qt.MouseButton.LeftButton)
    assert navigation == []
    assert "会话尚未结束" in stage.response.text()
    assert "private close detail" not in stage.response.text()


def test_archive_navigation_survives_unwritable_optional_settings(qtbot, monkeypatch):
    class DeniedSettings:
        def sync(self):
            pass

        def status(self):
            return QSettings.Status.AccessError

        def value(self, *_):
            raise AssertionError("unreadable settings must use a default")

        def setValue(self, *_):
            raise AssertionError("unwritable settings must not be retried")

    monkeypatch.setattr("anchor_desktop.widgets.archive_settings", DeniedSettings)
    workspace = ArchiveWorkspace(ProjectedTestGateway(), "fixture-world")
    qtbot.addWidget(workspace)
    workspace.set_collapsed(True)
    assert workspace.is_collapsed()
    workspace.set_collapsed(False)
    assert not workspace.is_collapsed()


def test_core_import_has_no_desktop_dependency():
    import ast
    from pathlib import Path

    core = Path(__file__).resolve().parents[1] / "src" / "cognitive_world"
    forbidden = {"PySide6", "PyQt6", "anchor_desktop"}
    for path in core.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden for alias in node.names), path
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden, path
