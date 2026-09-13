"""Upload storage and the pack result cache.

Uploads live in a temp directory with a time-to-live and no database behind
them. Pack results are memoised on a hash of (file bytes, library geometry,
parameters), so nudging a slider back to a value already tried returns the
previous answer immediately instead of repeating a multi-second pack.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

UPLOAD_TTL_SECONDS = 6 * 60 * 60
MAX_CACHE_ENTRIES = 64
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class UploadStore:
    """Temp-dir storage for uploaded panels, swept on a TTL."""

    def __init__(self, root: Path | None = None, ttl: int = UPLOAD_TTL_SECONDS) -> None:
        self._owns_root = root is None
        self.root = Path(root) if root else Path(tempfile.mkdtemp(prefix="vlada-uploads-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self._lock = threading.Lock()

    def save(self, data: bytes, filename: str) -> str:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("file is too large")
        file_id = uuid.uuid4().hex
        with self._lock:
            target = self.root / file_id
            target.mkdir(parents=True, exist_ok=True)
            (target / "panel.svg").write_bytes(data)
            (target / "meta.json").write_text(
                json.dumps({"filename": filename, "saved_at": time.time()}),
                encoding="utf-8",
            )
        self.sweep()
        return file_id

    def _dir(self, file_id: str) -> Path:
        # Reject anything that is not a plain hex id so a crafted id cannot
        # walk out of the upload root.
        if not file_id or not all(c in "0123456789abcdef" for c in file_id):
            raise KeyError(file_id)
        return self.root / file_id

    def load(self, file_id: str) -> tuple[str, str]:
        """Return (svg_text, original_filename)."""
        folder = self._dir(file_id)
        panel = folder / "panel.svg"
        if not panel.is_file():
            raise KeyError(file_id)
        filename = "panel.svg"
        meta = folder / "meta.json"
        if meta.is_file():
            try:
                filename = json.loads(meta.read_text(encoding="utf-8")).get(
                    "filename", filename)
            except (ValueError, OSError):
                pass
        return panel.read_text(encoding="utf-8", errors="replace"), filename

    def sweep(self) -> int:
        """Delete uploads past their TTL. Returns how many were removed."""
        cutoff = time.time() - self.ttl
        removed = 0
        with self._lock:
            if not self.root.is_dir():
                return 0
            for child in self.root.iterdir():
                if not child.is_dir():
                    continue
                try:
                    if child.stat().st_mtime < cutoff:
                        shutil.rmtree(child, ignore_errors=True)
                        removed += 1
                except OSError:
                    continue
        return removed

    def dispose(self) -> None:
        if self._owns_root:
            shutil.rmtree(self.root, ignore_errors=True)


class PackCache:
    """Bounded LRU of pack results, keyed by a hash of everything that matters."""

    def __init__(self, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        self._entries: OrderedDict[str, dict] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    @staticmethod
    def key(
        svg_text: str, library_id: str, library_fingerprint: str, payload: dict,
    ) -> str:
        digest = hashlib.sha256()
        digest.update(svg_text.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(library_id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(library_fingerprint.encode("utf-8"))
        digest.update(b"\x00")
        # sort_keys so an equivalent payload in a different order still hits.
        digest.update(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))
        return digest.hexdigest()

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
