"""Authored openings and synthetic provider startup never acquire world authority."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from anchor_desktop.product_gateway import DesktopProductGateway
from anchor_desktop import model_warmup
from anchor_desktop.model_warmup import LocalModelWarmup, ModelNotReady
from anchor_desktop.world_packages import WorldPackageCatalog
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.player.input_understanding import (
    OllamaPlayerInputUnderstandingProvider, InputUnderstandingStatus, PlayerInputAssessment,
)

PACKAGES = Path(__file__).parents[1] / "src" / "anchor_desktop" / "worlds"


@pytest.fixture
def local_model(monkeypatch):
    monkeypatch.setattr(model_warmup, "_JOBS", {})
    return OllamaPlayerInputUnderstandingProvider("http://127.0.0.1:11434/v1", "opening-test", 1.0)


def completed_response(content="WARMUP_PRIVATE_RESPONSE"):
    return json.dumps({"choices": [{"message": {"content": content},
                                    "finish_reason": "stop"}]}).encode()


def gateway(tmp_path, provider):
    return DesktopProductGateway(PACKAGES, saves_root=tmp_path / "saves",
                                 trust_supplier=lambda: HmacPersistenceTrust(b"opening-test-key" * 4),
                                 input_understanding_provider=provider)


def enter(host, *, restoring=None):
    if restoring is None:
        host.begin_world("rain-harbor")
    else:
        host.begin_restore("rain-harbor", restoring)
    host._entry.result(timeout=5)
    assert host.entry_status().state == "ready"
    return host._active.runtime.context


def test_world_opening_is_package_data_not_installed_cognition_or_model_context(tmp_path):
    package = WorldPackageCatalog(PACKAGES).package("rain-harbor")
    manifest = json.loads((PACKAGES / "rain-harbor" / "manifest.json").read_text(encoding="utf-8"))
    assert package.opening == manifest["opening"]
    assert "这里有一个名字：灰域。" in package.opening
    assert all(name in package.opening for name in ("灵诡", "孽生", "无因", "恒序", "血戮"))
    host = gateway(tmp_path, object())
    try:
        context = enter(host)
        before = context.event_history.get_events()
        assert host.take_opening() == package.opening
        assert host.take_opening() == ""
        assert context.event_history.get_events() == before
        assert all(item.kind == "fact" for item in host.read_display())
        assert host._active.memory_store.get_all_memories() == ()
        assert len(host._active.cognition.beliefs) == 0
    finally:
        host.close()


def test_old_manifest_remains_supported_and_new_fields_are_bounded(tmp_path):
    import shutil
    folder = tmp_path / "rain-harbor"
    shutil.copytree(PACKAGES / "rain-harbor", folder)
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for field in ("opening", "english_title", "listed"):
        manifest.pop(field, None)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert WorldPackageCatalog(tmp_path).package("rain-harbor").opening == ""
    for field, value in (("listed", "false"), ("opening", "x" * 2001), ("model_context", "unapproved")):
        path.write_text(json.dumps({**manifest, field: value}), encoding="utf-8")
        with pytest.raises(ValueError):
            WorldPackageCatalog(tmp_path)


def test_warmup_does_not_block_entry_or_touch_history_or_accept_early_input(tmp_path, local_model, monkeypatch):
    started, release = Event(), Event()
    calls = []
    def post(url, body, **kwargs):
        calls.append(json.loads(body))
        started.set()
        assert release.wait(5)
        return completed_response()
    monkeypatch.setattr(model_warmup, "_post_loopback_json", post)
    host = gateway(tmp_path, local_model)
    try:
        context = enter(host)
        assert started.wait(2)
        assert host.model_status().state == "warming"
        assert host.take_opening()
        before = (context.event_history.get_events(), dict(context.world_state.locations),
                  dict(context.world_state.environment))
        initial_display = host.read_display()
        with pytest.raises(ModelNotReady, match="warming"):
            host.submit_input("PRIVATE_PLAYER_INPUT")
        assert not host._handles
        release.set()
        assert host._warmup._job.result(timeout=3).state == "ready"
        assert (context.event_history.get_events(), dict(context.world_state.locations),
                dict(context.world_state.environment)) == before
        assert host.read_display() == ()
        assert all("WARMUP_PRIVATE_RESPONSE" not in entry.text for entry in initial_display)
        assert calls == [{"model": local_model.model, "messages": [{"role": "user", "content": "Reply with OK."}],
                          "temperature": 0, "max_tokens": 8, "stream": False}]
    finally:
        release.set()
        host.close()


def test_concurrent_world_initializations_share_one_model_warmup(tmp_path, local_model, monkeypatch):
    started, release = Event(), Event()
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        started.set()
        assert release.wait(5)
        return completed_response()
    monkeypatch.setattr(model_warmup, "_post_loopback_json", post)
    hosts = [gateway(tmp_path / str(i), local_model) for i in range(2)]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            contexts = list(pool.map(enter, hosts))
        assert started.wait(2)
        assert hosts[0]._warmup._job is hosts[1]._warmup._job
        assert all(host.model_status().state == "warming" for host in hosts)
        assert len(calls) == 1
        before = [context.event_history.get_events() for context in contexts]
        hosts[0].close()
        assert hosts[0].model_status().state == "closed"
        release.set()
        assert hosts[1]._warmup._job.result(timeout=3).state == "ready"
        assert [context.event_history.get_events() for context in contexts] == before
        assert len(calls) == 1
    finally:
        release.set()
        for host in hosts:
            host.close()


@pytest.mark.parametrize("failure", [TimeoutError("private"), ConnectionError("private"), b"not-json",
                                    b'{"choices":[{"message":{"content":"OK"},"finish_reason":null}]}'])
def test_failed_warmup_needs_explicit_retry_but_world_and_opening_work(tmp_path, local_model, monkeypatch, failure):
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            return completed_response()
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(model_warmup, "_post_loopback_json", post)
    host = gateway(tmp_path, local_model)
    try:
        context = enter(host)
        assert host._warmup._job.result(timeout=3).state == "failed"
        assert host.take_opening()
        before = context.event_history.get_events()
        with pytest.raises(ModelNotReady, match="failed"):
            host.submit_input("private player text")
        for _ in range(4):
            assert host.model_status().state == "failed"
        assert len(calls) == 1
        host.leave_world()
        context = enter(host)
        assert host.model_status().state == "failed"
        assert len(calls) == 1
        before = context.event_history.get_events()
        host.retry_model_warmup()
        assert host._warmup._job.result(timeout=3).state == "ready"
        assert len(calls) == 2
        assert context.event_history.get_events() == before
    finally:
        host.close()


def test_warmup_uses_captured_configured_provider_and_requires_inference(monkeypatch):
    monkeypatch.setattr(model_warmup, "_JOBS", {})
    monkeypatch.setenv("COGNITIVEWORLD_INPUT_UNDERSTANDING_PROVIDER", "ollama")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_MODEL", "configured-model")
    monkeypatch.setenv("COGNITIVEWORLD_OLLAMA_BASE_URL", "http://127.0.0.1:12345/v1")
    monkeypatch.setenv("COGNITIVEWORLD_INPUT_UNDERSTANDING_TIMEOUT", "0.75")
    calls = []
    def post(url, body, **kwargs):
        calls.append((url, json.loads(body), kwargs))
        return completed_response()
    monkeypatch.setattr(model_warmup, "_post_loopback_json", post)
    warmup = LocalModelWarmup()
    warmup.start()
    assert warmup._job.result(timeout=3).state == "ready"
    assert calls[0][0] == "http://127.0.0.1:12345/v1"
    assert calls[0][1]["model"] == "configured-model"
    assert calls[0][2]["timeout_seconds"] == 0.75
    warmup.close()


def test_unconfigured_or_other_provider_does_not_warmup(monkeypatch):
    monkeypatch.delenv("COGNITIVEWORLD_INPUT_UNDERSTANDING_PROVIDER", raising=False)
    monkeypatch.setattr(model_warmup, "_post_loopback_json", lambda *args, **kwargs: pytest.fail("no inference"))
    warmup = LocalModelWarmup()
    warmup.start()
    assert warmup.status().state == "not_configured"
    warmup.start(object())
    assert warmup.status().state == "not_required"
    warmup.close()


def test_restore_keeps_old_save_identity_without_opening_and_new_session_replays(tmp_path):
    host = gateway(tmp_path, object())
    package = host.catalog.package("rain-harbor")
    # A pre-rebrand package has the same durable world/scenario/role identities.
    old_locations = tuple(replace(item, description={"pier": "雨港码头", "station": "港口观测站"}[item.template_id])
                          for item in package.proposal.locations)
    host.catalog._packages["rain-harbor"] = replace(package, title="雨港观测站", opening="",
                                                   proposal=replace(package.proposal, locations=old_locations))
    try:
        context = enter(host)
        actor = context.player_session.controlled_agent_id
        timeline = context.event_history.timeline_id
        location = context.world_state.locations[actor]
        host.begin_save()
        host._save.result(timeout=5)
        save_id = host.save_status().save_id
        host.leave_world()
        host.catalog._packages["rain-harbor"] = package
        context = enter(host, restoring=save_id)
        assert context.event_history.timeline_id == timeline
        assert context.player_session.controlled_agent_id == actor
        assert context.world_state.locations[actor] == location
        assert host.take_opening() == ""
        assert host.catalog.package("rain-harbor").title == "灰域之外"
        host.leave_world()
        enter(host)
        assert host.take_opening() == package.opening
        assert host.take_opening() == ""
    finally:
        host.close()


def test_typewriter_completion_skip_and_timer_responsiveness(qtbot):
    from anchor_desktop.widgets import TypewriterOpening
    from PySide6.QtCore import QTimer
    widget = TypewriterOpening("序章\n\n" + "这是未确证的设定叙述。" * 8)
    qtbot.addWidget(widget)
    widget.show()
    initial = widget.text_label.text()
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    qtbot.waitUntil(lambda: bool(heartbeat) and len(widget.text_label.text()) > len(initial))
    assert widget.text_label.text() != widget._text
    widget.skip_button.click()
    assert widget.text_label.text() == widget._text
    assert not widget.timer.isActive()
    assert widget.skip_button.isHidden()
    short = TypewriterOpening("短序章")
    qtbot.addWidget(short)
    qtbot.waitUntil(lambda: not short.timer.isActive())
    assert short.text_label.text() == "短序章"


def test_qt_stage_keeps_early_input_then_commits_once(qtbot, tmp_path, local_model, monkeypatch):
    from anchor_desktop.app import MainWindow
    started, release = Event(), Event()
    def post(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return completed_response()
    interpreted = []
    def understand(self, request, *, candidates):
        interpreted.append(request.text)
        door = next(item for item in candidates if item.kind == "door")
        return PlayerInputAssessment(InputUnderstandingStatus.ACTION, "open door",
                                     door.supported_methods[0], door.handle)
    monkeypatch.setattr(model_warmup, "_post_loopback_json", post)
    monkeypatch.setattr(OllamaPlayerInputUnderstandingProvider, "understand_candidates", understand)
    host = gateway(tmp_path, local_model)
    window = MainWindow(host)
    qtbot.addWidget(window)
    try:
        window.navigate("world_detail", {"world_id": "rain-harbor"})
        window.stack.currentWidget().entry_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        assert started.wait(2)
        stage = window.stack.currentWidget()
        assert stage.opening is not None and stage.opening.timer.isActive()
        context = host._active.runtime.context
        before = context.event_history.get_events()
        stage.input_area.setPlainText("打开门")
        stage.submit.click()
        assert stage.input_area.toPlainText() == "打开门"
        assert "输入已保留" in stage.response.text()
        assert not host._handles and not interpreted
        assert context.event_history.get_events() == before
        stage.opening.skip_button.click()
        assert stage.opening.text_label.text() == host.catalog.package("rain-harbor").opening
        release.set()
        qtbot.waitUntil(lambda: host.model_status().state == "ready")
        stage.submit.click()
        stage.submit_action()  # A second submit cannot enqueue while the first is active.
        qtbot.waitUntil(lambda: bool(host._handles) and stage.submit.isEnabled(), timeout=5000)
        assert interpreted == ["打开门"]
        assert host.input_status(stage._pending_request).outcome_status == "resolved"
        assert len(context.event_history.get_events()) == len(before) + 1
        assert stage.input_area.toPlainText() == ""
        assert not any("WARMUP_PRIVATE_RESPONSE" in item.text for item in host.read_display())
    finally:
        release.set()
        window.close()


def test_qt_world_selection_has_one_new_world_and_keeps_legacy_save_restore(qtbot, tmp_path):
    from anchor_desktop.app import MainWindow
    from PySide6.QtWidgets import QPushButton
    host = gateway(tmp_path, object())
    host.begin_world("clockwork-library")
    host._entry.result(timeout=5)
    assert host.entry_status().state == "ready"
    host.begin_save()
    host._save.result(timeout=5)
    host.leave_world()
    window = MainWindow(host)
    qtbot.addWidget(window)
    try:
        window.navigate("worlds", {})
        page = window.stack.currentWidget()
        cards = [item for item in page.findChildren(QPushButton) if item.text() == "查看世界  →"]
        assert len(cards) == 1
        assert host.list_worlds()[0].title == "灰域之外"
        assert not any(item.text().startswith("恢复旧版") for item in page.findChildren(QPushButton))
        next(item for item in page.findChildren(QPushButton) if item.text() == "管理世界与存档").click()
        manage = window.stack.currentWidget()
        manage.worlds.setCurrentIndex(manage.worlds.findData("clockwork-library"))
        next(item for item in manage.findChildren(QPushButton) if item.text().startswith("查看／恢复")).click()
        assert window.navigation.current.page == "saves"
        saves = window.stack.currentWidget()
        assert saves.list.count() == 1
        saves.list.setCurrentRow(0)
        saves.restore_button.click()
        qtbot.waitUntil(lambda: window.navigation.current.page == "stage", timeout=5000)
        assert host._active.package.world_id == "clockwork-library"
        assert window.stack.currentWidget().opening is None
        from PySide6.QtWidgets import QToolButton
        assert not window.stack.currentWidget().findChildren(QToolButton, "openingSkip")
    finally:
        window.close()


def test_shared_model_views_follow_an_explicit_retry(local_model, monkeypatch):
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("unavailable")
        return completed_response()
    monkeypatch.setattr(model_warmup, "_post_loopback_json", post)
    first, second = LocalModelWarmup(), LocalModelWarmup()
    first.start(local_model)
    assert first._job.result(timeout=3).state == "failed"
    second.start(local_model)
    assert second.status().state == "failed"
    first.start(local_model, retry=True)
    assert first._job.result(timeout=3).state == "ready"
    assert second.status().state == "ready"
    assert len(calls) == 2
    first.close()
    second.close()


def test_skip_overlay_is_accessible_responsive_and_preserves_input_focus(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
    from anchor_desktop.widgets import TypewriterOpening, apply_dark_theme

    window = QWidget()
    qtbot.addWidget(window)
    apply_dark_theme(window)
    layout = QVBoxLayout(window)
    opening = TypewriterOpening("正文换行与段落。" * 1000, heading="", start=False)
    entry = QLineEdit()
    layout.addWidget(opening)
    layout.addWidget(entry)
    window.show()
    window.activateWindow()
    entry.setFocus()
    qtbot.waitUntil(entry.hasFocus)
    assert opening.skip_button.isHidden()
    opening.start()
    button = opening.skip_button
    assert button.text() == "" and button.icon().isNull()
    assert button.toolTip() == button.accessibleName() == "跳过动画"
    assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert opening.layout().indexOf(button) == -1
    assert entry.hasFocus()
    assert button.isVisible()

    for width in (560, 120, 80, 360):
        opening.setFixedWidth(width)
        opening._cursor = 300
        opening.advance()
        opening.layout().activate()
        qtbot.waitUntil(lambda: button.x() == opening.width() - button.width() - 4)
        assert button.y() == 4
        assert opening.rect().contains(button.geometry())
        assert not button.geometry().intersects(opening.text_label.geometry())
        assert entry.hasFocus()

    with qtbot.waitSignal(opening.finished):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert entry.hasFocus()
    assert opening.text_label.text() == opening._text
    assert button.isHidden()
    assert not opening.timer.isActive()
    opening.start()
    assert button.isHidden()


def test_skip_control_hides_on_natural_completion(qtbot):
    from anchor_desktop.widgets import TypewriterOpening

    opening = TypewriterOpening("短篇序章", start=False)
    qtbot.addWidget(opening)
    opening.show()
    opening.start()
    assert opening.skip_button.isVisible()
    qtbot.waitUntil(lambda: opening._finished)
    assert opening.text_label.text() == "短篇序章"
    assert opening.skip_button.isHidden()


@pytest.mark.parametrize("state", ["idle", "hover", "pressed", "checked", "focus"])
def test_custom_skip_pixels_are_monochrome_and_background_transparent(qtbot, state):
    from PySide6.QtCore import QPoint, Qt
    from anchor_desktop.widgets import OpeningSkipButton, TypewriterOpening, apply_dark_theme
    opening = TypewriterOpening("Narrative " * 1000)
    qtbot.addWidget(opening)
    apply_dark_theme(opening)
    # Even a conflicting platform-like button background cannot enter paintEvent.
    opening.setStyleSheet(opening.styleSheet() + "QToolButton { background:#0066ff; }")
    opening.resize(400, 160)
    opening.show()
    button = opening.skip_button
    assert isinstance(button, OpeningSkipButton)
    assert button.text() == "" and button.icon().isNull()
    qtbot.mouseMove(opening, QPoint(1, 100))
    qtbot.waitUntil(lambda: not button.underMouse())
    if state in {"hover", "pressed"}:
        qtbot.mouseMove(button, QPoint(14, 14))
        qtbot.waitUntil(button.underMouse)
    if state == "pressed":
        qtbot.mousePress(button, Qt.MouseButton.LeftButton)
        assert button.isDown()
    if state == "checked":
        button.setCheckable(True)
        button.setChecked(True)
    if state == "focus":
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        opening.activateWindow()
        button.setFocus()
        qtbot.waitUntil(button.hasFocus)
    image = button.grab().toImage()
    scale = image.devicePixelRatio()
    opaque = 0
    for x in range(image.width()):
        for y in range(image.height()):
            color = image.pixelColor(x, y)
            if color.alpha():
                assert max(color.red(), color.green(), color.blue()) - min(color.red(), color.green(), color.blue()) <= 1
                opaque += 1
            # The area between the outline and symbol must never be filled.
            lx, ly = x / scale, y / scale
            if 3 <= lx < 25 and (3 <= ly < 7 or 22 <= ly < 25):
                assert color.alpha() == 0
            if state == "idle" and not (4 <= lx < 24 and 7 <= ly < 21):
                assert color.alpha() == 0
    assert opaque > 40
    for x in (7, 14, 22):  # Sample interiors, not fractional-scale antialiased edges.
        assert image.pixelColor(int(x * scale), int(14 * scale)).alpha() == 255
    assert image.pixelColor(0, 0).alpha() == 0
    if state == "pressed":
        qtbot.mouseRelease(button, Qt.MouseButton.LeftButton)



def test_skip_does_not_inherit_narrative_text_selection(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolButton
    from anchor_desktop.widgets import TypewriterOpening, apply_dark_theme
    opening = TypewriterOpening("Selectable narrative " * 100, start=False)
    qtbot.addWidget(opening)
    apply_dark_theme(opening)
    opening.resize(440, 160)
    opening.show()
    opening.start()
    button = opening.skip_button
    assert isinstance(button, QToolButton)
    assert not button.isCheckable()
    assert not hasattr(button, "textInteractionFlags")
    assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
    before = button.grab().toImage()
    opening.text_label.setSelection(0, 2)
    assert opening.text_label.selectedText() == opening.text_label.text()[:2]
    assert button.grab().toImage() == before
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert opening.text_label.text() == opening._text
    assert button.isHidden()
    opening.text_label.setSelection(0, 10)
    assert opening.text_label.selectedText() == opening._text[:10]
    assert opening.text_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_custom_skip_click_finishes_once(qtbot):
    from PySide6.QtCore import Qt
    from anchor_desktop.widgets import TypewriterOpening
    opening = TypewriterOpening("Remaining narrative " * 100)
    qtbot.addWidget(opening)
    opening.show()
    finished, requested = [], []
    opening.finished.connect(lambda: finished.append(True))
    opening.skip_requested.connect(lambda: requested.append(True))
    qtbot.mouseClick(opening.skip_button, Qt.MouseButton.LeftButton)
    opening.finish()
    assert finished == requested == [True]
    assert opening.text_label.text() == opening._text
    assert not opening.timer.isActive()
    assert opening.skip_button.isHidden()
