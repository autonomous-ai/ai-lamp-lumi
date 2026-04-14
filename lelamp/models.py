"""
LeLamp Pydantic request/response models.

All FastAPI endpoint models live here — import from server.py via `from lelamp.models import *`.
"""

from typing import Optional, Union

from pydantic import BaseModel, Field


class ServoRequest(BaseModel):
    recording: str

    model_config = {"json_schema_extra": {"examples": [{"recording": "curious"}]}}


class ServoStateResponse(BaseModel):
    available_recordings: list[str]
    current: Optional[str]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "available_recordings": [
                        "nod",
                        "curious",
                        "happy_wiggle",
                        "idle",
                        "sad",
                        "excited",
                        "shy",
                        "shock",
                        "listening",
                        "thinking_deep",
                        "laugh",
                        "confused",
                        "sleepy",
                        "greeting",
                        "goodbye",
                        "acknowledge",
                        "stretching",
                        "scanning",
                        "wake_up",
                        "headshake",
                        "music_groove",
                        "music_chill",
                        "music_hype",
                    ],
                    "current": "idle",
                }
            ]
        }
    }


class LEDSolidRequest(BaseModel):
    color: Union[list[int], int]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"color": [255, 100, 0]},
                {"color": 16711680},
            ]
        }
    }


class LEDPaintRequest(BaseModel):
    colors: list[Union[list[int], int]]

    model_config = {
        "json_schema_extra": {
            "examples": [{"colors": [[255, 0, 0], [0, 255, 0], [0, 0, 255]]}]
        }
    }


class LEDStateResponse(BaseModel):
    led_count: int


class LEDColorResponse(BaseModel):
    led_count: int
    on: bool  # True if any pixel is lit
    color: list[int]  # [R, G, B] — actual pixel 0 from strip
    hex: str  # e.g. "#ff8800"
    brightness: float  # 0.0–1.0 derived from max channel
    effect: Optional[str]  # running effect name, or null
    scene: Optional[str]  # active scene name, or null


class LEDEffectRequest(BaseModel):
    effect: str = Field(
        ...,
        description="Effect name: breathing, candle, rainbow, notification_flash, pulse, blink",
    )
    color: Optional[list[int]] = Field(
        None, description="Base RGB color for the effect (default: current color)"
    )
    speed: float = Field(
        1.0,
        ge=0.1,
        le=5.0,
        description="Speed multiplier (0.1=slow, 1.0=normal, 5.0=fast)",
    )
    duration_ms: Optional[int] = Field(
        None, ge=100, le=60000, description="Auto-stop after duration (null=indefinite)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"effect": "breathing", "color": [255, 100, 0], "speed": 1.0},
                {"effect": "rainbow", "speed": 0.5},
                {
                    "effect": "notification_flash",
                    "color": [255, 0, 0],
                    "duration_ms": 3000,
                },
            ]
        }
    }


class LEDEffectResponse(BaseModel):
    status: str
    effect: str
    speed: float


class StatusResponse(BaseModel):
    status: str


class VolumeRequest(BaseModel):
    volume: int = Field(..., ge=0, le=100, description="Volume percentage 0-100")

    model_config = {"json_schema_extra": {"examples": [{"volume": 75}]}}


class AudioDevicesResponse(BaseModel):
    output_device: Optional[int]
    input_device: Optional[int]
    available: bool


class CameraInfoResponse(BaseModel):
    available: bool
    width: Optional[int]
    height: Optional[int]


class EmotionRequest(BaseModel):
    emotion: str = Field(
        ...,
        description="Emotion name: curious, happy, sad, thinking, idle, excited, shy, shock",
    )
    intensity: float = Field(0.7, ge=0.0, le=1.0, description="Intensity 0.0-1.0")

    model_config = {
        "json_schema_extra": {"examples": [{"emotion": "curious", "intensity": 0.8}]}
    }


class EmotionResponse(BaseModel):
    status: str
    emotion: str
    servo: Optional[str]
    led: Optional[list[int]]


class SceneRequest(BaseModel):
    scene: str = Field(
        ..., description="Scene name: reading, focus, relax, movie, night, energize"
    )

    model_config = {"json_schema_extra": {"examples": [{"scene": "reading"}]}}


class SceneResponse(BaseModel):
    status: str
    scene: str
    brightness: float
    color: list[int]


class SpeakRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=2000, description="Text to speak via TTS"
    )

    model_config = {
        "json_schema_extra": {"examples": [{"text": "Hi there! I am Lumi."}]}
    }


class MusicPlayRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=500, description="Song name or search query"
    )

    model_config = {
        "json_schema_extra": {"examples": [{"query": "Bohemian Rhapsody Queen"}]}
    }


class MusicStatusResponse(BaseModel):
    available: bool
    playing: bool
    title: Optional[str] = None


class VolumeResponse(BaseModel):
    control: str
    volume: int


class ServoPositionResponse(BaseModel):
    positions: dict[str, float]


class ServoDetail(BaseModel):
    id: int
    angle: Optional[float]
    online: bool
    error: Optional[str] = None


class ServoStatusResponse(BaseModel):
    servos: dict[str, ServoDetail]


class ServoAimRequest(BaseModel):
    direction: str = Field(
        ...,
        description="Named direction: desk, wall, left, right, up, down, center, user",
    )
    duration: float = Field(
        2.0, ge=0.0, le=10.0, description="Move duration in seconds (default: 2.0)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"direction": "desk"}, {"direction": "left", "duration": 3.0}]
        }
    }


class ServoAimResponse(BaseModel):
    status: str
    direction: str
    positions: dict[str, float]


class SceneListResponse(BaseModel):
    scenes: list[str]
    active: Optional[str]  # currently active scene name, or null


class PresenceResponse(BaseModel):
    state: str
    enabled: bool
    seconds_since_motion: int
    idle_timeout: int
    away_timeout: int


class FaceEnrollRequest(BaseModel):
    image_base64: str = Field(..., description="Base64-encoded image (JPEG or PNG)")
    label: str = Field(..., min_length=1, max_length=64, description="Person name")


class FaceEnrollResponse(BaseModel):
    status: str
    label: str
    photo_path: str
    enrolled_count: int


class FaceStatusResponse(BaseModel):
    enrolled_count: int
    enrolled_names: list[str]


class FacePersonDetail(BaseModel):
    label: str
    photo_count: int
    photos: list[str]  # filenames, e.g. ["1711929600000.jpg"]
    mood_days: list[str] = []  # e.g. ["2026-04-09"]
    files: list[str] = []  # all non-photo files


class FaceOwnersDetailResponse(BaseModel):
    enrolled_count: int
    persons: list[FacePersonDetail]


class FaceRemoveRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)


class FaceRemoveResponse(BaseModel):
    status: str
    label: str
    enrolled_count: int


class FaceResetResponse(BaseModel):
    status: str
    enrolled_count: int


class SensingResponse(BaseModel):
    running: bool
    poll_interval: float
    last_event_seconds_ago: dict[str, int]
    perceptions: list[dict]
    presence: dict


class DisplayStateResponse(BaseModel):
    mode: str
    hardware: bool
    available_expressions: list[str]


class VoiceStatusResponse(BaseModel):
    voice_available: bool
    voice_listening: bool
    tts_available: bool
    tts_speaking: bool
    tts_detail: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    servo: bool
    led: bool
    camera: bool
    audio: bool
    sensing: bool
    voice: bool
    tts: bool
    music: bool
    display: bool


class ServoMoveRequest(BaseModel):
    positions: dict[str, float] = Field(
        ...,
        description=(
            "Joint positions (degrees). Ordered by servo ID: "
            "base_yaw.pos (ID 1, min -90 max 90), "
            "base_pitch.pos (ID 2, min -90 max 90), "
            "elbow_pitch.pos (ID 3, min -90 max 90), "
            "wrist_roll.pos (ID 4, min -90 max 90), "
            "wrist_pitch.pos (ID 5, min -90 max 90). "
            "Values are clamped to safe limits automatically."
        ),
    )
    duration: float = Field(
        2.0,
        ge=0.0,
        le=10.0,
        description="Move duration in seconds. 0 = instant jump, >0 = smooth interpolation (default: 2.0)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "positions": {
                        "base_yaw.pos": 0.0,
                        "base_pitch.pos": 10.0,
                        "elbow_pitch.pos": -5.0,
                        "wrist_roll.pos": 0.0,
                        "wrist_pitch.pos": 0.0,
                    },
                    "_comment": "ID1 base_yaw [-90,90] | ID2 base_pitch [-90,90] | ID3 elbow_pitch [-90,90] | ID4 wrist_roll [-90,90] | ID5 wrist_pitch [-90,90]",
                },
                {
                    "positions": {"base_pitch.pos": 5.0, "elbow_pitch.pos": 5.0},
                    "duration": 3.0,
                },
            ]
        }
    }


class ServoMoveResponse(BaseModel):
    status: str
    requested: dict[str, float]
    clamped: dict[str, float]  # kept for API compat, same as requested
    duration: float
    errors: Optional[dict[str, str]] = None


class DisplayEyesRequest(BaseModel):
    expression: str = Field(
        ...,
        description="Expression: neutral, happy, sad, curious, thinking, excited, shy, shock, sleepy, angry, love",
    )
    pupil_x: float = Field(
        0.0, ge=-1.0, le=1.0, description="Pupil X: -1.0 (left) to 1.0 (right)"
    )
    pupil_y: float = Field(
        0.0, ge=-1.0, le=1.0, description="Pupil Y: -1.0 (up) to 1.0 (down)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"expression": "happy", "pupil_x": 0.0, "pupil_y": 0.0}]
        }
    }


class DisplayInfoRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=20, description="Main text (short, e.g. '14:30')"
    )
    subtitle: str = Field(
        "", max_length=40, description="Subtitle (e.g. 'Good afternoon')"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"text": "14:30", "subtitle": "Good afternoon"}]
        }
    }


class VoiceStartRequest(BaseModel):
    llm_api_key: str = Field(
        ..., min_length=1, description="OpenAI-compatible API key for TTS and STT"
    )
    llm_base_url: str = Field(
        ..., min_length=1, description="OpenAI-compatible base URL for TTS and STT"
    )
    deepgram_api_key: str = Field(
        "", description="Deepgram API key (optional, falls back to Autonomous STT)"
    )
    tts_voice: str = Field(
        "", description="TTS voice name (optional, defaults to config TTS_VOICE)"
    )


class VoiceConfigRequest(BaseModel):
    wake_words: list[str] = Field(..., min_length=1, description="Wake word list (lowercase matched)")
