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

# Per-user data directory (face photos, wellbeing notes, mood history)
USERS_DIR = Path(config.USERS_DIR)
USERS_DIR.mkdir(parents=True, exist_ok=True)
STRANGER_STATE_DIR = Path(config.STRANGERS_DIR)
STRANGER_STATE_DIR.mkdir(exist_ok=True, parents=True)
_STRANGER_STATS_FILE = USERS_DIR / ".stranger_stats.json"


class FaceRecognizer(Perception):
    """InsightFace-based face recognizer. Detects friends and strangers, fires presence events."""

    FRIEND_PREFIX: str = "friend_"
    STRANGER_PREFIX: str = "stranger_"

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        threshold: float = 0.4,
        negative_threshold: float | None = 0.2,
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
        self._known_face_kinds: dict[str, str] = {}  # person_id → "friend"
        self._strangers_last_seen: dict[str, float] = {}
        self._stranger_visit_counts: dict[str, dict] = self._load_stranger_stats()

        self._face_present = False
        self._faces_n = 0

        # Stranger snapshot buffer — flushed every FACE_STRANGER_FLUSH_S
        # Each entry: (raw_frame, annotations[(bbox, kind, label), ...])
        self._stranger_flush_interval: float = config.FACE_STRANGER_FLUSH_S
        self._stranger_buffer: list[tuple[npt.NDArray[np.uint8], list[tuple[list[int], str, str]]]] = []
        self._stranger_ids_buffer: set[str] = set()
        self._last_stranger_flush_ts: float = 0.0

        # Enrolled embeddings — populated by train(), cleared by reset_enrolled()
        self._owner_embeddings: np.ndarray | None = None
        self._owner_labels: np.ndarray | None = None

        # Stranger embeddings — accumulated at runtime, never cleared by reset_enrolled().
        # Rows are insertion-ordered; index 0 is always the oldest stranger.
        self._stranger_embeddings: np.ndarray | None = None
        self._stranger_labels: np.ndarray | None = None

        import onnxruntime as ort
        ort.set_default_logger_severity(3)
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 1
        sess_opts.inter_op_num_threads = 1

        self.app: insightface.app.FaceAnalysis = insightface.app.FaceAnalysis(
            name=model_name, session_options=sess_opts
        )
        self.app.prepare(ctx_id=-1)

        self._start_watcher()

    def _start_watcher(self) -> None:
        """Poll USERS_DIR every 2s and reload embeddings when files change."""
        USERS_DIR.mkdir(parents=True, exist_ok=True)

        def _latest_mtime() -> float:
            try:
                return max(
                    (e.stat().st_mtime for e in USERS_DIR.rglob("*")),
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
                    logger.info("User photos changed — reloading embeddings")
                    self.load_from_disk()

        t = threading.Thread(target=_poll, daemon=True, name="owner-photos-watcher")
        t.start()
        logger.info("Watching users dir: %s", USERS_DIR)

    def train(
        self,
        images: list[npt.NDArray[np.uint8]],
        labels: list[int | str],
    ) -> None:
        prefixed_labels = [self.FRIEND_PREFIX + str(lbl) for lbl in labels]
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
                "Added %d faces — total enrolled: %d, total strangers: %d",
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
        return s[:64] if s else "person"

    def _clear_owner_embeddings(self) -> None:
        self._owner_embeddings = None
        self._owner_labels = None

    @staticmethod
    def _read_metadata(person_dir: Path) -> dict:
        """Read metadata.json from a person's folder. Returns {} if missing."""
        meta_path = person_dir / "metadata.json"
        if meta_path.is_file():
            try:
                return json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    @staticmethod
    def _write_metadata(person_dir: Path, telegram_username: str = "", telegram_id: str = "") -> None:
        """Write metadata.json with telegram info."""
        meta_path = person_dir / "metadata.json"
        data: dict = {}
        if meta_path.is_file():
            try:
                data = json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        if telegram_username:
            data["telegram_username"] = telegram_username
        if telegram_id:
            data["telegram_id"] = telegram_id
        meta_path.write_text(json.dumps(data))

    def save_photo(self, image_bytes: bytes, label: str, telegram_username: str = "", telegram_id: str = "") -> str:
        """Write JPEG bytes under USERS_DIR/{label}/ with a timestamp name."""
        norm = self.normalize_label(label)
        dest_dir = USERS_DIR / norm
        dest_dir.mkdir(parents=True, exist_ok=True)
        if telegram_username or telegram_id:
            self._write_metadata(dest_dir, telegram_username, telegram_id)
        fname = f"{int(time.time() * 1000)}.jpg"
        path = dest_dir / fname
        path.write_bytes(image_bytes)
        return str(path)

    def load_from_disk(self) -> int:
        """Clear enrolled embeddings and re-train from all JPEG/PNG images under USERS_DIR."""
        self._clear_owner_embeddings()
        if not USERS_DIR.is_dir():
            logger.info("No users dir at %s — skipping", USERS_DIR)
            return 0

        _IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
        loaded_total = 0

        for person_dir in sorted(USERS_DIR.iterdir()):
            if not person_dir.is_dir():
                continue
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
                self.train(images, labels)
                loaded_total += len(images)
                logger.info(
                    "Loaded %d image(s) for '%s'",
                    len(images),
                    person_dir.name,
                )

        n_enrolled = self.enrolled_count()
        logger.info(
            "Load from disk done — %d image(s), %d enrolled person(s)",
            loaded_total,
            n_enrolled,
        )
        return n_enrolled

    def enroll_from_bytes(self, image_bytes: bytes, label: str, telegram_username: str = "", telegram_id: str = "") -> str:
        """Decode image, save as JPEG on disk, and append embeddings."""
        norm = self.normalize_label(label)
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = self._cv2.imdecode(arr, self._cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("could not decode image")
        if not self.app.get(img):
            raise ValueError("no face detected in image")
        ok, buf = self._cv2.imencode(".jpg", img)
        if not ok:
            raise ValueError("could not encode image")
        path = self.save_photo(buf.tobytes(), norm, telegram_username, telegram_id)
        self.train([img], [norm])
        return path

    def get_telegram_id(self, label: str) -> str | None:
        """Return telegram_id for a person, or None if not set."""
        norm = self.normalize_label(label)
        person_dir = USERS_DIR / norm
        meta = self._read_metadata(person_dir)
        return meta.get("telegram_id") or None

    def remove_person(self, label: str) -> bool:
        """Remove one person's directory and re-load remaining persons from disk."""
        norm = self.normalize_label(label)
        person_dir = USERS_DIR / norm
        if not person_dir.is_dir():
            return False
        shutil.rmtree(person_dir)
        self.load_from_disk()
        return True

    def enrolled_count(self) -> int:
        if self._owner_labels is None:
            return 0
        unique = set()
        for lbl in self._owner_labels:
            s = str(lbl)
            unique.add(s.removeprefix(self.FRIEND_PREFIX))
        return len(unique)

    def enrolled_names(self) -> list[str]:
        if self._owner_labels is None:
            return []
        unique = set()
        for lbl in self._owner_labels:
            s = str(lbl)
            unique.add(s.removeprefix(self.FRIEND_PREFIX))
        return sorted(unique)

    def reset_enrolled(self) -> None:
        """Clear enrolled embeddings and delete all saved photos. Stranger bank is unchanged."""
        self._clear_owner_embeddings()
        if USERS_DIR.is_dir():
            for child in USERS_DIR.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
        logger.info("Enrolled embeddings cleared and photos removed")

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
    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
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
        # per-face: (bbox_pixels, face_kind, label)  face_kind: "friend"|"stranger"|"unsure"
        face_annotations: list[tuple[list[int], str, str]] = []

        for x in range(n):
            o_score = float(owner_scores[x])
            s_score = float(stranger_scores[x])
            bbox = [int(v) for v in raw_results[x]["bbox"]]

            if o_score > self.threshold:
                raw_id = owner_ids[x] or ""
                face_kind = "friend"
                person_id = raw_id.removeprefix(self.FRIEND_PREFIX)

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
                        f"Ignore friend(id={person_id}): seen in the last {cur_ts - last_seen:.2f} seconds"
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
            f"Detected friends={list(owners_seen)} and strangers={list(strangers_seen)}"
        )
        self._face_present = self._faces_n > 0

        if self._face_present:
            self._on_motion()

        # Strangers: always buffer snapshots; flush decides when to send
        if strangers_seen:
            stranger_annotations = [
                (bbox, kind, label)
                for bbox, kind, label in face_annotations
                if kind == "stranger"
            ]
            self._stranger_buffer.append((frame.copy(), stranger_annotations))
            self._stranger_ids_buffer.update(strangers_seen)
            self._track_stranger_visits(strangers_seen)

        flushed_snapshots, flushed_ids = self._flush_stranger_buffer(cur_ts)

        # Build annotations to send: friends always, strangers only on flush
        owner_annotations = [
            (bbox, kind, label)
            for bbox, kind, label in face_annotations
            if kind == "friend"
        ]
        annotations_to_send = list(owner_annotations)
        if flushed_ids:
            annotations_to_send += [
                (bbox, kind, label)
                for bbox, kind, label in face_annotations
                if kind == "stranger"
            ]

        if annotations_to_send:
            friends_in_frame = {
                name for _, kind, name in annotations_to_send if kind == "friend"
            }
            strangers_in_frame = flushed_ids
            parts = []
            if friends_in_frame:
                parts.append(f"friend ({', '.join(friends_in_frame)})")
            if strangers_in_frame:
                parts.append(f"stranger ({', '.join(strangers_in_frame)})")
            summary = ", ".join(parts)
            self._send_enter_event(
                frames=[(frame, annotations_to_send)] + flushed_snapshots,
                summary=summary,
            )

        self._check_leaves(cur_ts)

    def to_dict(self) -> dict:
        return {
            "type": "face",
            "face_present": self._face_present,
            "faces_count": self._faces_n,
            "enrolled_count": self.enrolled_count(),
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
                kind = self._known_face_kinds.pop(person_id, "friend")
                self._send_leave_event(person_id, kind=kind)

        for person_id, last_seen in list(self._strangers_last_seen.items()):
            if (cur_ts - last_seen) > self._strangers_forget_ts:
                del self._strangers_last_seen[person_id]
                # self._send_leave_event(person_id, kind="stranger")

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

    def has_friend_present(self) -> bool:
        """Return True if any friend was seen within the forget interval."""
        if not self._owners_last_seen:
            return False
        now = time.time()
        return any(
            (now - ts) <= self._owners_forget_ts
            for ts in self._owners_last_seen.values()
        )

    # -- Cooldown state / reset -------------------------------------------------

    def cooldown_state(self) -> dict:
        """Return current cooldown state for all tracked persons."""
        now = time.time()
        owners = []
        for person_id, last_seen in self._owners_last_seen.items():
            elapsed = now - last_seen
            remaining = max(0.0, self._owners_forget_ts - elapsed)
            kind = self._known_face_kinds.get(person_id, "friend")
            owners.append({
                "person_id": person_id,
                "kind": kind,
                "last_seen_ago": round(elapsed, 1),
                "cooldown_remaining": round(remaining, 1),
                "cooldown_total": self._owners_forget_ts,
            })
        strangers = []
        for person_id, last_seen in self._strangers_last_seen.items():
            elapsed = now - last_seen
            remaining = max(0.0, self._strangers_forget_ts - elapsed)
            strangers.append({
                "person_id": person_id,
                "kind": "stranger",
                "last_seen_ago": round(elapsed, 1),
                "cooldown_remaining": round(remaining, 1),
                "cooldown_total": self._strangers_forget_ts,
            })
        return {
            "owners": owners,
            "strangers": strangers,
            "owners_forget_s": self._owners_forget_ts,
            "strangers_forget_s": self._strangers_forget_ts,
        }

    def reset_cooldowns(self) -> None:
        """Clear all last-seen timestamps so next detection fires events immediately."""
        self._owners_last_seen.clear()
        self._known_face_kinds.clear()
        self._strangers_last_seen.clear()
        logger.info("Face recognition cooldowns reset")

    # -- Events -----------------------------------------------------------------

    def _annotate_frame(
        self,
        frame: npt.NDArray[np.uint8],
        face_annotations: list[tuple[list[int], str, str]],
    ) -> npt.NDArray[np.uint8]:
        """Draw bounding boxes and labels on a frame copy."""
        annotated = frame.copy()
        cv2 = self._cv2
        _COLOR = {
            "friend": (0, 255, 0),  # green
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
        return annotated

    def _flush_stranger_buffer(
        self, cur_ts: float
    ) -> tuple[list[tuple[npt.NDArray[np.uint8], list[tuple[list[int], str, str]]]], set[str]]:
        """Flush buffered stranger snapshots if the interval has elapsed.

        Returns ([(frame, annotations), ...], flushed_ids). Empty if not yet time to flush.
        """
        if not self._stranger_buffer:
            return [], set()

        if (cur_ts - self._last_stranger_flush_ts) < self._stranger_flush_interval:
            return [], set()

        entries = list(self._stranger_buffer)
        ids = set(self._stranger_ids_buffer)
        self._stranger_buffer.clear()
        self._stranger_ids_buffer.clear()
        self._last_stranger_flush_ts = cur_ts
        logger.info("[face] flushing %d stranger snapshot(s) for %s", len(entries), ids)
        return entries, ids

    def _send_enter_event(
        self,
        frames: list[tuple[npt.NDArray[np.uint8], list[tuple[list[int], str, str]]]],
        summary: str,
    ) -> None:
        """Send a presence.enter event with annotated snapshots.

        Args:
            frames: List of (raw_frame, annotations) tuples. Each frame is annotated
                with bounding boxes and labels before sending. Includes the current
                frame plus any buffered stranger snapshots from the flush window.
            summary: Human-readable description of who was detected
                (e.g. "friend (alice), stranger (stranger_3)").
        """
        images = [self._annotate_frame(frame, annotations) for frame, annotations in frames]
        faces: set[tuple[str, str]] = set()
        for _, annotations in frames:
            for _, face_kind, label in annotations:
                faces.add((face_kind, label))
        total_faces = len(faces)
        self._send_event(
            "presence.enter",
            f"Person detected — {total_faces} face(s) visible ({summary})",
            images=images,
            cooldown=config.FACE_COOLDOWN_S,
        )
