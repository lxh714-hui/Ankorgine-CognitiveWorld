"""Local CLI host key provisioning; no Bundle, signature or Runtime changes.

POSIX file keys rely on filesystem permissions, not encryption at rest. Same-user
malicious code remains outside this boundary. Existing history is never rekeyed.
"""
from contextlib import contextmanager
import base64
import json
import os
from pathlib import Path
import secrets
import stat
import sys

from cognitive_world.core.persistence import HmacPersistenceTrust, WindowsDpapiPersistenceTrust


@contextmanager
def _directory(path, *, create=False):
    path = Path(os.path.abspath(path))
    if os.name != "posix":
        # Used by isolated adapter tests on Windows; the CLI selects DPAPI there.
        if create: path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink(): raise PermissionError("symlink trust directory")
        if not path.is_dir(): raise FileNotFoundError("trust directory is unavailable")
        yield None
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            if create:
                try: os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError: pass
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise PermissionError("trust directory requires owner-only mode 0700")
        yield fd
    finally:
        os.close(fd)


class FileHmacTrust:
    """Explicit file provisioning around the existing raw HMAC implementation.

    Every sign/verify reopens the original root; missing/corrupt roots are never
    replaced. No rotation, migration or stronger crash guarantee is introduced.
    """
    def __init__(self, path):
        self.path = Path(os.path.abspath(path))

    @classmethod
    def initialize(cls, path):
        instance = cls(path)
        key = secrets.token_bytes(32)
        payload = json.dumps({"version": 1, "key": base64.b64encode(key).decode("ascii")}, sort_keys=True).encode()
        with _directory(instance.path.parent, create=True) as directory:
            if directory is None:
                fd = os.open(instance.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            else:
                # Publish only a fully written key; link never replaces a winner.
                temporary = ".new-key-" + secrets.token_hex(16)
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.link(temporary, instance.path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                    os.fsync(directory)
                finally:
                    os.unlink(temporary, dir_fd=directory)
        return cls.open(path)

    @classmethod
    def open(cls, path):
        instance = cls(path)
        instance._load()
        return instance

    def _load(self):
        with _directory(self.path.parent) as directory:
            if directory is None:
                if self.path.is_symlink(): raise PermissionError("symlink trust root")
                fd = os.open(self.path, os.O_RDONLY | os.O_BINARY)
            else:
                fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise PermissionError("regular single-link trust root required")
                if os.name == "posix" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
                    raise PermissionError("trust root requires owner-only mode 0600")
                raw = stream.read(1025)
        if len(raw) > 1024: raise ValueError("trust root exceeds size limit")
        def closed(pairs):
            result = {}
            for key, value in pairs:
                if key in result: raise ValueError("duplicate trust field")
                result[key] = value
            return result
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=closed)
        if type(record) is not dict or set(record) != {"version", "key"} or type(record["version"]) is not int or record["version"] != 1 or type(record["key"]) is not str:
            raise ValueError("invalid file trust root")
        key = base64.b64decode(record["key"], validate=True)
        if len(key) != 32 or base64.b64encode(key).decode("ascii") != record["key"]:
            raise ValueError("invalid file trust key")
        return HmacPersistenceTrust(key)

    def sign(self, purpose, payload):
        return self._load().sign(purpose, payload)

    def verify(self, purpose, payload, signature):
        try: return self._load().verify(purpose, payload, signature)
        except (OSError, ValueError, TypeError): return False


def open_demo_trust(save_root, *, platform=None, user_data=None):
    """Provision only for a new empty demo; restoring requires an existing root."""
    platform = sys.platform if platform is None else platform
    save_root = Path(save_root)
    if platform == "win32":
        path = save_root / "trust.json"  # Preserve existing Windows demo saves.
        backend = WindowsDpapiPersistenceTrust
    elif platform in ("linux", "darwin"):
        if user_data is None:
            user_data = (Path.home() / "Library" / "Application Support" / "CognitiveWorld"
                         if platform == "darwin" else Path.home() / ".local" / "share" / "CognitiveWorld")
        path = Path(user_data) / "social-room-hmac-v1.json"
        backend = FileHmacTrust
    else:
        raise OSError("unsupported demo trust platform")
    # lstat recognizes broken symlinks: they must fail validation, not initialize.
    try: path.lstat()
    except FileNotFoundError:
        if any(save_root.iterdir()):
            raise FileNotFoundError("existing demo data requires its original trust root; no replacement created") from None
        try: return backend.initialize(path)
        except FileExistsError: return backend.open(path)  # Concurrent initializer won.
    return backend.open(path)
