"""Build an ONNX export of an emotion2vec model from a FunASR checkpoint.

Standalone fallback used by :class:`BaseSpeechEmotionRecognizer` when no
ONNX file is present locally and no remote URL is configured. The export
graph wraps FunASR's ``Emotion2vec`` model so the ONNX input is the raw
mono 16 kHz waveform ``[B, T]`` and the output ``scores`` is the softmax
probability ``[B, num_classes]``. Labels that start with ``"unuse"`` in
the FunASR tokenizer are masked out of the softmax via a large negative
bias, mirroring FunASR's own classifier head.

After a successful export, this module also copies the ``tokens.txt``
file that lives next to the ``model.pt`` snapshot in the HuggingFace
cache into the destination folder as ``labels.txt``, so the engine can
pick it up on its very next start with zero manual steps (falls back to
``tokenizer.token_list`` if the file isn't there).

Heavy imports (``torch``, ``funasr``) live inside the function so that
importing this module never pulls them in.

Example:
    from core.ser.prepare_onnx import prepare_onnx_export
    prepare_onnx_export("iic/emotion2vec_plus_large", "/tmp/e2v.onnx")
"""

from __future__ import annotations

import copy
import logging
import os
import types
import warnings
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


# FunASR snapshots ship the class list as a plain text file. The filename
# is usually ``tokens.txt`` but some converters emit ``token_list.txt``;
# we look for both.
_TOKENS_FILE_CANDIDATES = ("tokens.txt", "token_list.txt")


def _find_snapshot_dir(auto: Any) -> Optional[Path]:
    """Best-effort: locate the folder that holds ``model.pt`` (and tokens.txt).

    FunASR stores the ckpt path under several possible keys depending on
    version (``init_param``, ``model_path``, ``model_dir``). We probe them
    in order and return the parent dir of the first one that resolves to
    a real file/dir.
    """
    candidates = []
    kwargs = getattr(auto, "kwargs", None) or {}
    for key in ("init_param", "model_path", "model_dir"):
        val = kwargs.get(key)
        if val:
            candidates.append(val)
    # Some FunASR versions expose a direct attribute.
    for attr in ("model_path", "init_param"):
        val = getattr(auto, attr, None)
        if val:
            candidates.append(val)

    for raw in candidates:
        try:
            p = Path(str(raw)).expanduser().resolve()
        except Exception:
            continue
        if p.is_file():
            return p.parent
        if p.is_dir():
            return p
    return None


def _normalize_label(raw: str) -> Optional[str]:
    """Pick the English label from an upstream ``tokens.txt`` row.

    FunASR's ``tokens.txt`` for emotion2vec ships labels as
    ``"<chinese>/<english>"`` pairs (e.g. ``"生气/angry"``); special
    tokens such as ``"<unk>"`` come without a slash. We split on ``/``
    and keep the **last** non-empty segment so:

    * ``"生气/angry"`` -> ``"angry"``
    * ``"<unk>"``      -> ``"<unk>"``
    * ``""`` / blank   -> ``None`` (caller drops it)
    """
    line = raw.strip()
    if not line:
        return None
    if "/" in line:
        parts = [p.strip() for p in line.split("/") if p.strip()]
        if parts:
            return parts[-1]
    return line


def _materialize_labels(
    auto: Any,
    tokenizer: Any,
    output_dir: Path,
) -> Optional[Path]:
    """Read / synthesize ``labels.txt`` next to the exported ONNX file.

    Resolution order:

    1. Read ``tokens.txt`` (or ``token_list.txt``) from the FunASR
       snapshot folder that holds ``model.pt``, normalize each row with
       :func:`_normalize_label` (keeps only the English label after
       the ``/``), and write the result as ``labels.txt``.
    2. Fall back to ``tokenizer.token_list`` if the file isn't there but
       the tokenizer is loaded in memory; same per-token normalization.
    3. Give up silently (returns ``None``) -- caller may already have a
       hand-maintained ``labels.txt`` in the repo and we don't want to
       overwrite a user's file with an empty placeholder.
    """
    labels_dest = output_dir / "labels.txt"

    def _write_labels(labels: list[str], source_desc: str) -> Optional[Path]:
        if not labels:
            logger.warning(
                "[SER.prepare_onnx] %s yielded 0 usable labels; "
                "skipping write to %s.",
                source_desc,
                labels_dest,
            )
            return None
        try:
            labels_dest.write_text("\n".join(labels) + "\n", encoding="utf-8")
            logger.info(
                "[SER.prepare_onnx] Wrote %d labels from %s -> %s",
                len(labels),
                source_desc,
                labels_dest,
            )
            return labels_dest
        except OSError as exc:
            logger.warning(
                "[SER.prepare_onnx] Could not write %s (%s); "
                "leaving labels.txt untouched.",
                labels_dest,
                exc,
            )
            return None

    snapshot_dir = _find_snapshot_dir(auto)
    if snapshot_dir is not None:
        for fname in _TOKENS_FILE_CANDIDATES:
            src = snapshot_dir / fname
            if not src.exists():
                continue
            try:
                raw_lines = src.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                logger.warning(
                    "[SER.prepare_onnx] Could not read %s (%s); "
                    "will try tokenizer fallback.",
                    src,
                    exc,
                )
                break
            labels = [lbl for lbl in (_normalize_label(ln) for ln in raw_lines) if lbl]
            written = _write_labels(labels, f"snapshot tokens file '{src}'")
            if written is not None:
                return written
            break  # file existed but normalization produced nothing -> try fallback

    token_list = getattr(tokenizer, "token_list", None) if tokenizer else None
    if token_list:
        labels = [
            lbl
            for lbl in (_normalize_label(str(tok)) for tok in token_list)
            if lbl
        ]
        written = _write_labels(labels, "tokenizer.token_list")
        if written is not None:
            return written

    logger.warning(
        "[SER.prepare_onnx] No tokens.txt found in FunASR snapshot and tokenizer "
        "has no token_list; labels.txt was NOT created. Provide it manually "
        "next to %s.",
        output_dir,
    )
    return None



def _export_forward(self, x):
    """ONNX forward: raw waveform -> softmax scores (or pooled embedding).

    Replicates FunASR's ``Emotion2vec.inference`` head so the exported graph
    is self-contained.
    """
    import torch

    with torch.no_grad():
        if self.cfg.normalize:
            mean = torch.mean(x, dim=1, keepdim=True)
            var = torch.var(x, dim=1, keepdim=True, unbiased=False)
            x = (x - mean) / torch.sqrt(var + 1e-5)
            x = x.view(x.shape[0], -1)

        res = self._original_forward(
            source=x,
            padding_mask=None,
            mask=False,
            features_only=True,
            remove_extra_tokens=True,
        )
        h = res["x"]
        if self.proj is None:
            return h

        z = h.mean(dim=1)
        logits = self.proj(z)
        if getattr(self, "_export_logit_bias", None) is not None:
            logits = logits + self._export_logit_bias.to(
                device=logits.device, dtype=logits.dtype
            )
        return torch.softmax(logits, dim=-1)


def _export_dummy_inputs(self):
    import torch

    return (torch.randn(1, 16000),)


def _export_input_names(self):
    return ["input"]


def _export_output_names(self):
    if getattr(self, "proj", None) is not None:
        return ["scores"]
    return ["output"]


def _export_dynamic_axes(self):
    axes = {"input": {0: "batch_size", 1: "sequence_length"}}
    if getattr(self, "proj", None) is not None:
        axes["scores"] = {0: "batch_size"}
    else:
        axes["output"] = {0: "batch_size", 1: "sequence_length"}
    return axes


def _export_name(self):
    return "emotion2vec"


def _rebuild_for_export(model, tokenizer=None):
    """Attach the export-time helpers + ``unuse``-label masking."""
    import torch

    model._original_forward = model.forward

    if getattr(model, "proj", None) is not None:
        n = model.proj.out_features
        bias = torch.zeros(n, dtype=torch.float32)
        if tokenizer is not None and hasattr(tokenizer, "token_list"):
            tl = tokenizer.token_list
            if len(tl) != n:
                warnings.warn(
                    f"tokenizer token_list len {len(tl)} != proj.out_features {n}; "
                    "unuse mask not applied (softmax over all classes)."
                )
            else:
                for i, lab in enumerate(tl):
                    if str(lab).startswith("unuse"):
                        bias[i] = -1e4
        model.register_buffer("_export_logit_bias", bias)
    else:
        model._export_logit_bias = None

    model.forward = types.MethodType(_export_forward, model)
    model.export_dummy_inputs = types.MethodType(_export_dummy_inputs, model)
    model.export_input_names = types.MethodType(_export_input_names, model)
    model.export_output_names = types.MethodType(_export_output_names, model)
    model.export_dynamic_axes = types.MethodType(_export_dynamic_axes, model)
    model.export_name = types.MethodType(_export_name, model)
    return model



def prepare_onnx_export(
    model_id: str,
    output_path: Union[str, Path],
    *,
    hub: str = "hf",
    device: str = "cpu",
    opset_version: int = 14,
    quantize: bool = False,
    verbose: bool = False,
) -> Path:
    """Download a FunASR emotion2vec checkpoint and export it to ONNX.

    Args:
        model_id: FunASR / HuggingFace model identifier
            (e.g. ``"iic/emotion2vec_plus_large"``).
        output_path: Final ONNX path. Parent directory is created.
        hub: FunASR hub name (``"hf"`` or ``"ms"``).
        device: Torch device used for tracing.
        opset_version: ONNX opset version.
        quantize: Run dynamic INT8 quantization after export.
        verbose: Pass-through to ``torch.onnx.export``.

    Returns:
        The :class:`pathlib.Path` of the resulting ``.onnx`` file.

    Raises:
        ImportError: ``torch``/``funasr`` are not installed.
        RuntimeError: The export step did not produce the expected file.
    """
    try:
        import torch
        from funasr import AutoModel
        from funasr.utils.misc import deep_update
    except ImportError as exc:
        raise ImportError(
            "Building SER ONNX requires 'torch' and 'funasr'. "
            "Install them or supply a pre-exported ONNX via SER_MODEL_PATH."
        ) from exc

    dest = Path(output_path).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "[SER.prepare_onnx] Downloading FunASR weights (model_id=%s, hub=%s)...",
        model_id,
        hub,
    )
    auto = AutoModel(model=model_id, hub=hub, device=device)

    kwargs = copy.deepcopy(auto.kwargs)
    kwargs["device"] = device
    kwargs.pop("model", None)
    deep_update(
        kwargs,
        {
            "output_dir": str(dest.parent),
            "opset_version": int(opset_version),
            "quantize": bool(quantize),
            "verbose": bool(verbose),
        },
    )

    pt_model = auto.model.to(device)
    pt_model.eval()

    tokenizer = kwargs.get("tokenizer")
    with torch.no_grad():
        onnx_wrapped = _rebuild_for_export(pt_model, tokenizer=tokenizer)
        onnx_wrapped.eval()

        dummy = onnx_wrapped.export_dummy_inputs()
        if isinstance(dummy, torch.Tensor):
            dummy = dummy.to(device)
        else:
            dummy = tuple(t.to(device) for t in dummy)

        base = onnx_wrapped.export_name()
        intermediate = dest.parent / (
            base if str(base).endswith(".onnx") else f"{base}.onnx"
        )

        logger.info("[SER.prepare_onnx] Exporting ONNX to %s ...", intermediate)
        torch.onnx.export(
            onnx_wrapped,
            dummy,
            str(intermediate),
            verbose=verbose,
            do_constant_folding=True,
            opset_version=int(opset_version),
            input_names=onnx_wrapped.export_input_names(),
            output_names=onnx_wrapped.export_output_names(),
            dynamic_axes=onnx_wrapped.export_dynamic_axes(),
        )

        if quantize:
            try:
                from onnxruntime.quantization import QuantType, quantize_dynamic
                import onnx as onnx_pkg
            except ImportError as exc:
                raise ImportError(
                    "Set quantize=False or install onnx + onnxruntime quantization extras."
                ) from exc

            quant_path = intermediate.with_name(intermediate.stem + "_quant.onnx")
            onnx_model = onnx_pkg.load(str(intermediate))
            nodes = [n.name for n in onnx_model.graph.node]
            nodes_to_exclude = [
                n for n in nodes
                if "output" in n or "bias_encoder" in n or "bias_decoder" in n
            ]
            quantize_dynamic(
                model_input=str(intermediate),
                model_output=str(quant_path),
                op_types_to_quantize=["MatMul"],
                per_channel=True,
                reduce_range=False,
                weight_type=QuantType.QUInt8,
                nodes_to_exclude=nodes_to_exclude,
            )
            intermediate = quant_path

    if intermediate != dest:
        if dest.exists():
            dest.unlink()
        os.replace(intermediate, dest)

    if not dest.exists():
        raise RuntimeError(f"ONNX export completed but file is missing: {dest}")

    try:
        _materialize_labels(auto, tokenizer, dest.parent)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("[SER.prepare_onnx] Materializing labels.txt failed: %s", exc)

    logger.info("[SER.prepare_onnx] Done -> %s", dest)
    return dest
