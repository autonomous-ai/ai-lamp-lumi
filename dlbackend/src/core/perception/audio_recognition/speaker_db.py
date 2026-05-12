from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

import numpy as np


class BaseSpeakerDB(ABC):
    """Base interface for speaker embedding storage.

    Any future backend (SQLite, Redis, remote API, etc.) should keep
    this behavior-compatible API so `AudioRecognizer` can swap storage
    without changing business logic.
    """

    @abstractmethod
    def get(self, name: str) -> Optional[np.ndarray]:
        """Return speaker embedding by name, or None if not found."""

    @abstractmethod
    def set(self, name: str, embedding: np.ndarray) -> None:
        """Create/update one speaker embedding."""

    @abstractmethod
    def delete(self, name: str) -> bool:
        """Delete speaker by name. Return True if existed."""

    @abstractmethod
    def exists(self, name: str) -> bool:
        """Return True if speaker exists."""

    @abstractmethod
    def clear(self) -> None:
        """Delete all speakers."""

    @abstractmethod
    def items(self) -> Iterable[tuple[str, np.ndarray]]:
        """Iterate over active (name, embedding)."""

    @abstractmethod
    def to_dict(self) -> Dict[str, np.ndarray]:
        """Return in-memory copy of all speakers."""

    @abstractmethod
    def __len__(self) -> int:
        """Return total number of speakers."""


class SpeakerDB(BaseSpeakerDB):
    """JSON-backed speaker embedding DB with auto-persistence.

    - Initializes storage file automatically if missing.
    - Persists on every write (`set/delete/clear`).
    - Stores per-speaker metadata:
      - embedding: float32 vector (as list in JSON)
      - status: active | deleted
      - created_at: ISO-8601 UTC timestamp
      - updated_at: ISO-8601 UTC timestamp
    - Delete operation is soft-delete (updates `status` only).
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._data: Dict[str, Dict[str, Any]] = {}
        self._initialize()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self._load()
        else:
            self._save()

    def _load(self) -> None:
        raw = self.db_path.read_text(encoding="utf-8").strip()
        if not raw:
            self._data = {}
            return
        payload = json.loads(raw)
        parsed: Dict[str, Dict[str, Any]] = {}
        for name, value in payload.items():
            # Backward compatibility: old format {name: [embedding]}
            if isinstance(value, list):
                now = self._now_iso()
                parsed[name] = {
                    "embedding": np.asarray(value, dtype=np.float32),
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                }
                continue

            embedding = np.asarray(value.get("embedding", []), dtype=np.float32)
            status = value.get("status", "active")
            created_at = value.get("created_at") or self._now_iso()
            updated_at = value.get("updated_at") or created_at
            parsed[name] = {
                "embedding": embedding,
                "status": status,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        self._data = parsed

    def _save(self) -> None:
        payload = {
            name: {
                "embedding": record["embedding"].astype(np.float32).tolist(),
                "status": record["status"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            }
            for name, record in self._data.items()
        }
        self.db_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
        )

    def get(self, name: str) -> Optional[np.ndarray]:
        record = self._data.get(name)
        if record is None or record.get("status") != "active":
            return None
        return np.asarray(record["embedding"], dtype=np.float32).copy()

    def set(self, name: str, embedding: np.ndarray) -> None:
        now = self._now_iso()
        old = self._data.get(name)
        created_at = now if old is None else old.get("created_at", now)
        self._data[name] = {
            "embedding": np.asarray(embedding, dtype=np.float32).copy(),
            "status": "active",
            "created_at": created_at,
            "updated_at": now,
        }
        self._save()

    def delete(self, name: str) -> bool:
        record = self._data.get(name)
        if record is None:
            return False
        if record.get("status") == "deleted":
            return False
        record["status"] = "deleted"
        record["updated_at"] = self._now_iso()
        self._save()
        return True

    def exists(self, name: str) -> bool:
        record = self._data.get(name)
        return bool(record is not None and record.get("status") == "active")

    def clear(self) -> None:
        now = self._now_iso()
        for record in self._data.values():
            record["status"] = "deleted"
            record["updated_at"] = now
        self._save()

    def items(self) -> Iterable[tuple[str, np.ndarray]]:
        for name, record in self._data.items():
            if record.get("status") != "active":
                continue
            emb = np.asarray(record["embedding"], dtype=np.float32)
            yield name, emb.copy()

    def to_dict(self) -> Dict[str, np.ndarray]:
        return {name: emb for name, emb in self.items()}

    def get_record(self, name: str) -> Optional[Dict[str, Any]]:
        """Return full record (including metadata/status) for one speaker."""
        record = self._data.get(name)
        if record is None:
            return None
        return {
            "embedding": np.asarray(record["embedding"], dtype=np.float32).copy(),
            "status": record["status"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return sum(1 for _ in self.items())
