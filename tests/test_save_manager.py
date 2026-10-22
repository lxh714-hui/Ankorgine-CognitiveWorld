from __future__ import annotations

import json
import gc
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
from threading import Thread
import weakref
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from cognitive_world.runtime.save_manager import SaveError, SaveKind, SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
from test_runtime_reconstruction import (
    FakeTrust, LocalRuntimeAssembler, RuntimeReconstructionError,
    _dependency_manifest, _signed_inputs,
)


def _manager_and_runtime(tmp_path, *, retention=2):
    trust, *_rest, runtime = _signed_inputs()
    agent = runtime.context.agent_registry.all_agents()[0]
    context = runtime.cognition_context_provider(agent)
    manager = SaveManager(
        tmp_path / "saves", trust=trust, automatic_retention=retention,
    )
    args = {
        "runtime": runtime,
        "cognition": context.cognition_container,
        "memory_store": context.memory_store,
        "agent_contexts": (context,),
    }
    return manager, runtime, trust, args


def test_runtime_capture_manual_load_and_stage_restore(tmp_path):
    manager, runtime, _trust, args = _manager_and_runtime(tmp_path)
    with runtime.write_fence.operation():
        saved = manager.create_manual_save(name="checkpoint", **args)

    assert saved.kind is SaveKind.MANUAL
    assert saved.timeline_id == "timeline-parent"
    assert saved.simulation_tick == 4
    assert saved.runtime_session_id == runtime.write_fence.session_id
    assert manager.verify_consistency()

    loaded = manager.load_verified(saved.save_id, timeline_id="timeline-parent")
    assert loaded.bundle_manifest.simulation_tick == 4
    assert len(loaded.expected_agents) == 1
    with pytest.raises(PermissionError, match="does not belong"):
        manager.load_verified(saved.save_id, timeline_id="other-timeline")

    staged = manager.stage_restore(
        saved.save_id, timeline_id="timeline-parent", active_runtime=runtime,
        assembler=LocalRuntimeAssembler(_trust), dependencies=_dependency_manifest(),
        new_timeline_id="restored-child",
    )
    assert staged.status == "staged_not_active"
    assert staged.timeline_id == "restored-child"
    assert staged.runtime.write_fence.frozen


def test_cold_resume_reuses_signed_timeline_without_an_active_parent(tmp_path):
    manager, original, trust, args = _manager_and_runtime(tmp_path)
    with original.write_fence.operation():
        saved = manager.create_manual_save(**args)
    original.freeze_writes()
    reopened = SaveManager(manager.root, trust=trust)
    staged = reopened.stage_cold_resume(
        saved.save_id, timeline_id=saved.timeline_id,
        assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
    )
    assert staged.runtime.context.event_history.timeline_id == saved.timeline_id
    assert staged.runtime.context.event_history is not original.context.event_history
    assert staged.runtime.write_fence.frozen
    slot = ColdRuntimePublisher().activate(staged)
    resumed = slot.current
    assert resumed.running
    assert resumed.context.event_history.timeline_id == saved.timeline_id
    assert resumed.write_fence.session_id != saved.runtime_session_id
    assert resumed.write_fence.restore_generation > saved.restore_generation
    with resumed.write_fence.operation():
        resumed.context.event_history.verify_persisted_lineage(
            codec=reopened.codec, trust=trust,
        )


def test_automatic_retention_never_removes_manual_and_quick_is_separate(tmp_path):
    manager, runtime, _trust, args = _manager_and_runtime(tmp_path, retention=1)
    with runtime.write_fence.operation():
        manual = manager.create_manual_save(**args)
        first_auto = manager.create_automatic(**args)
        second_auto = manager.create_automatic(**args)
        quick_a = manager.create_quick_save(**args)
        quick_b = manager.create_quick_save(**args)

    records = manager.list_saves(timeline_id="timeline-parent")
    by_kind = {kind: [item for item in records if item.kind is kind]
               for kind in SaveKind}
    assert [item.save_id for item in by_kind[SaveKind.MANUAL]] == [manual.save_id]
    assert [item.save_id for item in by_kind[SaveKind.AUTOMATIC]] == [second_auto.save_id]
    assert [item.save_id for item in by_kind[SaveKind.QUICK]] == [quick_b.save_id]
    assert first_auto.save_id not in {item.save_id for item in records}
    assert quick_a.save_id == quick_b.save_id
    with pytest.raises(PermissionError):
        manager.delete_manual_save(second_auto.save_id)
    manager.delete_manual_save(manual.save_id)
    with pytest.raises(KeyError):
        manager.load_verified(manual.save_id, timeline_id="timeline-parent")


def test_content_addressed_resources_shared_until_last_save_reference(tmp_path):
    manager, runtime, _trust, args = _manager_and_runtime(tmp_path)
    with runtime.write_fence.operation():
        one = manager.create_manual_save(**args)
        two = manager.create_manual_save(**args)
    assert set(one.resource_ids) == set(two.resource_ids)
    counts = manager.verify_consistency()
    assert all(value == 2 for value in counts.values())
    manager.delete_manual_save(one.save_id)
    assert manager.verify_consistency()
    assert manager.load_verified(two.save_id, timeline_id=two.timeline_id)
    manager.delete_manual_save(two.save_id)
    assert manager.verify_consistency() == {}


def test_catalog_tampering_and_blob_tampering_fail_closed(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    with runtime.write_fence.operation():
        saved = manager.create_manual_save(**args)
    envelope = json.loads(manager.catalog_path.read_text("utf-8"))
    envelope["body"]["saves"][saved.save_id]["timeline_id"] = "forged"
    manager.catalog_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(PermissionError, match="catalog signature"):
        manager.list_saves()

    # A fresh manager over a valid catalog catches resource corruption by digest.
    manager2, runtime2, _trust2, args2 = _manager_and_runtime(tmp_path / "other")
    with runtime2.write_fence.operation():
        saved2 = manager2.create_manual_save(**args2)
    blob = manager2._blob_path(saved2.resource_ids[0])
    blob.write_bytes(blob.read_bytes() + b"tamper")
    with pytest.raises(PermissionError, match="digest mismatch"):
        manager2.load_verified(saved2.save_id, timeline_id=saved2.timeline_id)


def test_replace_failure_preserves_previous_manual_slot(tmp_path):
    manager, runtime, _trust, args = _manager_and_runtime(tmp_path)
    with runtime.write_fence.operation():
        saved = manager.create_manual_save(name="stable", **args)
    bad = dict(args)
    bad["agent_contexts"] = (object(),)
    with runtime.write_fence.operation():
        with pytest.raises((TypeError, ValueError, PermissionError)):
            manager.replace_manual_save(saved.save_id, **bad)
    assert manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert manager.list_saves()[0].save_id == saved.save_id


def test_child_save_retains_and_resolves_parent_checkpoint_after_parent_slot_delete(tmp_path):
    manager, root_runtime, trust, args = _manager_and_runtime(tmp_path)
    with root_runtime.write_fence.operation():
        parent_save = manager.create_manual_save(**args)
    staged = manager.stage_restore(
        parent_save.save_id, timeline_id=parent_save.timeline_id,
        active_runtime=root_runtime, assembler=LocalRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="child-timeline",
    )
    manager.delete_manual_save(parent_save.save_id)
    slot = ActiveRuntimeSlot(root_runtime)
    RestoreCoordinator(slot).activate(staged)
    child_runtime = slot.current
    child_agent = child_runtime.context.agent_registry.all_agents()[0]
    child_context = child_runtime.cognition_context_provider(child_agent)
    child_args = {
        "runtime": child_runtime,
        "cognition": child_context.cognition_container,
        "memory_store": child_context.memory_store,
        "agent_contexts": (child_context,),
    }
    with child_runtime.write_fence.operation():
        child_save = manager.create_manual_save(**child_args)
    assert child_save.parent_timeline_id == parent_save.timeline_id
    assert parent_save.snapshot_id in child_save.resource_ids

    assert manager.load_verified(child_save.save_id, timeline_id="child-timeline")
    assert manager.verify_consistency()


def test_other_manager_cannot_collect_staged_runtime_checkpoint(tmp_path):
    manager, parent_runtime, trust, args = _manager_and_runtime(tmp_path)
    parent_save = manager.create_manual_save(**args)
    staged = manager.stage_restore(
        parent_save.save_id, timeline_id=parent_save.timeline_id,
        active_runtime=parent_runtime, assembler=LocalRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="child-with-lease",
    )
    other_manager = SaveManager(manager.root, trust=trust)
    other_manager.delete_manual_save(parent_save.save_id)
    other_manager.collect_garbage()
    assert set(parent_save.resource_ids).issubset(
        {"sha256:" + path.stem for path in other_manager.resources.glob("*.blob")}
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(parent_runtime)).activate(staged)
    agent = child.context.agent_registry.all_agents()[0]
    context = child.cognition_context_provider(agent)
    child_save = other_manager.create_manual_save(
        runtime=child, cognition=context.cognition_container,
        memory_store=context.memory_store, agent_contexts=(context,),
    )
    assert other_manager.load_verified(child_save.save_id, timeline_id="child-with-lease")


def test_other_process_cannot_collect_staged_runtime_checkpoint(tmp_path):
    manager, parent_runtime, trust, args = _manager_and_runtime(tmp_path)
    parent_save = manager.create_manual_save(**args)
    staged = manager.stage_restore(
        parent_save.save_id, timeline_id=parent_save.timeline_id,
        active_runtime=parent_runtime, assembler=LocalRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="child-cross-process",
    )
    code = (
        "import sys; from cognitive_world.runtime.save_manager import SaveManager; "
        "from test_runtime_reconstruction import FakeTrust; "
        "m = SaveManager(sys.argv[1], trust=FakeTrust()); "
        "m.delete_manual_save(sys.argv[2]); m.collect_garbage()"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((
        str(Path(__file__).resolve().parents[1] / "src"),
        str(Path(__file__).resolve().parent), env.get("PYTHONPATH", ""),
    ))
    result = subprocess.run(
        [sys.executable, "-c", code, str(manager.root), parent_save.save_id],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert set(parent_save.resource_ids).issubset({
        "sha256:" + path.stem for path in manager.resources.glob("*.blob")
    })
    child = RestoreCoordinator(ActiveRuntimeSlot(parent_runtime)).activate(staged)
    agent = child.context.agent_registry.all_agents()[0]
    context = child.cognition_context_provider(agent)
    child_save = manager.create_manual_save(
        runtime=child, cognition=context.cognition_container,
        memory_store=context.memory_store, agent_contexts=(context,),
    )
    assert parent_save.snapshot_id in child_save.resource_ids
    assert manager.load_verified(child_save.save_id, timeline_id="child-cross-process")


def _child_line_reader(process):
    lines = Queue()

    def read_lines():
        for line in process.stdout:
            lines.put(line.rstrip("\r\n"))
        try:
            error_output = process.stderr.read()
        except ValueError:
            error_output = "child stderr was already closed"
        lines.put(("__EOF__", error_output))

    Thread(target=read_lines, daemon=True).start()
    return lines


def _child_line(lines, expected_prefix, *, timeout=20):
    deadline = __import__("time").monotonic() + timeout
    while True:
        remaining = deadline - __import__("time").monotonic()
        if remaining <= 0:
            raise AssertionError(f"timed out waiting for child line {expected_prefix!r}")
        try:
            line = lines.get(timeout=remaining)
        except Empty:
            raise AssertionError(f"timed out waiting for child line {expected_prefix!r}") from None
        if isinstance(line, tuple) and line[0] == "__EOF__":
            raise AssertionError(
                f"child exited before emitting {expected_prefix!r}; stderr={line[1]}"
            )
        if line.startswith(expected_prefix):
            return line


def test_cross_process_stage_holds_catalog_lock_through_assembler_and_lease(tmp_path):
    """A deletion and reopen recovery wait until the staged Runtime is leased."""
    manager, parent_runtime, trust, args = _manager_and_runtime(tmp_path)
    parent_save = manager.create_manual_save(**args)
    transaction_id = "interrupted-before-stage"
    partial_stage = manager.staging / transaction_id
    partial_stage.mkdir()
    (partial_stage / "partial.tmp").write_bytes(b"partial")
    orphan_name = "b" * 64
    (manager.resources / f"{orphan_name}.blob").write_bytes(b"orphan")
    manager._append_journal({
        "transaction_id": transaction_id, "phase": "PREPARED",
        "save_id": "not-published", "operation": "create",
    })

    stage_code = r"""
import sys
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from test_runtime_reconstruction import FakeTrust, LocalRuntimeAssembler, _dependency_manifest, _signed_inputs
trust = FakeTrust()
manager = SaveManager(sys.argv[1], trust=trust)
active = _signed_inputs()[-1]
class GateAssembler(LocalRuntimeAssembler):
    def assemble(self, inputs):
        print('A_ASSEMBLER_ENTERED', flush=True)
        if sys.stdin.readline().strip() != 'CONTINUE':
            raise RuntimeError('stage gate was not released')
        return super().assemble(inputs)
staged = manager.stage_restore(sys.argv[2], timeline_id='timeline-parent',
    active_runtime=active, assembler=GateAssembler(trust),
    dependencies=_dependency_manifest(), new_timeline_id='stage-race-child')
print('A_STAGED', flush=True)
if sys.stdin.readline().strip() != 'ACTIVATE':
    raise RuntimeError('activation gate was not released')
child = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
child.context.event_history.verify_persisted_lineage(codec=manager.codec, trust=trust)
print('A_ACTIVATED', flush=True)
"""
    contender_code = r"""
import sys
from contextlib import contextmanager
from cognitive_world.runtime.save_manager import SaveManager
from test_runtime_reconstruction import FakeTrust
original_locked = SaveManager._locked
@contextmanager
def traced_locked(self):
    print('B_WAIT_LOCK', flush=True)
    with original_locked(self):
        print('B_GOT_LOCK', flush=True)
        yield
SaveManager._locked = traced_locked
print('B_ATTEMPTING_OPEN', flush=True)
manager = SaveManager(sys.argv[1], trust=FakeTrust())
print('B_OPENED', flush=True)
manager.delete_manual_save(sys.argv[2])
manager.collect_garbage()
print('B_DELETED_AND_COLLECTED', flush=True)
"""
    env = _save_worker_env()
    stage = subprocess.Popen(
        [sys.executable, "-u", "-c", stage_code, str(manager.root), parent_save.save_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    stage_lines = _child_line_reader(stage)
    contender = None
    contender_lines = None
    try:
        _child_line(stage_lines, "A_ASSEMBLER_ENTERED")
        contender = subprocess.Popen(
            [sys.executable, "-u", "-c", contender_code,
             str(manager.root), parent_save.save_id],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )
        contender_lines = _child_line_reader(contender)
        _child_line(contender_lines, "B_ATTEMPTING_OPEN")
        _child_line(contender_lines, "B_WAIT_LOCK")
        # The assembler gate remains closed; the competing process has entered
        # the catalog-lock acquisition path and cannot finish reopen recovery.
        with pytest.raises(Empty):
            contender_lines.get(timeout=0.25)
        stage.stdin.write("CONTINUE\n")
        stage.stdin.flush()
        _child_line(stage_lines, "A_STAGED")
        _child_line(contender_lines, "B_GOT_LOCK")
        _child_line(contender_lines, "B_OPENED")
        _child_line(contender_lines, "B_DELETED_AND_COLLECTED")
        assert contender.wait(timeout=20) == 0, contender.stderr.read()

        # The child has deleted the parent slot and run transaction recovery;
        # the staged Runtime lease keeps every inherited resource alive.
        current_resources = {f"sha256:{path.stem}" for path in manager.resources.glob("*.blob")}
        assert set(parent_save.resource_ids).issubset(current_resources)
        assert not partial_stage.exists()
        assert not (manager.resources / f"{orphan_name}.blob").exists()
        journal = manager.journal_path.read_text(encoding="utf-8")
        assert "ABORTED_RECOVERED" in journal and transaction_id in journal
        assert any(manager.leases.glob("*.json"))

        stage.stdin.write("ACTIVATE\n")
        stage.stdin.flush()
        _child_line(stage_lines, "A_ACTIVATED")
        assert stage.wait(timeout=20) == 0
        assert all(manager._blob_path(resource).exists() for resource in parent_save.resource_ids)
        assert set(manager.collect_garbage()) == set(parent_save.resource_ids)
        assert manager.verify_consistency() == {}
    finally:
        for process in (stage, contender):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=20)


def test_assembler_failure_does_not_release_other_runtime_lease(tmp_path):
    manager, active, trust, args = _manager_and_runtime(tmp_path)
    saved = manager.create_manual_save(**args)
    live_stage = manager.stage_restore(
        saved.save_id, timeline_id=saved.timeline_id, active_runtime=active,
        assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="valid-live-stage",
    )
    lease_count = len(tuple(manager.leases.glob("*.json")))

    class FailAfterAssembly(LocalRuntimeAssembler):
        def assemble(self, inputs):
            super().assemble(inputs)
            raise RuntimeError("injected host assembler failure")

    with pytest.raises(RuntimeReconstructionError, match="injected host assembler failure"):
        manager.stage_restore(
            saved.save_id, timeline_id=saved.timeline_id, active_runtime=active,
            assembler=FailAfterAssembly(trust), dependencies=_dependency_manifest(),
            new_timeline_id="failed-stage",
        )
    assert len(tuple(manager.leases.glob("*.json"))) == lease_count
    manager.delete_manual_save(saved.save_id)
    manager.collect_garbage()
    assert all(manager._blob_path(resource).exists() for resource in saved.resource_ids)

    live_ref = weakref.ref(live_stage.runtime)
    del live_stage
    gc.collect()
    assert live_ref() is None
    assert set(saved.resource_ids).issubset(set(manager.collect_garbage()))
    assert manager.verify_consistency() == {}


def test_process_exit_during_assembler_releases_catalog_lock_without_lease(tmp_path):
    manager, active, trust, args = _manager_and_runtime(tmp_path)
    saved = manager.create_manual_save(**args)
    code = r"""
import sys
from cognitive_world.runtime.save_manager import SaveManager
from test_runtime_reconstruction import FakeTrust, LocalRuntimeAssembler, _dependency_manifest, _signed_inputs
trust = FakeTrust()
manager = SaveManager(sys.argv[1], trust=trust)
class GateAssembler(LocalRuntimeAssembler):
    def assemble(self, inputs):
        print('ASSEMBLER_ENTERED', flush=True)
        sys.stdin.readline()
        return super().assemble(inputs)
manager.stage_restore(sys.argv[2], timeline_id='timeline-parent',
    active_runtime=_signed_inputs()[-1], assembler=GateAssembler(trust),
    dependencies=_dependency_manifest(), new_timeline_id='crashed-during-assembly')
"""
    holder = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(manager.root), saved.save_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=_save_worker_env(),
    )
    try:
        assert holder.stdout.readline().strip() == "ASSEMBLER_ENTERED"
        holder.kill()
        holder.communicate(timeout=20)
        manager.delete_manual_save(saved.save_id)
        manager.collect_garbage()
        assert all(not manager._blob_path(resource).exists() for resource in saved.resource_ids)
        assert tuple(manager.leases.glob("*.json")) == ()
        assert manager.verify_consistency() == {}
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate(timeout=20)


def test_cross_process_lease_release_and_crashed_holder_are_reclaimed(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    saved = manager.create_manual_save(**args)
    local_stage = manager.stage_restore(
        saved.save_id, timeline_id=saved.timeline_id, active_runtime=runtime,
        assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
        new_timeline_id="other-live-child",
    )
    code = """
import sys
from cognitive_world.runtime.save_manager import SaveManager
from test_runtime_reconstruction import FakeTrust, LocalRuntimeAssembler, _dependency_manifest, _signed_inputs
trust = FakeTrust()
manager = SaveManager(sys.argv[1], trust=trust)
staged = manager.stage_restore(sys.argv[2], timeline_id='timeline-parent',
    active_runtime=_signed_inputs()[-1], assembler=LocalRuntimeAssembler(trust),
    dependencies=_dependency_manifest(), new_timeline_id='leased-child')
print('READY', flush=True)
sys.stdin.readline()
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((
        str(Path(__file__).resolve().parents[1] / "src"),
        str(Path(__file__).resolve().parent), env.get("PYTHONPATH", ""),
    ))
    holder = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(manager.root), saved.save_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    try:
        assert holder.stdout.readline().strip() == "READY", holder.stderr.read()
        manager.delete_manual_save(saved.save_id)
        assert set(saved.resource_ids).issubset({
            "sha256:" + path.stem for path in manager.resources.glob("*.blob")
        })
        holder.kill()
        holder.communicate(timeout=20)
        assert manager.collect_garbage() == ()
        assert all(manager._blob_path(item).exists() for item in saved.resource_ids)
        local_ref = weakref.ref(local_stage.runtime)
        del local_stage
        gc.collect()
        assert local_ref() is None
        assert set(saved.resource_ids).issubset(set(manager.collect_garbage()))
        assert manager.verify_consistency() == {}
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate(timeout=20)


def test_released_runtime_lease_and_damaged_lease_fail_closed(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    saved = manager.create_manual_save(**args)
    staged = manager.stage_restore(
        saved.save_id, timeline_id=saved.timeline_id, active_runtime=runtime,
        assembler=LocalRuntimeAssembler(trust), dependencies=_dependency_manifest(),
    )
    manager.delete_manual_save(saved.save_id)
    lease_manifest = next(manager.leases.glob("*.json"))
    lease_manifest.write_text("damaged", encoding="utf-8")
    with pytest.raises(SaveError, match="lease"):
        manager.collect_garbage()
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys; from cognitive_world.runtime.save_manager import SaveManager; "
            "from test_runtime_reconstruction import FakeTrust; "
            "SaveManager(sys.argv[1], trust=FakeTrust()).collect_garbage()"
        ), str(manager.root)], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=20, env=_save_worker_env(),
    )
    assert result.returncode != 0 and "runtime lease" in result.stderr
    assert all(manager._blob_path(item).exists() for item in saved.resource_ids)
    # Repairing the test-only damage still does not release a live Runtime.
    # The signed record is recreated from the original bytes, not re-signed.
    # A separate clean manager below exercises normal released-lease cleanup.
    clean, active, clean_trust, clean_args = _manager_and_runtime(tmp_path / "clean")
    clean_save = clean.create_manual_save(**clean_args)
    pending = clean.stage_restore(
        clean_save.save_id, timeline_id=clean_save.timeline_id,
        active_runtime=active, assembler=LocalRuntimeAssembler(clean_trust),
        dependencies=_dependency_manifest(),
    )
    clean.delete_manual_save(clean_save.save_id)
    pending_ref = weakref.ref(pending.runtime)
    del pending
    gc.collect()
    assert pending_ref() is None
    assert set(clean_save.resource_ids).issubset(set(clean.collect_garbage()))
    assert clean.verify_consistency() == {}


def _save_worker_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((
        str(Path(__file__).resolve().parents[1] / "src"),
        str(Path(__file__).resolve().parent), env.get("PYTHONPATH", ""),
    ))
    return env


def test_two_processes_delete_distinct_slots_without_wrong_reclaim(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    first = manager.create_manual_save(**args)
    second = manager.create_manual_save(**args)
    code = (
        "import sys; from cognitive_world.runtime.save_manager import SaveManager; "
        "from test_runtime_reconstruction import FakeTrust; "
        "m = SaveManager(sys.argv[1], trust=FakeTrust()); "
        "print('READY', flush=True); sys.stdin.readline(); "
        "m.delete_manual_save(sys.argv[2]); print('DONE', flush=True)"
    )
    workers = [subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(manager.root), save.save_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=_save_worker_env(),
    ) for save in (first, second)]
    try:
        for worker in workers:
            assert worker.stdout.readline().strip() == "READY", worker.stderr.read()
        for worker in workers:
            worker.stdin.write("GO\n")
            worker.stdin.flush()
        for worker in workers:
            output, error = worker.communicate(timeout=20)
            assert worker.returncode == 0, error
            assert "DONE" in output
        assert manager.list_saves() == ()
        assert manager.verify_consistency() == {}
        assert not list(manager.resources.glob("*.blob"))
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=20)


def test_two_processes_create_and_replace_do_not_prune_new_dependencies(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    original = manager.create_manual_save(**args)
    code = """
import sys
from cognitive_world.runtime.save_manager import SaveManager
from test_runtime_reconstruction import FakeTrust, _signed_inputs
trust, *_, runtime = _signed_inputs()
manager = SaveManager(sys.argv[1], trust=trust)
agent = runtime.context.agent_registry.all_agents()[0]
context = runtime.cognition_context_provider(agent)
print('READY', flush=True)
sys.stdin.readline()
capture = dict(runtime=runtime, cognition=context.cognition_container,
    memory_store=context.memory_store, agent_contexts=(context,))
saved = manager.create_manual_save(**capture) if sys.argv[2] == 'create' else manager.replace_manual_save(sys.argv[3], **capture)
print(saved.save_id, flush=True)
"""
    workers = [subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(manager.root), operation, original.save_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=_save_worker_env(),
    ) for operation in ("create", "replace")]
    try:
        for worker in workers:
            assert worker.stdout.readline().strip() == "READY", worker.stderr.read()
        for worker in workers:
            worker.stdin.write("GO\n")
            worker.stdin.flush()
        ids = []
        for worker in workers:
            output, error = worker.communicate(timeout=20)
            assert worker.returncode == 0, error
            ids.append(output.strip())
        assert len(set(ids)) == 2 and original.save_id in ids
        assert {item.save_id for item in manager.list_saves()} == set(ids)
        assert all(value == 2 for value in manager.verify_consistency().values())
        for save in manager.list_saves():
            assert manager.load_verified(save.save_id, timeline_id=save.timeline_id)
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=20)


def test_interrupted_catalog_commit_and_other_process_gc_keep_published_resources(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    original = manager.create_manual_save(**args)
    crash_code = """
import os, sys
from cognitive_world.runtime.save_manager import SaveManager
from test_runtime_reconstruction import FakeTrust, _signed_inputs
trust, *_, runtime = _signed_inputs()
manager = SaveManager(sys.argv[1], trust=trust)
agent = runtime.context.agent_registry.all_agents()[0]
context = runtime.cognition_context_provider(agent)
original_append = manager._append_journal
def interrupted(record):
    if record.get('phase') == 'COMMITTED':
        os._exit(71)
    original_append(record)
manager._append_journal = interrupted
manager.create_manual_save(runtime=runtime, cognition=context.cognition_container,
    memory_store=context.memory_store, agent_contexts=(context,))
"""
    crashed = subprocess.run(
        [sys.executable, "-c", crash_code, str(manager.root)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=20, env=_save_worker_env(),
    )
    assert crashed.returncode == 71, crashed.stderr
    code = """
import sys
from cognitive_world.runtime.save_manager import SaveManager
from test_runtime_reconstruction import FakeTrust
print('READY', flush=True)
sys.stdin.readline()
manager = SaveManager(sys.argv[1], trust=FakeTrust())
if sys.argv[2] == 'gc': manager.collect_garbage()
print(len(manager.list_saves()), flush=True)
"""
    workers = [subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(manager.root), operation],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=_save_worker_env(),
    ) for operation in ("recover", "gc")]
    try:
        for worker in workers:
            assert worker.stdout.readline().strip() == "READY", worker.stderr.read()
        for worker in workers:
            worker.stdin.write("GO\n")
            worker.stdin.flush()
        for worker in workers:
            output, error = worker.communicate(timeout=20)
            assert worker.returncode == 0, error
            assert output.strip() == "2"
        saves = manager.list_saves()
        assert len(saves) == 2 and original.save_id in {item.save_id for item in saves}
        assert all(value == 2 for value in manager.verify_consistency().values())
        for save in saves:
            assert manager.load_verified(save.save_id, timeline_id=save.timeline_id)
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=20)


def test_catalog_commit_is_atomic_and_failed_replacement_keeps_old_slot(tmp_path, monkeypatch):
    manager, runtime, _trust, args = _manager_and_runtime(tmp_path)
    with runtime.write_fence.operation():
        saved = manager.create_manual_save(**args)
    with runtime.write_fence.operation():
        with runtime.write_fence.commit_scope():
            runtime.context.clock.advance(1)
    original_write = manager._write_catalog

    def fail_commit(body):
        if body.get("last_transaction_id") is not None:
            raise OSError("injected catalog publication failure")
        original_write(body)

    monkeypatch.setattr(manager, "_write_catalog", fail_commit)
    with runtime.write_fence.operation(), pytest.raises(OSError, match="injected"):
        manager.replace_manual_save(saved.save_id, **args)
    monkeypatch.setattr(manager, "_write_catalog", original_write)
    assert manager.list_saves()[0].save_id == saved.save_id
    assert manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    with pytest.raises(ValueError, match="unreferenced"):
        manager.verify_consistency()
    assert manager.collect_garbage()
    assert manager.verify_consistency()


def test_interrupted_prepare_is_reconciled_and_orphan_staging_is_removed(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    with runtime.write_fence.operation():
        saved = manager.create_manual_save(**args)
    transaction_id = "interrupted-transaction"
    stage = manager.staging / transaction_id
    stage.mkdir()
    (stage / "partial.tmp").write_bytes(b"partial")
    orphan_id = "sha256:" + "a" * 64
    (manager.resources / ("a" * 64 + ".blob")).write_bytes(b"orphan")
    manager._append_journal({"transaction_id": transaction_id, "phase": "PREPARED",
                             "save_id": "never-published", "operation": "create"})

    reopened = SaveManager(manager.root, trust=trust, automatic_retention=2)
    assert [item.save_id for item in reopened.list_saves()] == [saved.save_id]
    assert not stage.exists()
    assert not (reopened.resources / ("a" * 64 + ".blob")).exists()
    assert reopened.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert reopened.verify_consistency()


def test_concurrent_manager_instances_serialize_catalog_publication(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    second = SaveManager(manager.root, trust=trust, automatic_retention=2)
    start = Barrier(2)

    def create(target):
        start.wait()
        return target.create_manual_save(**args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(create, manager), pool.submit(create, second))
        saved = tuple(item.result(timeout=5) for item in futures)
    assert len({item.save_id for item in saved}) == 2
    assert len(manager.list_saves()) == 2
    assert manager.verify_consistency()


def test_garbage_collection_and_new_save_publication_share_catalog_boundary(tmp_path):
    manager, runtime, trust, args = _manager_and_runtime(tmp_path)
    other_manager = SaveManager(manager.root, trust=trust)
    first = manager.create_manual_save(**args)
    manager.delete_manual_save(first.save_id)
    start = Barrier(2)

    def create():
        start.wait()
        return manager.create_manual_save(**args)

    def collect():
        start.wait()
        return other_manager.collect_garbage()

    with ThreadPoolExecutor(max_workers=2) as pool:
        created = pool.submit(create)
        collected = pool.submit(collect)
        saved = created.result(timeout=5)
        collected.result(timeout=5)
    assert other_manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert other_manager.verify_consistency()


def test_save_capture_and_restore_freeze_share_the_runtime_fence(tmp_path, monkeypatch):
    manager, parent, trust, args = _manager_and_runtime(tmp_path)
    original = manager.create_manual_save(**args)
    staged = manager.stage_restore(
        original.save_id, timeline_id=original.timeline_id,
        active_runtime=parent, assembler=LocalRuntimeAssembler(trust),
        dependencies=_dependency_manifest(), new_timeline_id="capture-restore-child",
    )
    coordinator = RestoreCoordinator(ActiveRuntimeSlot(parent))
    entered, release = Event(), Event()
    export = parent.context.world_state.export_persisted_snapshot

    def blocked_export(**kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return export(**kwargs)

    monkeypatch.setattr(parent.context.world_state, "export_persisted_snapshot", blocked_export)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(manager.create_manual_save, **args)
        assert entered.wait(timeout=10)
        restoring = pool.submit(coordinator.activate, staged)
        try:
            release.set()
            saved = saving.result(timeout=10)
            child = restoring.result(timeout=10)
        finally:
            release.set()
    assert saved.timeline_id == original.timeline_id
    assert manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert child.context.event_history.timeline_id == "capture-restore-child"
    assert parent.write_fence.retired
