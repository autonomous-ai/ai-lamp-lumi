import logging
import re
import shutil
import time
from pathlib import Path
from typing import Callable, override

import insightface
import lelamp.config as config
import numpy as np
import numpy.typing as npt

from .base import Perception

logger = logging.getLogger(__name__)

_NO_MATCH = -2.0  # sentinel score used when an embedding bank is empty

# Persisted owner photos (see save_photo / load_from_disk)
OWNER_PHOTOS_DIR = Path(config.OWNER_PHOTOS_DIR)


class FaceRecognizer(Perception):
    """InsightFace-based face recognizer. Detects owners and strangers, fires presence events."""

    OWNER_PREFIX: str = "owner_"
    STRANGER_PREFIX: str = "stranger_"

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        threshold: float = 0.4,
        negative_threshold: float | None = 0.1,
        model_name: str = "buffalo_sc",
        max_strangers: int = 50,
        strangers_forget_ts: float = 360,
        owners_forget_ts: float = 3600,
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
        self._strangers_last_seen: dict[str, float] = {}

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

    def train(
        self, images: list[npt.NDArray[np.uint8]], labels: list[int | str]
    ) -> None:
        prefixed_labels = [self.OWNER_PREFIX + str(lbl) for lbl in labels]
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
        return (s[:64] if s else "owner")

    def _clear_owner_embeddings(self) -> None:
        self._owner_embeddings = None
        self._owner_labels = None

    def save_photo(self, image_bytes: bytes, label: str) -> str:
        """Write JPEG bytes under OWNER_PHOTOS_DIR/{label}/ with a timestamp name."""
        norm = self.normalize_label(label)
        dest_dir = OWNER_PHOTOS_DIR / norm
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{int(time.time() * 1000)}.jpg"
        path = dest_dir / fname
        path.write_bytes(image_bytes)
        return str(path)

    def load_from_disk(self) -> int:
        """Clear owner embeddings and re-train from all JPEG/PNG images under OWNER_PHOTOS_DIR."""
        self._clear_owner_embeddings()
        if not OWNER_PHOTOS_DIR.is_dir():
            logger.info("No owner photos dir at %s — skipping", OWNER_PHOTOS_DIR)
            return 0

        _IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
        loaded_total = 0

        for owner_id in sorted(OWNER_PHOTOS_DIR.iterdir()):
            if not owner_id.is_dir():
                continue
            images = []
            labels: list[str] = []
            for fname in sorted(owner_id.iterdir()):
                if fname.suffix.lower() not in _IMG_EXTS:
                    continue
                img = self._cv2.imread(str(fname))
                if img is None:
                    logger.warning("Failed to load owner image: %s", fname)
                    continue
                images.append(img)
                labels.append(owner_id.name)

            if images:
                self.train(images, labels)
                loaded_total += len(images)
                logger.info(
                    "Loaded %d image(s) for owner '%s'",
                    len(images),
                    owner_id.name,
                )

        n_owners = self.owner_count()
        logger.info(
            "Owner load from disk done — %d image(s), %d owner(s)",
            loaded_total,
            n_owners,
        )
        return n_owners

    def enroll_from_bytes(self, image_bytes: bytes, label: str) -> str:
        """Decode image, save as JPEG on disk, and append embeddings for this owner."""
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
        path = self.save_photo(buf.tobytes(), norm)
        self.train([img], [norm])
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
        unique = {
            str(lbl).removeprefix(self.OWNER_PREFIX) for lbl in self._owner_labels
        }
        return len(unique)

    def owner_names(self) -> list[str]:
        if self._owner_labels is None:
            return []
        unique = {
            str(lbl).removeprefix(self.OWNER_PREFIX) for lbl in self._owner_labels
        }
        return sorted(unique)

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

        if not raw_results:
            self._face_present = False
            self._faces_n = 0
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
        # per-face: (bbox_pixels, face_kind, label)  face_kind: "owner"|"stranger"|"unsure"
        face_annotations: list[tuple[list[int], str, str]] = []

        cur_ts = time.time()

        for x in range(n):
            o_score = float(owner_scores[x])
            s_score = float(stranger_scores[x])
            bbox = [int(v) for v in raw_results[x]["bbox"]]

            if o_score > self.threshold:
                person_id = (owner_ids[x] or "").removeprefix(self.OWNER_PREFIX)

                if person_id not in self._owners_last_seen:
                    last_seen = None
                else:
                    last_seen = self._owners_last_seen[person_id]

                self._owners_last_seen[person_id] = cur_ts

                if last_seen is None or (cur_ts - last_seen) > self._owners_forget_ts:
                    owners_seen.add(person_id)
                    face_annotations.append((bbox, "owner", person_id))

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

            elif (
                self.negative_threshold is None
                or max(o_score, s_score) <= self.negative_threshold
            ):
                self._stranger_counter += 1
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

        self._faces_n = len(owners_seen) + len(strangers_seen)
        self._face_present = self._faces_n > 0

        if self._face_present:
            self._on_motion()

            unsure_count = sum(1 for _, kind, _ in face_annotations if kind == "unsure")
            parts = []
            if owners_seen:
                parts.append(f"owner ({', '.join(owners_seen)})")
            if strangers_seen:
                parts.append(f"stranger ({', '.join(strangers_seen)})")
            if unsure_count:
                parts.append(f"{unsure_count} unsure")
            summary = ", ".join(parts) if parts else "unknown person"

            self._send_enter_event(frame, face_annotations, summary=summary)

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
