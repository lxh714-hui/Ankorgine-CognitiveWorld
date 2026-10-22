"""Cold resume acceptance in two distinct Python interpreter processes."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


_ROOT = Path(__file__).parents[1]
_WORLDS = _ROOT / "src" / "anchor_desktop" / "worlds"
_WORKER = r'''
import json
import os
import sys
from pathlib import Path

from anchor_desktop.host import start_new_world, resume_saved_world
from anchor_desktop.world_packages import WorldPackageCatalog
from cognitive_world.content.persistence import scenario_snapshot_codec
from cognitive_world.core.persistence import HmacPersistenceTrust, WindowsDpapiPersistenceTrust
from cognitive_world.player.input_understanding import (
    InputUnderstandingStatus, PlayerInputAssessment, PlayerInputRequest,
)
from cognitive_world.runtime.save_manager import SaveManager

class Interpreter:
    def understand(self, request, *, authorized_targets):
        target = next(target for target in authorized_targets if "door" in target)
        return PlayerInputAssessment(InputUnderstandingStatus.ACTION,
                                     intent="open the observed door", method="push the door",
                                     target_ref=target)

mode, root, worlds, world_id, trust_mode, *rest = sys.argv[1:]
if trust_mode == "dpapi":
    key_file = Path(root) / "protected-keys.json"
    trust = (WindowsDpapiPersistenceTrust.initialize(key_file) if mode == "save"
             else WindowsDpapiPersistenceTrust.open(key_file))
else:
    trust = HmacPersistenceTrust(b"independent-process-cold-key" * 4)
manager = SaveManager(Path(root) / world_id, trust=trust, codec=scenario_snapshot_codec())
package = WorldPackageCatalog(Path(worlds)).package(world_id)
if mode == "save":
    session = start_new_world(package, trust=trust, input_understanding_provider=Interpreter())
    try:
        saved = manager.create_manual_save(runtime=session.runtime,
            cognition=session.cognition, memory_store=session.memory_store,
            agent_contexts=session.agent_contexts)
        print(json.dumps({"pid": os.getpid(), "save_id": saved.save_id,
                          "timeline_id": saved.timeline_id,
                          "event_ids": [event.id for event in session.runtime.context.event_history.get_events()]}))
    finally:
        session.close()
elif mode == "resume":
    save_id, timeline_id = rest
    session = resume_saved_world(package, manager=manager, save_id=save_id,
                                 timeline_id=timeline_id, trust=trust,
                                 input_understanding_provider=Interpreter())
    try:
        binding = session.runtime.context.player_session
        before = [event.id for event in session.runtime.context.event_history.get_events()]
        request = PlayerInputRequest("after-process-exit", binding.session_id,
                                     world_id, "Open the observed door.")
        handle = session.player_tasks.submit_input(request)
        result = session.player_tasks.completion(handle).result(timeout=5)
        assert result.outcome_status == "resolved"
        after = [event.id for event in session.runtime.context.event_history.get_events()]
        assert len(after) == len(before) + 1
        continued = manager.create_manual_save(runtime=session.runtime,
            cognition=session.cognition, memory_store=session.memory_store,
            agent_contexts=session.agent_contexts)
        manager.load_verified(continued.save_id, timeline_id=timeline_id)
        print(json.dumps({"pid": os.getpid(), "timeline_id": timeline_id,
                          "before": before, "after": after,
                          "continued_save_id": continued.save_id}))
    finally:
        session.close()
else:
    raise AssertionError("invalid worker mode")
'''


def _run(mode, root, world_id, *extra, trust_mode="hmac"):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", _WORKER, mode, str(root), str(_WORLDS), world_id,
         trust_mode, *extra],
        cwd=_ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_save_exit_new_process_resume_and_continue_original_timeline(world_id, tmp_path):
    saved = _run("save", tmp_path, world_id)
    resumed = _run("resume", tmp_path, world_id, saved["save_id"], saved["timeline_id"])
    assert saved["pid"] != resumed["pid"]
    assert resumed["timeline_id"] == saved["timeline_id"]
    assert resumed["before"][:len(saved["event_ids"])] == saved["event_ids"]
    assert resumed["after"][:len(saved["event_ids"])] == saved["event_ids"]
    assert resumed["continued_save_id"] != saved["save_id"]


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is available on Windows only")
def test_dpapi_save_exit_new_process_resume_and_continue(tmp_path):
    world_id = "rain-harbor"
    saved = _run("save", tmp_path, world_id, trust_mode="dpapi")
    resumed = _run("resume", tmp_path, world_id, saved["save_id"],
                   saved["timeline_id"], trust_mode="dpapi")
    assert saved["pid"] != resumed["pid"]
    assert resumed["before"][:len(saved["event_ids"])] == saved["event_ids"]
    assert resumed["continued_save_id"] != saved["save_id"]
