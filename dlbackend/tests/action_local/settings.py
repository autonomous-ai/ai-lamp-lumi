"""Local test settings — paths to model files used in local integration tests."""

from pathlib import Path

LOCAL_DIR = Path(__file__).parent / "local"

VIDEOMAE_MODEL_PATH = LOCAL_DIR / "videomae_fp32.onnx"
UNIFORMERV2_MODEL_PATH = LOCAL_DIR / "uniformerv2-b-224_fp32.onnx"
