"""Deletion confirmations bind exact resources; presentation never mutates history."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from threading import Event
from hashlib import sha256

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QMessageBox, QApplication, QPushButton
from anchor_desktop.product_gateway import DesktopProductGateway
from anchor_desktop.app import MainWindow
from anchor_desktop.pages import ManagementPage, SaveListPage, confirm_resource_removal, ResourceRemovalDialog
from anchor_desktop.navigation import Route
from anchor_desktop.widgets import TypewriterOpening
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.runtime.save_manager import SaveManager, SaveError
from cognitive_world.content.persistence import scenario_snapshot_codec
from cognitive_world.player.input_understanding import InputUnderstandingStatus, PlayerInputAssessment

PACKAGES = Path(__file__).parents[1] / "src/anchor_desktop/worlds"
TRUST = HmacPersistenceTrust(b"management-test-key" * 4)


def host(tmp_path, provider=None, **kwargs):
    return DesktopProductGateway(PACKAGES, saves_root=tmp_path / "saves",
        trust_supplier=lambda: TRUST, input_understanding_provider=provider or object(), **kwargs)


def enter(gateway):
    gateway.begin_world("rain-harbor")
    gateway._entry.result(timeout=5)
    assert gateway.entry_status().state == "ready"
    return gateway._active


def save(gateway):
    gateway.begin_save()
    gateway._save.result(timeout=5)
    return gateway.save_status().save_id


def tree(root):
    return {str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()} if root.exists() else {}


def remove(gateway, preview):
    gateway.begin_removal(preview.token)
    return gateway._removal.result(timeout=5)


def test_bundled_removal_is_explicit_hiding_without_deleting_sources_or_saves(tmp_path):
    written=[]
    gateway=host(tmp_path, package_visibility_writer=written.append)
    try:
        enter(gateway); sid=save(gateway); gateway.leave_world()
        before_sources, before_saves=tree(PACKAGES), tree(tmp_path/"saves")
        cancelled=gateway.prepare_removal("package","rain-harbor")
        assert cancelled.target_id=="rain-harbor" and not cancelled.irreversible
        assert "1" in cancelled.retained and "不删除" in cancelled.removed
        gateway.cancel_removal(cancelled.token)
        assert not written and tree(tmp_path/"saves")==before_saves
        with pytest.raises(KeyError): gateway.begin_removal(cancelled.token)
        assert remove(gateway,gateway.prepare_removal("package","rain-harbor")).state=="completed"
        assert gateway.list_worlds()==()
        assert gateway.management_worlds()
        assert gateway.list_saves("rain-harbor")[0].id==sid
        assert tree(PACKAGES)==before_sources and tree(tmp_path/"saves")==before_saves
        assert written==[("rain-harbor",)]
        gateway.begin_restore("rain-harbor",sid)
        gateway._entry.result(timeout=5)
        assert gateway.entry_status().state=="ready"
        gateway.leave_world()
        gateway.restore_package_visibility("rain-harbor")
        assert gateway.list_worlds()[0].title=="灰域之外"
    finally: gateway.close()


def test_package_dependency_change_rejects_stale_confirmation(tmp_path):
    first,peer=host(tmp_path),host(tmp_path)
    try:
        preview=first.prepare_removal("package","rain-harbor")
        enter(peer); sid=save(peer);peer.leave_world()
        assert remove(first,preview).state=="failed"
        assert not first.package_hidden("rain-harbor")
        assert first.list_saves("rain-harbor")[0].id==sid
    finally: first.close();peer.close()


def test_live_instance_deletion_cancels_late_action_and_preserves_save(tmp_path):
    started,release=Event(),Event()
    class Blocked:
        def understand(self, request, *, authorized_targets):
            started.set();assert release.wait(5)
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION,"open","push the closed door",authorized_targets[0])
    gateway=host(tmp_path,Blocked())
    try:
        session=enter(gateway);sid=save(gateway)
        request_id=gateway.submit_input("open")
        handle=gateway._handles[request_id]
        assert started.wait(2)
        history=session.runtime.context.event_history.get_events()
        preview=gateway.prepare_removal("instance","rain-harbor")
        assert preview.target_id==session.runtime.context.event_history.timeline_id
        assert preview.irreversible and "1" in preview.retained
        assert remove(gateway,preview).state=="completed"
        assert gateway._active is None and session.runtime.write_fence.frozen
        release.set()
        session.player_tasks.completion(handle).result(timeout=4)
        assert session.runtime.context.event_history.get_events()==history
        assert gateway.list_saves("rain-harbor")[0].id==sid
    finally:release.set();gateway.close()


def test_old_instance_confirmation_cannot_close_a_new_instance(tmp_path):
    gateway=host(tmp_path)
    try:
        first=enter(gateway)
        preview=gateway.prepare_removal("instance","rain-harbor")
        gateway.cancel_removal(gateway.prepare_removal("instance","rain-harbor").token)
        assert gateway._active is first and not first.runtime.write_fence.frozen
        gateway.leave_world();second=enter(gateway)
        assert remove(gateway,preview).state=="failed"
        assert gateway._active is second and not second.runtime.write_fence.frozen
    finally:gateway.close()


def test_save_deletion_preserves_other_slot_resources_and_is_single_use(tmp_path):
    gateway=host(tmp_path)
    try:
        enter(gateway);one,two=save(gateway),save(gateway);gateway.leave_world()
        before=tree(tmp_path/"saves")
        cancelled=gateway.prepare_removal("save","rain-harbor",one)
        assert cancelled.irreversible and "1" in cancelled.retained
        gateway.cancel_removal(cancelled.token)
        assert tree(tmp_path/"saves")==before
        preview=gateway.prepare_removal("save","rain-harbor",one)
        assert remove(gateway,preview).state=="completed"
        with pytest.raises(KeyError):gateway.begin_removal(preview.token)
        assert [item.id for item in gateway.list_saves("rain-harbor")]==[two]
        manager=SaveManager(tmp_path/"saves/rain-harbor",trust=TRUST,codec=scenario_snapshot_codec())
        record=manager.list_saves()[0]
        manager.load_verified(two,timeline_id=record.timeline_id)
        assert all(manager._blob_path(ref).exists() for ref in record.resource_ids)
    finally:gateway.close()


def test_save_catalog_fingerprint_rechecked_inside_manager_lock(tmp_path):
    gateway=host(tmp_path)
    try:
        enter(gateway);one=save(gateway);gateway.leave_world()
        manager=SaveManager(tmp_path/"saves/rain-harbor",trust=TRUST,codec=scenario_snapshot_codec())
        fingerprint=manager.manual_deletion_fingerprint(one)
        enter(gateway);two=save(gateway);gateway.leave_world()
        with pytest.raises(SaveError,match="stale"):
            manager.delete_manual_save(one,expected_catalog_sha256=fingerprint)
        assert {item.id for item in gateway.list_saves("rain-harbor")}=={one,two}
    finally:gateway.close()


def test_active_save_or_busy_restore_cannot_be_deleted(tmp_path):
    gateway=host(tmp_path)
    try:
        enter(gateway);sid=save(gateway)
        with pytest.raises(RuntimeError,match="active"):
            gateway.prepare_removal("save","rain-harbor",sid)
        gateway.leave_world();gateway.begin_restore("rain-harbor",sid)
        with pytest.raises(RuntimeError,match="progress"):
            gateway.prepare_removal("save","rain-harbor",sid)
        gateway._entry.result(timeout=5)
    finally:gateway.close()


def test_cleanup_failure_is_reported_as_already_committed(tmp_path,monkeypatch):
    gateway=host(tmp_path)
    try:
        enter(gateway);one,two=save(gateway),save(gateway);gateway.leave_world()
        preview=gateway.prepare_removal("save","rain-harbor",one)
        original = SaveManager._collect_unreferenced
        def fail(manager, records):
            if one not in records:
                raise OSError("cleanup unavailable")
            return original(manager, records)
        monkeypatch.setattr(SaveManager,"_collect_unreferenced",fail)
        assert remove(gateway,preview).state=="completed_cleanup_pending"
        assert [item.id for item in gateway.list_saves("rain-harbor")]==[two]
    finally:gateway.close()


@pytest.mark.parametrize("operation",["package","instance","save"])
@pytest.mark.parametrize("confirm",[False,True])
def test_real_confirmation_dialog_names_exact_target_and_cancel_has_no_effect(qtbot,tmp_path,operation,confirm):
    gateway=host(tmp_path)
    page=ManagementPage(gateway,Route("management"))
    qtbot.addWidget(page)
    try:
        if operation in {"instance","save"}:enter(gateway)
        sid=save(gateway) if operation=="save" else None
        if operation=="save":gateway.leave_world()
        preview=gateway.prepare_removal(operation,"rain-harbor",sid)
        before=tree(tmp_path/"saves")
        def respond():
            dialog=QApplication.activeModalWidget()
            assert isinstance(dialog,ResourceRemovalDialog)
            assert dialog.details.itemAtPosition(1,1).widget().text()==preview.target_id
            assert dialog.details.itemAtPosition(3,0).widget().text()=="保留"
            assert ("不可撤销" in dialog.warning.text())==preview.irreversible
            button=next(item for item in dialog.actions.buttons() if item.text().startswith("确认") if confirm) if confirm else next(item for item in dialog.actions.buttons() if item.text()=="取消")
            button.click()
        QTimer.singleShot(0,respond)
        decision=confirm_resource_removal(page,preview)
        assert decision is confirm
        if confirm:
            assert remove(gateway,preview).state=="completed"
        else:
            gateway.cancel_removal(preview.token)
            assert tree(tmp_path/"saves")==before
            assert gateway.package_hidden("rain-harbor") is False
            if operation=="instance":assert gateway._active is not None
    finally:gateway.close()


def test_save_ui_refreshes_only_after_confirmed_completion(qtbot,tmp_path,monkeypatch):
    gateway=host(tmp_path)
    try:
        enter(gateway);one,two=save(gateway),save(gateway);gateway.leave_world()
        page=SaveListPage(gateway,Route("saves",{"world_id":"rain-harbor"}))
        qtbot.addWidget(page);page.list.setCurrentRow(0)
        selected=page.list.currentItem().data(Qt.ItemDataRole.UserRole)
        monkeypatch.setattr("anchor_desktop.pages.confirm_resource_removal",lambda *args:False)
        page.delete_selected()
        qtbot.waitUntil(lambda:not page._removing,timeout=5000)
        assert page.list.count()==2
        monkeypatch.setattr("anchor_desktop.pages.confirm_resource_removal",lambda *args:True)
        page.delete_selected();page.delete_selected()
        qtbot.waitUntil(lambda:page.list.count()==1,timeout=5000)
        assert page.list.item(0).data(Qt.ItemDataRole.UserRole)!=selected
    finally:gateway.close()


def stage(qtbot,tmp_path,provider=None):
    gateway=host(tmp_path,provider);enter(gateway)
    window=MainWindow(gateway);qtbot.addWidget(window);window.resize(600,540)
    window.navigate("stage",{"world_id":"rain-harbor"});window.show()
    return gateway,window,window.stack.currentWidget()


@pytest.mark.parametrize("skip", [False, True])
def test_worldbuilding_only_then_explicit_observation_and_authorized_interaction(qtbot, tmp_path, skip):
    from copy import deepcopy
    class Interpreter:
        kind = None
        def __init__(self):
            self.calls = []
        def understand_candidates(self, request, *, candidates):
            self.calls.append(candidates)
            if self.kind is None:
                return PlayerInputAssessment(InputUnderstandingStatus.OBSERVE, "inspect", "read current observation", None)
            candidate = next(item for item in candidates if item.kind == self.kind)
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION, "interact", candidate.supported_methods[0], candidate.handle)
    interpreter = Interpreter()
    gateway, window, page = stage(qtbot, tmp_path, interpreter)
    try:
        context = gateway._active.runtime.context
        player = context.player_session.player_id
        history = context.event_history.get_events()
        state = deepcopy((dict(context.world_state.environment), dict(context.world_state.locations)))
        expected = [item.content for item in gateway._active.output.messages_for(player)]
        visible = gateway._active.player_service._current_visible_environment()
        assert expected and visible
        assert page.opening._text == gateway.catalog.package("rain-harbor").opening
        assert not page.findChildren(QLabel, "actionEffectEntry")
        if skip:
            page.opening.skip_button.click()
        else:
            qtbot.waitUntil(lambda: page.opening._finished, timeout=15000)
        assert page.opening.text_label.text() == page.opening._text
        assert not page.findChildren(QLabel, "actionEffectEntry")
        assert not page._initial_queue
        assert not gateway.read_display()
        assert context.event_history.get_events() == history
        page.input_area.setPlainText("观察周围")
        page.submit.click()
        qtbot.waitUntil(page.submit.isEnabled, timeout=5000)
        request_id = page._pending_request
        assert gateway.input_status(request_id).outcome_status == "observed"
        labels = page.findChildren(QLabel, "actionEffectEntry")
        assert [item.text() for item in labels] == expected
        assert {item.kind for item in interpreter.calls[0]} >= {"door", "passage"}
        assert gateway._active.player_service._current_visible_environment() == visible
        assert context.event_history.get_events() == history
        assert (dict(context.world_state.environment), dict(context.world_state.locations)) == state
        deliveries = gateway._active.output.observation_results_for(player)
        assert len(deliveries) == 1 and deliveries[0].request_id == request_id
        assert [item.content for item in deliveries[0].batch.messages] == expected
        page._append_display(); page._reveal_initial(); page.opening.finish()
        assert [item.text() for item in page.findChildren(QLabel, "actionEffectEntry")] == expected
        assert len(gateway._active.output.observation_results_for(player)) == 1
        def edges():
            return [item.mapTo(page, item.contentsRect().topLeft()).x() for item in [page.opening.text_label] + labels]
        qtbot.waitUntil(lambda: len(set(edges())) == 1)
        assert all(item.styleSheet() == page.opening.text_label.styleSheet() for item in labels)
        actor = context.player_session.controlled_agent_id
        origin = context.world_state.locations[actor]
        for kind, text in (("door", "打开门"), ("passage", "走进去")):
            interpreter.kind = kind
            page.input_area.setPlainText(text)
            page.submit.click()
            qtbot.waitUntil(page.submit.isEnabled, timeout=5000)
            assert gateway.input_status(page._pending_request).outcome_status == "resolved"
        assert context.world_state.locations[actor] != origin
    finally:
        window.close()



def test_scroll_follows_new_messages_but_keeps_upward_reader_position(qtbot,tmp_path):
    gateway,window,page=stage(qtbot,tmp_path)
    try:
        page._reveal_initial()
        for i in range(25):page._append_history_line(str(i)+" 长消息"*35,"testHistory")
        bar=page.history_scroll.verticalScrollBar()
        qtbot.waitUntil(lambda:bar.maximum()>200 and bar.value()==bar.maximum())
        maximum=bar.maximum();page._append_history_line("最后一条"*70,"testHistory")
        qtbot.waitUntil(lambda:bar.maximum()>maximum and bar.value()==bar.maximum())
        bar.setValue(bar.maximum()//3);position=bar.value();maximum=bar.maximum()
        selected=page.findChildren(QLabel,"testHistory")[0];selected.setSelection(0,3)
        page._append_history_line("后台新消息"*60,"testHistory")
        qtbot.waitUntil(lambda:bar.maximum()>maximum)
        assert bar.value()==position and len(selected.selectedText())==3
        bar.setValue(bar.maximum());maximum=bar.maximum()
        page._append_history_line("继续跟随"*50,"testHistory")
        qtbot.waitUntil(lambda:bar.maximum()>maximum and bar.value()==bar.maximum())
    finally:window.close()


def test_wrapped_typewriter_final_line_stays_visible_without_polling(qtbot,tmp_path):
    gateway,window,page=stage(qtbot,tmp_path)
    try:
        page.opening._text="第一段。\n\n"+"换行很长的序章。"*120
        for _ in range(650):page.opening.advance()
        page._reveal_initial()
        bar=page.history_scroll.verticalScrollBar()
        qtbot.waitUntil(lambda:bar.maximum()>0 and bar.value()==bar.maximum())
        assert not page.opening.timer.isActive()
        assert "\n\n" in page.opening.text_label.text()
    finally:window.close()


def test_stale_async_preview_and_duplicate_pending_confirm_cannot_redirect(tmp_path):
    gateway=host(tmp_path)
    gate,release=Event(),Event()
    try:
        preview=gateway.prepare_removal("package","rain-harbor")
        def block():gate.set();assert release.wait(5)
        gateway._executor.submit(block)
        assert gate.wait(2)
        gateway.begin_removal(preview.token)
        with pytest.raises(RuntimeError,match="progress"):
            gateway.begin_removal(preview.token)
        with pytest.raises(RuntimeError,match="progress"):
            gateway.begin_world("rain-harbor")
        release.set()
        assert gateway._removal.result(timeout=5).state=="completed"
        assert gateway.removal_status("other-token").error_code=="operation_expired"
        assert gateway.package_hidden("rain-harbor")
    finally:release.set();gateway.close()


def test_package_settings_persist_only_visibility_without_creating_registry(qtbot,tmp_path):
    from PySide6.QtCore import QSettings
    from anchor_desktop.widgets import hidden_world_ids,save_hidden_world_ids
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/"settings"))
    save_hidden_world_ids(("rain-harbor",))
    assert hidden_world_ids()==("rain-harbor",)
    gateway=host(tmp_path,hidden_world_ids=hidden_world_ids(),package_visibility_writer=save_hidden_world_ids)
    try:
        assert gateway.list_worlds()==()
        assert gateway.catalog.package("rain-harbor").world_id=="rain-harbor"
        gateway.restore_package_visibility("rain-harbor")
        assert hidden_world_ids()==()
        assert not (tmp_path/"saves").exists()
    finally:gateway.close()


def test_hidden_package_card_refreshes_when_returning_from_management(qtbot,tmp_path):
    gateway=host(tmp_path);window=MainWindow(gateway);qtbot.addWidget(window)
    try:
        window.navigate("worlds",{})
        window.navigate("management",{})
        assert remove(gateway,gateway.prepare_removal("package","rain-harbor")).state=="completed"
        window.navigate("__back__",{})
        assert not [p for p in window.stack.currentWidget().findChildren(QPushButton) if p.text()=="查看世界  →"]
    finally:window.close()


def test_pending_save_blocks_management_without_removing_existing_slots(tmp_path,monkeypatch):
    gateway=host(tmp_path);started,release=Event(),Event()
    original=SaveManager.create_manual_save
    try:
        enter(gateway);sid=save(gateway)
        def blocked(manager,**kwargs):
            started.set();assert release.wait(5)
            return original(manager,**kwargs)
        monkeypatch.setattr(SaveManager,"create_manual_save",blocked)
        gateway.begin_save();assert started.wait(2)
        with pytest.raises(RuntimeError,match="progress"):
            gateway.prepare_removal("instance","rain-harbor")
        with pytest.raises(RuntimeError,match="progress"):
            gateway.prepare_removal("save","rain-harbor",sid)
        release.set();gateway._save.result(timeout=5)
        assert sid in {item.id for item in gateway.list_saves("rain-harbor")}
    finally:release.set();gateway.close()


def test_removal_dialog_wraps_long_details_and_escape_cancels(qtbot):
    from anchor_desktop.management import RemovalPreview
    from PySide6.QtCore import Qt
    preview = RemovalPreview("token", "save", "world-" * 40, "resource-" * 50,
        "存档名称" * 20, "删除此存档的目录记录。" * 20,
        "保留共享祖先与仍被引用的资源。" * 20, "清理失败时仍保留恢复维护信息。" * 20, True)
    dialog = ResourceRemovalDialog(None, preview)
    qtbot.addWidget(dialog)
    dialog.resize(390, 420)
    dialog.show()
    qtbot.waitUntil(dialog.isVisible)
    dialog.layout().activate()
    edges = []
    for row, expected in enumerate((preview.world_id, preview.target_id,
            preview.removed, preview.retained, preview.consequences)):
        value = dialog.details.itemAtPosition(row, 1).widget()
        assert value.text() == expected
        assert value.wordWrap()
        edges.append(value.x())
        assert value.x() + value.width() <= value.parentWidget().width()
        assert value.height() >= value.heightForWidth(value.width())
    assert len(set(edges)) == 1
    assert dialog.actions.geometry().bottom() < dialog.height()
    assert dialog.cancel.isDefault()
    assert not dialog.confirm.autoDefault()
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.result() == dialog.DialogCode.Rejected


def test_opening_and_later_observation_text_share_metrics(qtbot, tmp_path):
    gateway, window, page = stage(qtbot, tmp_path)
    try:
        page._reveal_initial()
        page._static_history_line("第一段。\n\n第二段。", "actionEffectEntry")
        text = page.findChildren(QLabel, "actionEffectEntry")[0]
        opening = page.opening.text_label
        assert text.styleSheet() == opening.styleSheet()
        assert text.contentsMargins() == opening.contentsMargins()
        assert text.font() == opening.font()
        assert text.alignment() == opening.alignment()
        assert text.text() == "第一段。\n\n第二段。"
        assert text.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    finally:
        window.close()


def test_restored_stage_does_not_replay_startup_scene_or_generate_observations(qtbot, tmp_path):
    gateway = host(tmp_path)
    window = MainWindow(gateway)
    qtbot.addWidget(window)
    try:
        enter(gateway)
        save_id = save(gateway)
        gateway.leave_world()
        gateway.begin_restore("rain-harbor", save_id)
        gateway._entry.result(timeout=5)
        assert gateway.entry_status().state == "ready"
        session = gateway._active
        before = session.runtime.context.event_history.get_events()
        visible = session.player_service._current_visible_environment()
        assert visible
        window.navigate("stage", {"world_id": "rain-harbor", "save_id": save_id})
        window.show()
        page = window.stack.currentWidget()
        assert page.opening is None
        assert not page.findChildren(QLabel, "actionEffectEntry")
        assert session.runtime.context.event_history.get_events() == before
        assert session.player_service._current_visible_environment() == visible
        assert gateway.read_display() == ()
    finally:
        window.close()


def test_management_does_not_advertise_unlisted_fixture_without_resources(tmp_path):
    gateway = host(tmp_path)
    try:
        assert [item.world_id for item in gateway.management_worlds()] == ["rain-harbor"]
        assert gateway.list_worlds()[0].title == "灰域之外"
        gateway.begin_world("clockwork-library")
        gateway._entry.result(timeout=5)
        assert gateway.entry_status().state == "ready"
        compatibility = next(item for item in gateway.management_worlds() if item.world_id == "clockwork-library")
        assert compatibility.title == "历史存档（兼容）"
        assert all(item.world_id != "clockwork-library" for item in gateway.list_worlds())
        gateway.leave_world()
        assert [item.world_id for item in gateway.management_worlds()] == ["rain-harbor"]
    finally:
        gateway.close()


def test_unverified_compatibility_catalog_keeps_its_recovery_entry(tmp_path):
    gateway = host(tmp_path)
    root = tmp_path / "saves" / "clockwork-library"
    root.mkdir(parents=True)
    (root / "catalog.json").write_text("not a valid signed catalog", encoding="utf-8")
    before = tree(root)
    try:
        assert "clockwork-library" in {item.world_id for item in gateway.management_worlds()}
        with pytest.raises((ValueError, SaveError)):
            gateway.list_saves("clockwork-library")
        assert tree(root) == before
        assert all(item.world_id != "clockwork-library" for item in gateway.list_worlds())
    finally:
        gateway.close()
