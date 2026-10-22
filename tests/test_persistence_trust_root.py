import base64
import json
import os
import shutil
import subprocess
import sys

import pytest

from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")


def test_dpapi_root_requires_explicit_initialization_and_survives_new_process(tmp_path):
    path = tmp_path / "persistence-trust.json"
    with pytest.raises(FileNotFoundError):
        WindowsDpapiPersistenceTrust.open(path)

    signer = WindowsDpapiPersistenceTrust.initialize(path)
    signature = signer.sign("synthetic-test-purpose", b"non-sensitive synthetic payload")
    assert json.loads(signature)["algorithm"] == "hmac-sha256"
    assert json.loads(signature)["key_id"] == signer.active_key_id
    with pytest.raises(FileExistsError):
        WindowsDpapiPersistenceTrust.initialize(path)

    script = (
        "import base64,sys; "
        "from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust; "
        "trust=WindowsDpapiPersistenceTrust.open(sys.argv[1]); "
        "assert trust.verify('synthetic-test-purpose', b'non-sensitive synthetic payload', "
        "base64.b64decode(sys.argv[2]))"
    )
    env = os.environ.copy()
    src = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(path), base64.b64encode(signature).decode("ascii")],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, env=env,
    )
    assert completed.returncode == 0, completed.stderr


def test_dpapi_root_rotation_retains_old_signatures_then_revocation_fails_closed(tmp_path):
    path = tmp_path / "persistence-trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(path)
    old_signature = trust.sign("purpose", b"payload")
    old_id = trust.active_key_id

    new_id = trust.rotate()
    assert new_id != old_id
    assert trust.verify("purpose", b"payload", old_signature)
    new_signature = trust.sign("purpose", b"payload")
    assert trust.verify("purpose", b"payload", new_signature)

    trust.revoke(old_id)
    assert not trust.verify("purpose", b"payload", old_signature)
    assert trust.verify("purpose", b"payload", new_signature)


def test_dpapi_root_corruption_or_unknown_signature_algorithm_fails_closed(tmp_path):
    path = tmp_path / "persistence-trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(path)
    valid_signature = trust.sign("purpose", b"payload")
    signature = json.loads(valid_signature)
    signature["algorithm"] = "unknown-algorithm"
    assert not trust.verify("purpose", b"payload", json.dumps(signature).encode())
    signature = json.loads(trust.sign("purpose", b"payload"))
    signature["key_id"] = "unknown-key-id"
    assert not trust.verify("purpose", b"payload", json.dumps(signature).encode())
    signature = json.loads(trust.sign("purpose", b"payload"))
    signature["version"] = 99
    assert not trust.verify("purpose", b"payload", json.dumps(signature).encode())

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises((ValueError, PermissionError)):
        trust.sign("purpose", b"payload")
    assert not trust.verify("purpose", b"payload", valid_signature)


def test_replacing_key_ring_with_another_local_root_does_not_trust_old_signatures(tmp_path):
    first_path = tmp_path / "first" / "trust.json"
    second_path = tmp_path / "second" / "trust.json"
    first = WindowsDpapiPersistenceTrust.initialize(first_path)
    signature = first.sign("purpose", b"payload")
    WindowsDpapiPersistenceTrust.initialize(second_path)

    shutil.copyfile(second_path, first_path)
    replacement = WindowsDpapiPersistenceTrust.open(first_path)
    assert not replacement.verify("purpose", b"payload", signature)
