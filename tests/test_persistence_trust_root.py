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


@pytest.mark.parametrize("location", ["envelope", "ring"])
@pytest.mark.parametrize("version", [True, 1.0])
def test_dpapi_version_requires_an_integer_not_numeric_equality(tmp_path, location, version):
    path = tmp_path / "trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(path)
    signature = trust.sign("synthetic-purpose", b"synthetic-payload")
    if location == "envelope":
        envelope = json.loads(signature)
        envelope["version"] = version
        assert not trust.verify("synthetic-purpose", b"synthetic-payload", json.dumps(envelope).encode())
    else:
        ring = json.loads(path.read_bytes())
        ring["version"] = version
        path.write_text(json.dumps(ring), encoding="utf-8")
        original = path.read_bytes()
        with pytest.raises(ValueError): WindowsDpapiPersistenceTrust.open(path)
        with pytest.raises(ValueError): trust.sign("synthetic-purpose", b"synthetic-payload")
        assert not trust.verify("synthetic-purpose", b"synthetic-payload", signature)
        assert path.read_bytes() == original


@pytest.mark.parametrize("phase", ["protect", "unprotect"])
def test_dpapi_crypto_failure_does_not_rebuild_root(tmp_path, monkeypatch, phase):
    path = tmp_path / "trust.json"
    def fail(cls, value): raise OSError("injected DPAPI failure")
    if phase == "protect":
        monkeypatch.setattr(WindowsDpapiPersistenceTrust, "_protect", classmethod(fail))
        with pytest.raises(OSError): WindowsDpapiPersistenceTrust.initialize(path)
        assert not path.exists()
    else:
        trust = WindowsDpapiPersistenceTrust.initialize(path)
        signature = trust.sign("synthetic", b"payload")
        original = path.read_bytes()
        monkeypatch.setattr(WindowsDpapiPersistenceTrust, "_unprotect", classmethod(fail))
        with pytest.raises(OSError): WindowsDpapiPersistenceTrust.open(path)
        with pytest.raises(OSError): trust.sign("synthetic", b"payload")
        assert not trust.verify("synthetic", b"payload", signature)
        assert path.read_bytes() == original


def test_concurrent_dpapi_initialization_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / "trust.json"
    def initialize(_):
        try:
            WindowsDpapiPersistenceTrust.initialize(path)
            return True
        except FileExistsError: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(initialize, range(8))) == 1
    trust = WindowsDpapiPersistenceTrust.open(path)
    signature = trust.sign("synthetic", b"payload")
    assert WindowsDpapiPersistenceTrust.open(path).verify("synthetic", b"payload", signature)
