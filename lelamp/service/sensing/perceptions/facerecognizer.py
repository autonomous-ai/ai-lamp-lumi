import logging
from typing import Callable, override

import insightface
import lelamp.config as config
import numpy as np
import numpy.typing as npt

from .base import Perception

logger = logging.getLogger(__name__)

_NO_MATCH = -2.0  # sentinel score used when an embedding bank is empty


class FaceRecognizer(Perception):
    """InsightFace-based face recognizer. Detects owners and strangers, fires presence events."""

    OWNER_PREFIX: str = "owner_"
    STRANGER_PREFIX: str = "stranger_"

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        encode_frame: Callable,
        threshold: float = 0.4,
        negative_threshold: float | None = 0.2,
        model_name: str = "buffalo_sc",
        max_strangers: int = 50,
    ):
        super().__init__(send_event)
        self._cv2 = cv2
        self._on_motion = on_motion
        self._encode_frame = encode_frame

        self.threshold = threshold
        self.negative_threshold = negative_threshold
        self.max_strangers = max_strangers
        self._stranger_counter = 0

        self._face_present: bool = False
        self._face_absent_count: int = 0

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

    def reset_owners(self) -> None:
        """Clear owner embeddings so they can be retrained without losing stranger memory."""
        self._owner_embeddings = None
        self._owner_labels = None
        logger.info("Owner embeddings cleared")

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
        raw_results = self.app.get(frame)
        face_found = len(raw_results) > 0

        if not face_found:
            if self._face_present:
                self._face_absent_count += 1
                if self._face_absent_count >= 3:
                    self._face_present = False
                    self._face_absent_count = 0
                    self._send_event(
                        "presence.leave",
                        "No face detected — person may have left the area",
                        cooldown=config.FACE_COOLDOWN_S,
                    )
            return

        H, W, _ = frame.shape
        embeds = np.array(
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
        owners_seen = []
        strangers_seen = []
        # per-face: (bbox_pixels, face_kind, label)  face_kind: "owner"|"stranger"|"unsure"
        face_annotations: list[tuple[list[int], str, str]] = []

        for x in range(n):
            o_score = float(owner_scores[x])
            s_score = float(stranger_scores[x])
            bbox = [int(v) for v in raw_results[x]["bbox"]]

            if o_score > self.threshold:
                person_id = (owner_ids[x] or "").removeprefix(self.OWNER_PREFIX)
                owners_seen.append(person_id)
                face_annotations.append((bbox, "owner", person_id))

            elif s_score > self.threshold:
                person_id = (stranger_ids[x] or "").removeprefix(self.STRANGER_PREFIX)
                strangers_seen.append(person_id)
                face_annotations.append((bbox, "stranger", person_id))

            elif self.negative_threshold is None or (
                o_score <= self.negative_threshold
                and s_score <= self.negative_threshold
            ):
                self._stranger_counter += 1
                stranger_id = (
                    self.STRANGER_PREFIX + f"stranger_{self._stranger_counter}"
                )
                person_id = stranger_id.removeprefix(self.STRANGER_PREFIX)
                strangers_seen.append(person_id)
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

        if not self._face_present:
            self._face_present = True
            self._face_absent_count = 0
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
        else:
            self._face_absent_count = 0

    def to_dict(self) -> dict:
        return {
            "type": "face",
            "face_present": self._face_present,
            "face_absent_count": self._face_absent_count,
            "owner_count": len(self._owner_embeddings) if self._owner_embeddings is not None else 0,
            "stranger_count": len(self._stranger_embeddings) if self._stranger_embeddings is not None else 0,
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
            "owner": (0, 255, 0),    # green
            "stranger": (0, 0, 255), # red
            "unsure": (0, 255, 255), # yellow
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
        image_b64 = self._encode_frame(annotated)
        self._send_event(
            "presence.enter",
            f"Person detected — {len(face_annotations)} face(s) visible ({summary})",
            image=image_b64,
            cooldown=config.FACE_COOLDOWN_S,
        )
