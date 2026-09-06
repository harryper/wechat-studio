"""Thread-safe and process-safe JSON file storage with atomic writes."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("wechat-studio")

_locks: Dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _get_rlock(path: str) -> threading.RLock:
    with _locks_guard:
        if path not in _locks:
            _locks[path] = threading.RLock()
        return _locks[path]


class AtomicStore:
    """JSON file store with thread-level RLock and process-level fcntl.flock."""

    def __init__(self, path: Path, default: Any = None):
        self._path = path
        self._lock_path = path.with_suffix(path.suffix + ".lock")
        self._default = default if default is not None else {}
        self._rlock = _get_rlock(str(path))

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> Any:
        with self._rlock:
            with self._flock_shared():
                return self._read_raw()

    def write(self, data: Any) -> None:
        with self._rlock:
            with self._flock_exclusive():
                self._write_raw(data)

    def update(self, fn) -> Any:
        """Read-modify-write under exclusive lock. fn receives current data, returns new data."""
        with self._rlock:
            with self._flock_exclusive():
                current = self._read_raw()
                result = fn(current)
                self._write_raw(result)
                return result

    def _read_raw(self) -> Any:
        if not self._path.exists():
            return (
                self._default() if callable(self._default) else
                json.loads(json.dumps(self._default))
            )
        try:
            text = self._path.read_text(encoding="utf-8")
            return json.loads(text)
        except json.JSONDecodeError as exc:
            log.error("JSON 文件损坏 %s: %s", self._path, exc)
            raise StorageError(f"本地存储文件损坏: {self._path.name}") from exc
        except OSError as exc:
            log.error("无法读取 %s: %s", self._path, exc)
            raise StorageError(f"本地存储文件不可读: {self._path.name}") from exc

    def _write_raw(self, data: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=f".{self._path.stem}.",
                suffix=".tmp",
            )
            raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            os.write(fd, raw.encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.replace(tmp_path, str(self._path))
            tmp_path = None
        except Exception:
            if fd is not None:
                os.close(fd)
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    class _flock_shared:
        """Context manager for shared (read) file lock."""
        def __init__(self_inner):
            self_inner.store = None
        def __init__(self_inner, store_instance=None):
            self_inner._store = store_instance
        def __enter__(self_inner):
            return self_inner
        def __exit__(self_inner, *args):
            pass

    def _flock_exclusive(self):
        return _FileLock(self._lock_path, fcntl.LOCK_EX)

    def _flock_shared(self):
        return _FileLock(self._lock_path, fcntl.LOCK_SH)


class _FileLock:
    def __init__(self, lock_path: Path, mode: int):
        self._lock_path = lock_path
        self._mode = mode
        self._fd: Optional[int] = None

    def __enter__(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(self._fd, self._mode)
        return self

    def __exit__(self, *args):
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


class StorageError(RuntimeError):
    """Raised when local storage operations fail."""
