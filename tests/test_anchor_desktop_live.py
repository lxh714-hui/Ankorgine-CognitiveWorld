"""Desktop entry drives a real Runtime without waiting on its input Provider."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from anchor_desktop.app import MainWindow
from anchor_desktop.product_gateway import DesktopProductGateway
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.core.door import DoorState
from cognitive_world.player.input_understanding import InputUnderstandingStatus, PlayerInputAssessment


PACKAGES = Path(__file__).parents[1] / "src" / "anchor_desktop" / "worlds"


class LocalInterpreter:
    def understand(self, request, *, authorized_targets):
        target = next(item for item in authorized_targets if "door" in item)
        return PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the observed door", method="push the closed door", target_ref=target,
        )


@pytest.mark.parametrize("result", ("unparseable", "clarification", "unavailable"))
def test_desktop_no_result_finishes_processing_and_keeps_world_unchanged(qtbot, tmp_path, result):
    class Interpreter:
        def understand(self, request, *, authorized_targets):
            if result == "unavailable":
                raise TimeoutError("private provider details")
            if result == "clarification":
                return PlayerInputAssessment(
                    InputUnderstandingStatus.CLARIFICATION_REQUIRED,
                    intent="act on an observed target", method="choose a direction",
                    missing_information=("direction",),
                    clarification_question="你希望朝哪个方向行动？",
                )
            return PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE)

    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"desktop-no-result" * 3),
        input_understanding_provider=Interpreter(), saves_root=tmp_path / "saves",
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    window.navigate("world_detail", {"world_id": "rain-harbor"})
    window.stack.currentWidget().entry_button.click()
    qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
    stage = window.stack.currentWidget()
    before = tuple(gateway._active.runtime.context.event_history.get_events())
    stage.input_area.setPlainText("无法确定的输入")
    stage.submit.click()
    qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
    assert "处理中" not in stage.response.text()
    if result != "clarification":
        assert any(item.objectName() == "statusEntry" for item in stage.findChildren(QLabel))
    if result == "clarification":
        assert "等待补充" in stage.response.text()
        assert any("哪个方向" in item.text() for item in stage.findChildren(QLabel)
                   if item.objectName() == "clarificationEntry")
        assert not any("补充信息" in item.text() for item in stage.findChildren(QLabel)
                       if item.objectName() == "statusEntry")
    elif result == "unparseable":
        assert "没有理解" in stage.response.text()
    else:
        assert "超时" in stage.response.text()
    assert "private provider details" not in stage.response.text()
    assert tuple(gateway._active.runtime.context.event_history.get_events()) == before
    assert len([item for item in stage.findChildren(QLabel)
                if item.objectName() == "playerInputEntry"]) == 1
    window.close()


def test_english_provider_clarification_is_not_shown_raw_or_duplicated(qtbot, tmp_path):
    class Interpreter:
        def understand(self, request, *, authorized_targets):
            return PlayerInputAssessment(
                InputUnderstandingStatus.CLARIFICATION_REQUIRED,
                intent="interact", method="choose", missing_information=("target",),
                clarification_question="Do you mean the first object or the second object?",
            )

    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"desktop-language-key" * 3),
        input_understanding_provider=Interpreter(), saves_root=tmp_path / "saves",
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    window.navigate("world_detail", {"world_id": "rain-harbor"})
    window.stack.currentWidget().entry_button.click()
    qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
    stage = window.stack.currentWidget()
    stage.input_area.setPlainText("看看那个")
    stage.submit.click()
    assert "受理" in stage.response.text()
    qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
    entries = [item.text() for item in stage.findChildren(QLabel)
               if item.objectName() == "clarificationEntry"]
    assert len(entries) == 1
    assert "Do you mean" not in entries[0]
    assert "补充" in stage.response.text()
    assert not any("Do you mean" in item.text() for item in stage.findChildren(QLabel))
    assert not any(item.objectName() == "statusEntry" for item in stage.findChildren(QLabel))
    window.close()


def test_each_sequential_input_has_visible_admission_terminal_and_no_repeat(qtbot, tmp_path):
    from threading import Event

    started, release = Event(), Event()

    class Interpreter:
        calls = 0

        def understand(self, request, *, authorized_targets):
            self.calls += 1
            if self.calls == 1:
                started.set()
                if not release.wait(5):
                    raise TimeoutError("controlled wait expired")
            return PlayerInputAssessment(InputUnderstandingStatus.UNPARSEABLE)

    interpreter = Interpreter()
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"desktop-sequence-key" * 3),
        input_understanding_provider=interpreter, saves_root=tmp_path / "saves",
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    try:
        window.navigate("world_detail", {"world_id": "rain-harbor"})
        window.stack.currentWidget().entry_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        stage = window.stack.currentWidget()
        stage.input_area.setPlainText("第一条不明输入")
        QTest.mouseClick(stage.submit, Qt.MouseButton.LeftButton)
        first_id = stage._pending_request
        assert first_id and "受理" in stage.response.text()
        assert not stage.submit.isEnabled()
        assert started.wait(2)
        stage._poll_task()
        assert "处理" in stage.response.text()
        assert len([item for item in stage.findChildren(QLabel)
                    if item.objectName() == "playerInputEntry"]) == 1
        release.set()
        qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
        assert "没有理解" in stage.response.text()
        first_history_count = stage.action_effect_history.count()
        stage._poll_task()
        assert stage.action_effect_history.count() == first_history_count

        stage.input_area.setPlainText("第二条不明输入")
        QTest.mouseClick(stage.submit, Qt.MouseButton.LeftButton)
        second_id = stage._pending_request
        assert second_id != first_id
        assert "受理" in stage.response.text()
        qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
        assert "没有理解" in stage.response.text()
        stage._poll_task()
        assert [item.text() for item in stage.findChildren(QLabel)
                if item.objectName() == "playerInputEntry"] == [
                    "你：第一条不明输入", "你：第二条不明输入",
                ]
        assert interpreter.calls == 2
    finally:
        release.set()
        window.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_uncovered_action_is_reported_as_unresolved_not_failed_world_effect(qtbot, tmp_path, world_id):
    class UnsupportedInterpreter:
        def understand(self, request, *, authorized_targets):
            return PlayerInputAssessment(
                InputUnderstandingStatus.ACTION,
                intent="inspect an observed mechanism",
                method="look carefully without changing it",
                target_ref=authorized_targets[0],
            )

    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"unresolved-action-key" * 3),
        input_understanding_provider=UnsupportedInterpreter(), saves_root=tmp_path / "saves",
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    try:
        window.navigate("world_detail", {"world_id": world_id})
        window.stack.currentWidget().entry_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        stage = window.stack.currentWidget()
        before = tuple(gateway._active.runtime.context.event_history.get_events())
        stage.input_area.setPlainText("仔细看看眼前的物件")
        QTest.mouseClick(stage.submit, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
        assert gateway.input_status(stage._pending_request).outcome_status == "unresolved"
        assert "未能裁定" in stage.response.text()
        assert "没有达成预期" not in stage.response.text()
        assert tuple(gateway._active.runtime.context.event_history.get_events()) == before
    finally:
        window.close()


def test_desktop_back_click_cancels_old_input_before_world_switch(qtbot, tmp_path):
    from threading import Event

    started, release = Event(), Event()

    class BlockingInterpreter:
        def understand(self, request, *, authorized_targets):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test provider wait expired")
            return LocalInterpreter().understand(request, authorized_targets=authorized_targets)

    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"desktop-switch-key" * 3),
        input_understanding_provider=BlockingInterpreter(), saves_root=tmp_path / "saves",
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    window.show()
    try:
        window.navigate("world_detail", {"world_id": "clockwork-library"})
        window.stack.currentWidget().entry_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        stage = window.stack.currentWidget()
        old_session = gateway._active
        stage.input_area.setPlainText("Open the observed door.")
        stage.submit.click()
        qtbot.waitUntil(started.is_set, timeout=5000)
        old_handle = gateway._handles[stage._pending_request]
        before = tuple(old_session.runtime.context.event_history.get_events())
        QTest.mouseClick(stage.back_button, Qt.MouseButton.LeftButton)
        assert window.navigation.current.page == "worlds"
        assert gateway._active is None
        release.set()
        window.navigate("world_detail", {"world_id": "rain-harbor"})
        window.stack.currentWidget().entry_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        qtbot.waitUntil(lambda: old_session.player_tasks.get_status(old_handle).execution.value
                        not in {"accepted", "running"}, timeout=5000)
        assert tuple(old_session.runtime.context.event_history.get_events()) == before
        assert not any("Open the observed door" in item.text() for item in
                       window.stack.currentWidget().findChildren(QLabel))
    finally:
        release.set()
        window.close()


def test_world_status_page_returns_to_same_runtime_and_history(qtbot, tmp_path):
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"status-page-key" * 4),
        input_understanding_provider=LocalInterpreter(), saves_root=tmp_path / "saves",
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    window.show()
    try:
        window.navigate("world_detail", {"world_id": "rain-harbor"})
        window.stack.currentWidget().entry_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        stage = window.stack.currentWidget()
        runtime = gateway._active.runtime
        before = tuple(runtime.context.event_history.get_events())
        assert not [item for item in stage.findChildren(QLabel) if item.objectName() == "actionEffectEntry"]
        stage.opening.skip_button.click()
        history = [item.text() for item in stage.findChildren(QLabel)
                   if item.objectName() == "actionEffectEntry"]
        assert history == []
        assert stage.opening.text_label.text() == gateway.catalog.package("rain-harbor").opening
        QTest.mouseClick(stage.stage_buttons[0], Qt.MouseButton.LeftButton)
        assert window.navigation.current.page == "archive"
        page = window.stack.currentWidget()
        assert page.panel.width() > 292
        labels = [item.text() for item in page.findChildren(QLabel)]
        assert all(section in labels for section in
                   ("角色", "地点", "公开世界规则", "玩家已知事件"))
        assert all("instance:" not in item and "timeline:" not in item for item in labels)
        assert not any(event.id in item for event in before for item in labels)
        assert gateway._active.runtime is runtime
        assert tuple(runtime.context.event_history.get_events()) == before
        QTest.mouseClick(page.back_button, Qt.MouseButton.LeftButton)
        assert window.stack.currentWidget() is stage
        assert gateway._active.runtime is runtime
        assert tuple(runtime.context.event_history.get_events()) == before
        assert [item.text() for item in stage.findChildren(QLabel)
                if item.objectName() == "actionEffectEntry"] == history
    finally:
        window.close()


def test_corrupt_signed_save_disables_restore_entry_without_mutating_storage(qtbot, tmp_path):
    world_id = "clockwork-library"
    saves_root = tmp_path / "saves"
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"qt-corrupt-save-key" * 4),
        saves_root=saves_root,
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    try:
        window.navigate("world_detail", {"world_id": world_id})
        window.stack.currentWidget().entry_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        stage = window.stack.currentWidget()
        runtime = gateway._active.runtime
        stage.stage_buttons[3].click()
        qtbot.waitUntil(lambda: gateway.save_status().state != "saving", timeout=5000)
        assert gateway.save_status().state == "saved"
        catalog = saves_root / world_id / "catalog.json"
        catalog.write_bytes(catalog.read_bytes() + b"tampered")
        before = catalog.read_bytes()
        window.navigate("world_detail", {"world_id": world_id})
        detail = window.stack.currentWidget()
        qtbot.waitUntil(lambda: detail.save_button.text() != "正在核验存档", timeout=5000)
        assert detail.save_button.text() == "存档暂不可用"
        assert not detail.save_button.isEnabled()
        assert detail.entry_button.isEnabled()
        assert catalog.read_bytes() == before
        assert gateway._active.runtime is runtime
    finally:
        window.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_desktop_world_entry_and_async_fact_presentation(qtbot, tmp_path, world_id):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"desktop-live-test-key" * 2),
        input_understanding_provider=LocalInterpreter(),
        saves_root=tmp_path / "saves",
    )
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    window.show()
    window.navigate("world_detail", {"world_id": world_id})
    detail = window.stack.currentWidget()
    qtbot.waitUntil(lambda: detail.save_button.text() != "正在核验存档", timeout=5000)
    assert detail.save_button.text() == "当前无可用存档"
    assert not detail.save_button.isEnabled()
    assert detail.entry_button.isEnabled()
    detail.entry_button.click()
    qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
    stage = window.stack.currentWidget()
    assert stage.submit.isEnabled() and not stage.input_area.isReadOnly()
    assert stage.back_button.isEnabled()
    if stage.opening is not None:
        assert not [item for item in stage.findChildren(QLabel) if item.objectName() == "actionEffectEntry"]
        stage.opening.skip_button.click()
    initial = [item.text() for item in stage.findChildren(QLabel)
               if item.objectName() == "actionEffectEntry"]
    assert initial == []  # Startup evidence remains available to explicit observation.
    stage.input_area.setPlainText("Please open the observed door.")
    stage.submit.click()
    qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
    assert "行动已完成" in stage.response.text()
    assert any(item.objectName() == "playerInputEntry" for item in stage.findChildren(QLabel))
    entries = [item.text() for item in stage.findChildren(QLabel)
               if item.objectName() == "actionEffectEntry"]
    assert entries and all("instance:" not in item and "door_open" not in item for item in entries)
    committed_events = len(gateway._active.runtime.context.event_history.get_events())
    stage.input_area.setPlainText("Please open the observed door again.")
    stage.submit.click()
    qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
    assert stage.response.text() == "请求已结束；结果见历史。"
    feedback = [item.text() for item in stage.findChildren(QLabel)
                if item.objectName() == "actionEffectEntry"]
    assert "目标当前已经满足。" in feedback
    assert len(gateway._active.runtime.context.event_history.get_events()) == committed_events + 1
    doors = [state for state in gateway._active.runtime.context.world_state.environment.values()
             if isinstance(state, DoorState)]
    assert doors and all(state.is_open for state in doors)
    assert gateway.read_display() == ()
    QTest.mouseClick(stage.leave_button, Qt.MouseButton.LeftButton)
    assert window.navigation.current.page == "worlds"
    assert gateway.available_targets(world_id) == ()
    next_world = "rain-harbor" if world_id == "clockwork-library" else "clockwork-library"
    window.navigate("world_detail", {"world_id": next_world})
    window.stack.currentWidget().entry_button.click()
    qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
    assert window.stack.currentWidget().world_id == next_world
    window.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_desktop_save_close_reopen_restore_and_continue(qtbot, tmp_path, world_id):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    saves_root = tmp_path / "saves"
    def gateway():
        return DesktopProductGateway(
            PACKAGES, saves_root=saves_root,
            trust_supplier=lambda: HmacPersistenceTrust(b"desktop-restart-key" * 4),
            input_understanding_provider=LocalInterpreter(),
        )

    first_gateway = gateway()
    first_window = MainWindow(first_gateway)
    qtbot.addWidget(first_window)
    first_window.navigate("world_detail", {"world_id": world_id})
    first_window.stack.currentWidget().entry_button.click()
    qtbot.waitUntil(lambda: first_window.navigation.current.page == "stage", timeout=5000)
    first_stage = first_window.stack.currentWidget()
    first_stage.stage_buttons[3].click()
    qtbot.waitUntil(lambda: first_gateway.save_status().state != "saving", timeout=5000)
    assert first_gateway.save_status().state == "saved"
    save_id = first_gateway.save_status().save_id
    first_window.navigate("world_detail", {"world_id": world_id})
    detail = first_window.stack.currentWidget()
    qtbot.waitUntil(lambda: detail.save_button.text() != "正在核验存档", timeout=5000)
    assert detail.save_button.text() == "选择存档"
    assert detail.save_button.isEnabled()
    first_window.close()
    first_gateway.close()

    reopened_gateway = gateway()
    reopened_window = MainWindow(reopened_gateway)
    qtbot.addWidget(reopened_window)
    try:
        reopened_window.navigate("saves", {"world_id": world_id})
        saves = reopened_window.stack.currentWidget()
        assert saves.restore_button.isEnabled()
        assert len(saves.saves) == 1 and saves.saves[0].id == save_id
        saves.list.setCurrentRow(0)
        saves.restore_button.click()
        qtbot.waitUntil(lambda: reopened_window.navigation.current.page == "stage", timeout=5000)
        stage = reopened_window.stack.currentWidget()
        assert stage.world_id == world_id
        stage.input_area.setPlainText("Open the observed door.")
        stage.submit.click()
        qtbot.waitUntil(lambda: stage.submit.isEnabled(), timeout=5000)
        assert "行动已完成" in stage.response.text()
        assert all("instance:" not in item and "door_open" not in item for item in
                   (label.text() for label in stage.findChildren(QLabel)
                    if label.objectName() == "actionEffectEntry"))
    finally:
        reopened_window.close()
        reopened_gateway.close()
