from pathlib import Path

RESOURCES_DIR = Path(__file__).parent / "resources"

# -- Per-model defaults --
# Each model defines its own defaults here. Config overrides (when not None)
# take precedence at construction time.

VIDEOMAE_DEFAULTS = {
    "max_frames": 16,
    "frame_size": (224, 224),
    "frame_interval": 1.0,
    "confidence_threshold": 0.3,
}

UNIFORMERV2_DEFAULTS = {
    "max_frames": 8,
    "frame_size": (224, 224),
    "frame_interval": 1.0,
    "confidence_threshold": 0.3,
}

X3D_DEFAULTS = {
    "max_frames": 16,
    "frame_size": (256, 256),
    "frame_interval": 1.0,
    "confidence_threshold": 0.3,
}
