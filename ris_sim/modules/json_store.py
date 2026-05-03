"""Small JSON state helpers with atomic writes and advisory locking."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


@contextlib.contextmanager
def file_lock(path: str | os.PathLike[str]):
    """Cross-platform advisory lock using a sibling `.lock` file."""
    lock_path = Path(path).with_suffix(Path(path).suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_json(path: str | os.PathLike[str], default: Any | None = None) -> Any:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        if default is not None:
            return default
        raise


def write_json_atomic(path: str | os.PathLike[str], data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w") as tmp:
            json.dump(data, tmp, indent=4)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def update_json_file(
    path: str | os.PathLike[str],
    mutator: Callable[[Any], Any],
    *,
    default: Any | None = None,
) -> Any:
    with file_lock(path):
        data = load_json(path, default=default)
        updated = mutator(data)
        write_json_atomic(path, updated)
        return updated
