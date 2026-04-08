import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, override

import insightface
import lelamp.config as config
import numpy as np
import numpy.typing as npt

from .base import Perception

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

_NO_MATCH = -2.0  # sentinel score used when an embedding bank is empty

# Persisted owner photos (see save_photo / load_from_disk)
OWNER_PHOTOS_DIR = Path(config.OWNER_PHOTOS_DIR)
STRANGER_STATE_DIR = OWNER_PHOTOS_DIR / ".strangers"
STRANGER_STATE_DIR.mkdir(exist_ok=True, parents=True)
_STRANGER_STATS_FILE = OWNER_PHOTOS_DIR.parent / "stranger_stats.json"


class FaceRecognizer(Perception):
    """InsightFace-based face recognizer. Detects owners, friends, and strangers, fires presence events."""

    OWNER_PREFIX: str = "owner_"
    FRIEND_PREFIX: str = "friend_"
    STRANGER_PREFIX: str = "stranger_"
    KNOWN_ROLES: set[str] = {"owner", "friend"}

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        threshold: float = 0.4,
        negative_threshold: float | None = 0.1,
        model_name: str = "buffalo_sc",
        max_strangers: int = 50,
        strangers_forget_ts: float = config.FACE_STRANGER_FORGET_S,
        owners_forget_ts: float = config.FACE_OWNER_FORGET_S,
    ):
        super().__init__(send_event)
        self._cv2 = cv2
        self._on_motion = on_motion

        self.threshold = threshold
        self.negative_threshold = negative_threshold
        self.max_strangers = max_strangers
        self._stranger_counter = 0

        self._owners_forget_ts = owners_forget_ts
        self._strangers_forget_ts = strangers_forget_ts

        self._owners_last_seen: dict[str, float] = {}
        self._known_face_kinds: dict[str, str] = {}  # person_id → "owner"|"friend"
        self._strangers_last_seen: dict[str, float] = {}
        self._stranger_visit_counts: dict[str, dict] = self._load_stranger_stats()

        self._face_present = False
        self._faces_n = 0

        # Owner embeddings — populated by train(), cleared by reset_owners()
        self._owner_embeddings: np.ndarray | None = None
        self._owner_labels: np.ndarray | None = None

        # Stranger embeddings — accumulated at runtime, never cleared by reset_owners().
        # Rows are insertion-ordered; index 0 is always the oldest stranger.
        self._stranger_embeddings: np.ndarray | None = None
        self._stranger_labels: np.ndarray | None = None

        self.app: insightface.app.FaceAnalysis = insightface.app.FaceAnalysis(
            name=model_name
        )
        self.app.prepare(ctx_id=-1)

        self._start_watcher()

    def _start_watcher(self) -> None:
        """Poll OWNER_PHOTOS_DIR every 2s and reload embeddings when files change."""
        OWNER_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

        def _latest_mtime() -> float:
            try:
                return max(
                    (e.stat().st_mtime for e in OWNER_PHOTOS_DIR.rglob("*")),
                    default=0.0,
                )
            except OSError:
                return 0.0

        def _poll():
            last = _latest_mtime()
            while True:
                time.sleep(2)
                current = _latest_mtime()
                if current != last:
                    last = current
                    logger.info("Owner photos changed — reloading embeddings")
                    self.load_from_disk()

        t = threading.Thread(target=_poll, daemon=True, name="owner-photos-watcher")
        t.start()
        logger.info("Watching owner photos dir: %s", OWNER_PHOTOS_DIR)

    def train(
        self,
        images: list[npt.NDArray[np.uint8]],
        labels: list[int | str],
        role: str = "owner",
    ) -> None:
        prefix = self.FRIEND_PREFIX if role == "friend" else self.OWNER_PREFIX
        prefixed_labels = [prefix + str(lbl) for lbl in labels]
        new_embeddings = []
        new_labels = []
        for img, label in zip(images, prefixed_labels):
            results = self.app.get(img)
            for r in results:
                emb = r["embedding"]
                new_embeddings.append(emb / np.linalg.norm(emb))
                new_labels.append(label)

        if new_embeddings:
            stacked_e = np.stack(new_embeddings, axis=0)
            stacked_l = np.stack(new_labels, axis=0)
            self._owner_embeddings = (
                np.concatenate([self._owner_embeddings, stacked_e])
                if self._owner_embeddings is not None
                else stacked_e
            )
            self._owner_labels = (
                np.concatenate([self._owner_labels, stacked_l])
                if self._owner_labels is not None
                else stacked_l
            )
            logger.info(
                "Added %d owner faces — total owners: %d, total strangers: %d",
                len(new_embeddings),
                len(self._owner_embeddings),
                len(self._stranger_embeddings)
                if self._stranger_embeddings is not None
                else 0,
            )

    @staticmethod
    def normalize_label(label: str) -> str:
        """Lowercase folder-safe label (a-z0-9_-)."""
        s = label.strip().lower()
        s = re.sub(r"[^a-z0-9_-]+", "_", s)
        s = s.strip("_")
        return s[:64] if s else "owner"

    def _clear_owner_embeddings(self) -> None:
        self._owner_embeddings = None
        self._owner_labels = None

    @staticmethod
    def _read_role(person_dir: Path) -> str:
        """Read role from metadata.json in a person's photo folder. Default 'owner'."""
        meta_path = person_dir / "metadata.json"
        if meta_path.is_file():
            try:
                data = json.loads(meta_path.read_text())
                role = data.get("role", "owner")
                if role in FaceRecognizer.KNOWN_ROLES:
                    return role
            except (json.JSONDecodeError, OSError):
                pass
        return "owner"

    @staticmethod
    def _write_role(person_dir: Path, role: str) -> None:
        """Write role to metadata.json in a person's photo folder."""
        meta_path = person_dir / "metadata.json"
        meta_path.write_text(json.dumps({"role": role}))

    def save_photo(self, image_bytes: bytes, label: str, role: str = "owner") -> str:
        """Write JPEG bytes under OWNER_PHOTOS_DIR/{label}/ with a timestamp name."""
        norm = self.normalize_label(label)
        if role not in self.KNOWN_ROLES:
            role = "owner"
        dest_dir = OWNER_PHOTOS_DIR / norm
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Persist role metadata
        self._write_role(dest_dir, role)
        fname = f"{int(time.time() * 1000)}.jpg"
        path = dest_dir / fname
        path.write_bytes(image_bytes)
        return str(path)

    def load_from_disk(self) -> int:
        """Clear owner/friend embeddings and re-train from all JPEG/PNG images under OWNER_PHOTOS_DIR."""
        self._clear_owner_embeddings()
        if not OWNER_PHOTOS_DIR.is_dir():
            logger.info("No owner photos dir at %s — skipping", OWNER_PHOTOS_DIR)
            return 0

        _IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
        loaded_total = 0

        for person_dir in sorted(OWNER_PHOTOS_DIR.iterdir()):
            if not person_dir.is_dir():
                continue
            role = self._read_role(person_dir)
            images = []
            labels: list[str] = []
            for fname in sorted(person_dir.iterdir()):
                if fname.suffix.lower() not in _IMG_EXTS:
                    continue
                img = self._cv2.imread(str(fname))
                if img is None:
                    logger.warning("Failed to load image: %s", fname)
                    continue
                images.append(img)
                labels.append(person_dir.name)

            if images:
                self.train(images, labels, role=role)
                loaded_total += len(images)
                logger.info(
                    "Loaded %d image(s) for %s '%s'",
                    len(images),
                    role,
                    person_dir.name,
                )

        n_enrolled = self.owner_count()
        logger.info(
            "Load from disk done — %d image(s), %d enrolled person(s)",
            loaded_total,
            n_enrolled,
        )
        return n_enrolled

    def enroll_from_bytes(
        self, image_bytes: bytes, label: str, role: str = "owner"
    ) -> str:
        """Decode image, save as JPEG on disk, and append embeddings."""
        norm = self.normalize_label(label)
        if role not in self.KNOWN_ROLES:
            role = "owner"
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = self._cv2.imdecode(arr, self._cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("could not decode image")
        if not self.app.get(img):
            raise ValueError("no face detected in image")
        ok, buf = self._cv2.imencode(".jpg", img)
        if not ok:
            raise ValueError("could not encode image")
        path = self.save_photo(buf.tobytes(), norm, role=role)
        self.train([img], [norm], role=role)
        return path

    def remove_owner(self, label: str) -> bool:
        """Remove one owner's directory and re-load remaining owners from disk."""
        norm = self.normalize_label(label)
        owner_dir = OWNER_PHOTOS_DIR / norm
        if not owner_dir.is_dir():
            return False
        shutil.rmtree(owner_dir)
        self.load_from_disk()
        return True

    def owner_count(self) -> int:
        if self._owner_labels is None:
            return 0
        unique = set()
        for lbl in self._owner_labels:
            s = str(lbl)
            if s.startswith(self.FRIEND_PREFIX):
                unique.add(s.removeprefix(self.FRIEND_PREFIX))
            else:
                unique.add(s.removeprefix(self.OWNER_PREFIX))
        return len(unique)

    def owner_names(self) -> list[str]:
        if self._owner_labels is None:
            return []
        unique = set()
        for lbl in self._owner_labels:
            s = str(lbl)
            if s.startswith(self.FRIEND_PREFIX):
                unique.add(s.removeprefix(self.FRIEND_PREFIX))
            else:
                unique.add(s.removeprefix(self.OWNER_PREFIX))
        return sorted(unique)

    def enrolled_persons(self) -> list[dict]:
        """Return list of enrolled persons with name and role."""
        if not OWNER_PHOTOS_DIR.is_dir():
            return []
        persons = []
        for d in sorted(OWNER_PHOTOS_DIR.iterdir()):
            if not d.is_dir():
                continue
            role = self._read_role(d)
            persons.append({"label": d.name, "role": role})
        return persons

    def reset_owners(self) -> None:
        """Clear owner embeddings and delete all saved owner photos. Stranger bank is unchanged."""
        self._clear_owner_embeddings()
        if OWNER_PHOTOS_DIR.is_dir():
            for child in OWNER_PHOTOS_DIR.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
        logger.info("Owner embeddings cleared and owner photos removed")

    def _evict_oldest_strangers(self) -> None:
        if self._stranger_embeddings is None or self._stranger_labels is None:
            return
        count = len(self._stranger_embeddings)
        if count <= self.max_strangers:
            return
        drop = count - self.max_strangers
        logger.debug("Evicting %d oldest stranger(s)", drop)
        self._stranger_embeddings = self._stranger_embeddings[drop:]
        self._stranger_labels = self._stranger_labels[drop:]

    def _save_strangers_state(self):
        if self._stranger_embeddings is not None and self._stranger_labels is not None:
            try:
                np.save(STRANGER_STATE_DIR / "embeds.npy", self._stranger_embeddings)
                np.save(STRANGER_STATE_DIR / "labels.npy", self._stranger_labels)
                np.save(
                    STRANGER_STATE_DIR / "counter.npy", np.array(self._stranger_counter)
                )
                logger.debug("Saved strangers' state")
            except Exception as e:
                logger.error(f"Failed to save strangers' state due to {e}")

    def _load_strangers_state(self):
        try:
            stranger_embeddings = np.load(
                STRANGER_STATE_DIR / "embeds.npy", allow_pickle=True
            )
            stranger_labels = np.load(
                STRANGER_STATE_DIR / "labels.npy", allow_pickle=True
            )
            stranger_counter = int(
                np.load(STRANGER_STATE_DIR / "counter.npy", allow_pickle=True)
            )
        except Exception as e:
            logger.debug("Loaded strangers' state")
            logger.error(f"Failed to load strangers' state due to {e}")
            stranger_embeddings = None
            stranger_labels = None
            stranger_counter = 0

        if stranger_embeddings is not None and stranger_labels is not None:
            self._stranger_embeddings = stranger_embeddings
            self._stranger_labels = stranger_labels
            self._stranger_counter = stranger_counter

    def _score(self, embeds: np.ndarray, bank: np.ndarray, labels: np.ndarray):
        sim = embeds @ bank.T
        best = sim.argmax(axis=-1)
        scores = np.array([sim[i, best[i]] for i in range(len(embeds))])
        ids = [str(labels[best[i]]) for i in range(len(embeds))]
        return scores, ids

    @override
    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        if frame is None:
            return

        raw_results = self.app.get(frame)
        cur_ts = time.time()

        if not raw_results:
            self._face_present = False
            self._faces_n = 0
            self._check_leaves(cur_ts)
            return

        embeds = np.stack(
            [r["embedding"] / np.linalg.norm(r["embedding"]) for r in raw_results]
        )
        n = len(embeds)

        owner_scores = np.full(n, _NO_MATCH)
        owner_ids: list[str | None] = [None] * n
        if self._owner_embeddings is not None and self._owner_labels is not None:
            owner_scores, owner_ids = self._score(
                embeds, self._owner_embeddings, self._owner_labels
            )

        self._load_strangers_state()
        stranger_scores = np.full(n, _NO_MATCH)
        stranger_ids: list[str | None] = [None] * n
        if self._stranger_embeddings is not None and self._stranger_labels is not None:
            stranger_scores, stranger_ids = self._score(
                embeds, self._stranger_embeddings, self._stranger_labels
            )

        new_stranger_embeds = []
        new_stranger_labels = []
        owners_seen = set()
        strangers_seen = set()
        # per-face: (bbox_pixels, face_kind, label)  face_kind: "owner"|"friend"|"stranger"|"unsure"
        face_annotations: list[tuple[list[int], str, str]] = []

        for x in range(n):
            o_score = float(owner_scores[x])
            s_score = float(stranger_scores[x])
            bbox = [int(v) for v in raw_results[x]["bbox"]]

            if o_score > self.threshold:
                raw_id = owner_ids[x] or ""
                if raw_id.startswith(self.FRIEND_PREFIX):
                    face_kind = "friend"
                    person_id = raw_id.removeprefix(self.FRIEND_PREFIX)
                else:
                    face_kind = "owner"
                    person_id = raw_id.removeprefix(self.OWNER_PREFIX)

                if person_id not in self._owners_last_seen:
                    last_seen = None
                else:
                    last_seen = self._owners_last_seen[person_id]

                self._owners_last_seen[person_id] = cur_ts
                self._known_face_kinds[person_id] = face_kind

                if last_seen is None or (cur_ts - last_seen) > self._owners_forget_ts:
                    owners_seen.add(person_id)
                    face_annotations.append((bbox, face_kind, person_id))
                else:
                    logger.debug(
                        f"Ignore owner(id={person_id}): owner has been seen in the last {cur_ts - last_seen:.2f} seconds"
                    )

            elif s_score > self.threshold:
                person_id = (stranger_ids[x] or "").removeprefix(self.STRANGER_PREFIX)

                if person_id not in self._strangers_last_seen:
                    last_seen = None
                else:
                    last_seen = self._strangers_last_seen[person_id]

                self._strangers_last_seen[person_id] = cur_ts

                if (
                    last_seen is None
                    or (cur_ts - last_seen) > self._strangers_forget_ts
                ):
                    strangers_seen.add(person_id)
                    face_annotations.append((bbox, "stranger", person_id))
                else:
                    logger.debug(
                        f"Ignore stranger(id={person_id}): stranger has been seen in the last {cur_ts - last_seen:.2f} seconds"
                    )

            elif (
                self.negative_threshold is None
                or max(o_score, s_score) <= self.negative_threshold
            ):
                self._stranger_counter += 1
                self._stranger_counter %= int(1e6)
                stranger_id = (
                    self.STRANGER_PREFIX + f"stranger_{self._stranger_counter}"
                )
                person_id = stranger_id.removeprefix(self.STRANGER_PREFIX)
                self._strangers_last_seen[person_id] = cur_ts

                strangers_seen.add(person_id)
                face_annotations.append((bbox, "stranger", person_id))
                new_stranger_embeds.append(embeds[x])
                new_stranger_labels.append(stranger_id)

            else:
                # Score between negative_threshold and threshold on both banks — unsure
                face_annotations.append((bbox, "unsure", "?"))

        if new_stranger_embeds:
            stacked_e = np.stack(new_stranger_embeds, axis=0)
            stacked_l = np.stack(new_stranger_labels, axis=0)
            self._stranger_embeddings = (
                np.concatenate([self._stranger_embeddings, stacked_e])
                if self._stranger_embeddings is not None
                else stacked_e
            )
            self._stranger_labels = (
                np.concatenate([self._stranger_labels, stacked_l])
                if self._stranger_labels is not None
                else stacked_l
            )
            self._evict_oldest_strangers()
            self._save_strangers_state()

        self._faces_n = len(owners_seen) + len(strangers_seen)
        logger.info(
            f"Detected owners={list(owners_seen)} and strangers={list(strangers_seen)}"
        )
        self._face_present = self._faces_n > 0

        if self._face_present:
            self._on_motion()

            unsure_count = sum(1 for _, kind, _ in face_annotations if kind == "unsure")
            owners_in_frame = {
                name for _, kind, name in face_annotations if kind == "owner"
            }
            friends_in_frame = {
                name for _, kind, name in face_annotations if kind == "friend"
            }
            parts = []
            if owners_in_frame:
                parts.append(f"owner ({', '.join(owners_in_frame)})")
            if friends_in_frame:
                parts.append(f"friend ({', '.join(friends_in_frame)})")
            if strangers_seen:
                parts.append(f"stranger ({', '.join(strangers_seen)})")
            if unsure_count:
                parts.append(f"{unsure_count} unsure")
            summary = ", ".join(parts) if parts else "unknown person"

            self._send_enter_event(frame, face_annotations, summary=summary)
            if strangers_seen:
                self._track_stranger_visits(strangers_seen)

        self._check_leaves(cur_ts)

    def to_dict(self) -> dict:
        return {
            "type": "face",
            "face_present": self._face_present,
            "faces_count": self._faces_n,
            "owner_count": self.owner_count(),
            "stranger_count": len(self._stranger_embeddings)
            if self._stranger_embeddings is not None
            else 0,
        }

    # -- Presence leave detection ------------------------------------------------

    def _check_leaves(self, cur_ts: float) -> None:
        """Fire presence.leave for anyone not seen within their forget interval."""
        for person_id, last_seen in list(self._owners_last_seen.items()):
            if (cur_ts - last_seen) > self._owners_forget_ts:
                del self._owners_last_seen[person_id]
                kind = self._known_face_kinds.pop(person_id, "owner")
                self._send_leave_event(person_id, kind=kind)

        for person_id, last_seen in list(self._strangers_last_seen.items()):
            if (cur_ts - last_seen) > self._strangers_forget_ts:
                del self._strangers_last_seen[person_id]
                self._send_leave_event(person_id, kind="stranger")

    def _send_leave_event(self, person_id: str, kind: str) -> None:
        self._send_event(
            "presence.leave",
            f"Person no longer visible — {kind} ({person_id})",
            cooldown=config.FACE_COOLDOWN_S,
        )

    # -- Stranger visit tracking -------------------------------------------------

    @staticmethod
    def _load_stranger_stats() -> dict[str, dict]:
        try:
            return json.loads(_STRANGER_STATS_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_stranger_stats(self) -> None:
        try:
            _STRANGER_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STRANGER_STATS_FILE.write_text(
                json.dumps(self._stranger_visit_counts, indent=2)
            )
        except OSError as e:
            logger.warning("Failed to save stranger stats: %s", e)

    def _track_stranger_visits(self, stranger_ids: set[str]) -> None:
        """Increment visit count for each stranger seen in this frame."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for sid in stranger_ids:
            rec = self._stranger_visit_counts.get(sid)
            if rec is None:
                self._stranger_visit_counts[sid] = {
                    "count": 1,
                    "first_seen": now,
                    "last_seen": now,
                }
            else:
                rec["count"] += 1
                rec["last_seen"] = now
        if stranger_ids:
            self._save_stranger_stats()

    def stranger_stats(self) -> dict[str, dict]:
        """Return visit counts for all tracked stranger IDs."""
        return dict(self._stranger_visit_counts)

    # -- Events -----------------------------------------------------------------

    def _send_enter_event(
        self,
        frame: npt.NDArray[np.uint8],
        face_annotations: list[tuple[list[int], str, str]],
        summary: str,
    ) -> None:
        annotated = frame.copy()
        cv2 = self._cv2
        _COLOR = {
            "owner": (0, 255, 0),  # green
            "friend": (255, 200, 0),  # cyan/teal
            "stranger": (0, 0, 255),  # red
            "unsure": (0, 255, 255),  # yellow
        }
        for bbox, face_kind, label in face_annotations:
            x1, y1, x2, y2 = bbox
            color = _COLOR.get(face_kind, (128, 128, 128))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            display_label = label if face_kind != "unsure" else "unsure"
            cv2.putText(
                annotated,
                display_label,
                (x1, y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
        self._send_event(
            "presence.enter",
            f"Person detected — {len(face_annotations)} face(s) visible ({summary})",
            image=annotated,
            cooldown=config.FACE_COOLDOWN_S,
        )
