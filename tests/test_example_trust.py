"""Example-host key lifecycle; real POSIX permissions run only on POSIX."""
import os
import subprocess
import sys
from pathlib import Path
import pytest
from cognitive_world.examples.persistence_trust import FileHmacTrust, open_demo_trust


def test_explicit_file_root_is_stable_and_never_replaced(tmp_path):
    path = tmp_path / "private" / "key.json"
    with pytest.raises(FileNotFoundError): FileHmacTrust.open(path)
    first = FileHmacTrust.initialize(path)
    original = path.read_bytes()
    signature = first.sign("test", b"data")
    assert FileHmacTrust.open(path).verify("test", b"data", signature)
    with pytest.raises(FileExistsError): FileHmacTrust.initialize(path)
    assert path.read_bytes() == original
    assert not first.verify("test", b"changed", signature)
    script = "from cognitive_world.examples.persistence_trust import FileHmacTrust; import sys; assert FileHmacTrust.open(sys.argv[1]).verify('test', b'data', bytes.fromhex(sys.argv[2]))"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-B", "-c", script, str(path), signature.hex()], env=env, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"version":2}', b'[]'])
def test_corrupt_root_is_not_rebuilt(tmp_path, raw):
    path = tmp_path / "private" / "key.json"
    FileHmacTrust.initialize(path)
    path.write_bytes(raw)
    with pytest.raises((ValueError, PermissionError)): FileHmacTrust.open(path)
    assert path.read_bytes() == raw


def test_missing_or_replaced_root_cannot_verify_original_history(tmp_path):
    a, b = tmp_path / "a" / "key.json", tmp_path / "b" / "key.json"
    trust = FileHmacTrust.initialize(a)
    signature = trust.sign("test", b"data")
    replacement = FileHmacTrust.initialize(b)
    a.write_bytes(b.read_bytes())
    assert not trust.verify("test", b"data", signature)
    a.unlink()
    with pytest.raises(FileNotFoundError): trust.sign("test", b"data")
    assert not trust.verify("test", b"data", signature)
    assert not a.exists()


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_posix_selector_reuses_user_root_and_refuses_missing_old_root(tmp_path, platform):
    root, user = tmp_path / "saves", tmp_path / "user"
    root.mkdir()
    first = open_demo_trust(root, platform=platform, user_data=user)
    signature = first.sign("test", b"data")
    assert open_demo_trust(root, platform=platform, user_data=user).verify("test", b"data", signature)
    (root / "existing-checkpoint").write_text("old history")
    key = user / "social-room-hmac-v1.json"
    key.unlink()
    with pytest.raises(FileNotFoundError): open_demo_trust(root, platform=platform, user_data=user)
    assert not key.exists()


def test_windows_selection_does_not_fall_back(tmp_path, monkeypatch):
    from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
    calls = []
    def fail(cls, path):
        calls.append(path)
        raise OSError("DPAPI unavailable")
    monkeypatch.setattr(WindowsDpapiPersistenceTrust, "initialize", classmethod(fail))
    with pytest.raises(OSError): open_demo_trust(tmp_path, platform="win32", user_data=tmp_path / "unused")
    assert calls == [tmp_path / "trust.json"]
    assert not (tmp_path / "unused").exists()


@pytest.mark.skipif(os.name != "posix", reason="requires actual POSIX permissions and descriptor operations")
@pytest.mark.parametrize("defect", ["file_mode", "dir_mode", "file_symlink", "dir_symlink", "hardlink"])
def test_posix_unsafe_root_fails_closed(tmp_path, defect):
    path = tmp_path / "private" / "key.json"
    FileHmacTrust.initialize(path)
    if defect == "file_mode": path.chmod(0o644)
    elif defect == "dir_mode": path.parent.chmod(0o755)
    elif defect == "file_symlink":
        target = tmp_path / "other"
        path.rename(target)
        path.symlink_to(target)
    elif defect == "dir_symlink":
        target = tmp_path / "other"
        path.parent.rename(target)
        path.parent.symlink_to(target, target_is_directory=True)
    else: os.link(path, tmp_path / "alias")
    with pytest.raises((OSError, ValueError, PermissionError)): FileHmacTrust.open(path)


@pytest.mark.parametrize("defect", ["corrupt", "missing", "replacement"])
def test_real_signed_room_cold_restore_with_file_root(tmp_path, defect):
    from cognitive_world.examples.social_room import SocialRoom, SocialRoomAssembler, dependency_manifest
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    path = tmp_path / "user" / "key.json"
    trust = FileHmacTrust.initialize(path)
    scene = SocialRoom(trust=trust)
    scene.advance(speak=True)
    scene.advance_receivers()
    manager = SaveManager(tmp_path / "saves", trust=trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    reopened = FileHmacTrust.open(path)
    manager2 = SaveManager(tmp_path / "saves", trust=reopened, codec=cognitive_snapshot_codec())
    assembler = SocialRoomAssembler(trust=reopened)
    ColdRuntimePublisher().activate(manager2.stage_cold_resume(saved.save_id, timeline_id=saved.timeline_id, assembler=assembler, dependencies=dependency_manifest()))
    assert assembler.scene.runtime.context.world_state.environment[scene.definition.door].is_open
    original = path.read_bytes()
    if defect == "missing": path.unlink()
    elif defect == "replacement":
        other = tmp_path / "other-user" / "key.json"
        FileHmacTrust.initialize(other)
        path.write_bytes(other.read_bytes())
    else: path.write_text("invalid")
    with pytest.raises((ValueError, PermissionError, RuntimeError)):
        manager2.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert not path.exists() if defect == "missing" else path.read_bytes() != original


def test_concurrent_explicit_initialization_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / "user" / "key.json"
    def initialize(_):
        try:
            FileHmacTrust.initialize(path)
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(initialize, range(8))) == 1
    assert FileHmacTrust.open(path).sign("test", b"data")


@pytest.mark.parametrize("raw", [b'{"version":1,"version":1,"key":"x"}',
    b'{"version":true,"key":"x"}', b'{"version":1,"key":"%%%"}',
    b'{"version":1,"key":"eA=="}', b'{"version":1,"key":"x","extra":1}', b'x' * 1025])
def test_closed_key_format_is_required(tmp_path, raw):
    path = tmp_path / "user" / "key.json"
    FileHmacTrust.initialize(path)
    path.write_bytes(raw)
    with pytest.raises(ValueError): FileHmacTrust.open(path)
    assert path.read_bytes() == raw


def test_default_platform_paths_are_user_scoped(tmp_path, monkeypatch):
    from cognitive_world.examples import persistence_trust as module
    monkeypatch.setattr(module.Path, "home", classmethod(lambda cls: tmp_path))
    calls = []
    monkeypatch.setattr(module.FileHmacTrust, "initialize", classmethod(lambda cls, path: calls.append(path)))
    saves = tmp_path / "save-root"
    saves.mkdir()
    open_demo_trust(saves, platform="linux")
    open_demo_trust(saves, platform="darwin")
    assert calls == [tmp_path / ".local/share/CognitiveWorld/social-room-hmac-v1.json",
                     tmp_path / "Library/Application Support/CognitiveWorld/social-room-hmac-v1.json"]
    assert all(saves not in path.parents for path in calls)


@pytest.mark.parametrize("method", ["initialize", "open"])
def test_windows_backend_error_never_selects_file_hmac(tmp_path, monkeypatch, method):
    from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
    if method == "open": (tmp_path / "trust.json").write_text("existing")
    def fail(cls, path): raise OSError("injected selected backend error")
    def forbidden(*args, **kwargs): pytest.fail("selected backend was replaced")
    monkeypatch.setattr(WindowsDpapiPersistenceTrust, method, classmethod(fail))
    monkeypatch.setattr(FileHmacTrust, "initialize", forbidden)
    monkeypatch.setattr(FileHmacTrust, "open", forbidden)
    with pytest.raises(OSError): open_demo_trust(tmp_path, platform="win32")


@pytest.mark.skipif(os.name != "posix", reason="real POSIX publication and directory fsync boundary")
@pytest.mark.parametrize("point", ["write", "flush", "file_fsync", "link", "directory_fsync", "cleanup_before", "cleanup_after", "final_open"])
def test_posix_initialization_failure_preserves_publication_identity(tmp_path, monkeypatch, point):
    import stat
    from cognitive_world.examples import persistence_trust as module
    path = tmp_path / "private" / "key.json"
    original_fsync, original_link, original_unlink = os.fsync, os.link, os.unlink
    original_fdopen = os.fdopen
    from contextlib import contextmanager
    from types import SimpleNamespace
    @contextmanager
    def fdopen(fd, mode):
        with original_fdopen(fd, mode) as stream:
            def write(data):
                if point == "write": raise OSError("injected write failure")
                return stream.write(data)
            def flush():
                if point == "flush": raise OSError("injected flush failure")
                return stream.flush()
            yield SimpleNamespace(write=write, flush=flush, fileno=stream.fileno)
    captured = []
    def fsync(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if (point == "directory_fsync" and directory) or (point == "file_fsync" and not directory):
            if path.exists(): captured.append(path.read_bytes())
            raise OSError("injected fsync failure")
        return original_fsync(fd)
    def link(*args, **kwargs):
        if point == "link": raise OSError("injected publication failure")
        return original_link(*args, **kwargs)
    def unlink(*args, **kwargs):
        if point == "cleanup_before":
            captured.append(path.read_bytes())
            raise OSError("injected pre-cleanup failure")
        result = original_unlink(*args, **kwargs)
        if point == "cleanup_after":
            captured.append(path.read_bytes())
            raise OSError("injected post-cleanup failure")
        return result
    def fail_open(cls, file):
        captured.append(path.read_bytes())
        raise OSError("injected final validation failure")
    with monkeypatch.context() as patch:
        if point in ("write", "flush"): patch.setattr(module.os, "fdopen", fdopen)
        patch.setattr(module.os, "fsync", fsync)
        patch.setattr(module.os, "link", link)
        patch.setattr(module.os, "unlink", unlink)
        if point == "final_open": patch.setattr(FileHmacTrust, "open", classmethod(fail_open))
        with pytest.raises(OSError): FileHmacTrust.initialize(path)
    published = point not in ("write", "flush", "file_fsync", "link")
    assert path.exists() is published
    if not published:
        assert not list(path.parent.iterdir())
        FileHmacTrust.initialize(path)
        assert FileHmacTrust.open(path).sign("synthetic", b"payload")
        return
    assert path.read_bytes() == captured[0]
    if point == "cleanup_before":
        assert path.stat().st_nlink == 2
        with pytest.raises(PermissionError): FileHmacTrust.open(path)
    else:
        assert path.stat().st_nlink == 1
        trust = FileHmacTrust.open(path)
        signature = trust.sign("synthetic", b"payload")
        assert FileHmacTrust.open(path).verify("synthetic", b"payload", signature)
    original = path.read_bytes()
    with pytest.raises(FileExistsError): FileHmacTrust.initialize(path)
    assert path.read_bytes() == original
