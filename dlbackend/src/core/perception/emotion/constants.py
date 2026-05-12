from pathlib import Path

RESOURCES_DIR = Path(__file__).parent / "resources"

# -- Default emotion model settings --
# Config overrides (when not None) take precedence at construction time.

EMOTION_DEFAULTS = {
    "confidence_threshold": 0.5,
    "frame_interval": 1.0,
}
