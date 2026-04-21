"""
LeLamp presets — emotion, scene, and LED effect constants.

All pure data, no runtime dependencies. Import from server.py.
"""

# --- LED effect name constants ---
FX_BREATHING = "breathing"
FX_CANDLE = "candle"
FX_RAINBOW = "rainbow"
FX_NOTIFICATION_FLASH = "notification_flash"
FX_PULSE = "pulse"
FX_BLINK = "blink"
FX_SPEAKING_WAVE = "speaking_wave"

VALID_LED_EFFECTS = [FX_BREATHING, FX_CANDLE, FX_RAINBOW, FX_NOTIFICATION_FLASH, FX_PULSE, FX_BLINK, FX_SPEAKING_WAVE]

# --- Scene name constants ---
SCENE_READING = "reading"
SCENE_FOCUS = "focus"
SCENE_RELAX = "relax"
SCENE_MOVIE = "movie"
SCENE_NIGHT = "night"
SCENE_ENERGIZE = "energize"

# --- Aim direction constants ---
AIM_CENTER = "center"
AIM_DESK = "desk"
AIM_WALL = "wall"
AIM_LEFT = "left"
AIM_RIGHT = "right"
AIM_UP = "up"
AIM_DOWN = "down"
AIM_USER = "user"

# --- Emotion name constants ---
# Used as keys in EMOTION_PRESETS and for comparisons across the codebase.
# The string values are part of the HTTP API contract (SKILL.md).
EMO_CURIOUS = "curious"
EMO_HAPPY = "happy"
EMO_SAD = "sad"
EMO_THINKING = "thinking"
EMO_IDLE = "idle"
EMO_EXCITED = "excited"
EMO_SHY = "shy"
EMO_SHOCK = "shock"
EMO_LISTENING = "listening"
EMO_LAUGH = "laugh"
EMO_CONFUSED = "confused"
EMO_SLEEPY = "sleepy"
EMO_GREETING = "greeting"
EMO_GOODBYE = "goodbye"
EMO_CARING = "caring"
EMO_ACKNOWLEDGE = "acknowledge"
EMO_STRETCHING = "stretching"
EMO_MUSIC_STRONG = "music_strong"
EMO_MUSIC_CHILL = "music_chill"
EMO_SCAN = "scan"
EMO_NOD = "nod"
EMO_HEADSHAKE = "headshake"

# Emotion presets: maps emotion name to servo recording + LED color + optional LED effect.
# "effect" triggers a background LED animation; "color" is the base color for that effect.
# When no "effect" is set, LED is a simple solid fill.
# "camera": "off" = auto-disable camera (e.g. sleepy — lamp going to sleep)
# "camera": "on"  = auto-enable camera if off (active interaction, need vision)
# omitted         = no camera change
EMOTION_PRESETS = {
    EMO_CURIOUS:       {"servo": "curious",       "color": [255, 191, 0],   "effect": FX_BREATHING,          "speed": 1.0, "camera": "on"},
    EMO_HAPPY:         {"servo": "happy_wiggle",  "color": [255, 220, 0],   "effect": FX_CANDLE,             "speed": 1.0, "camera": "on"},
    EMO_SAD:           {"servo": "sad",           "color": [80, 80, 200],   "effect": FX_BREATHING,          "speed": 0.8, "camera": "on"},
    EMO_THINKING:      {"servo": "thinking_deep", "color": [180, 100, 255], "effect": FX_PULSE,              "speed": 0.5, "camera": "on"},
    EMO_IDLE:          {"servo": "idle",          "color": [183, 235, 234], "effect": FX_BREATHING,          "speed": 0.8},
    EMO_EXCITED:       {"servo": "excited",       "color": [230, 51, 230],  "effect": FX_BLINK,              "speed": 2.5, "camera": "on"},
    EMO_SHY:           {"servo": "shy",           "color": [255, 150, 180], "effect": FX_BLINK,              "speed": 0.5, "camera": "on"},
    EMO_SHOCK:         {"servo": "shock",         "color": [255, 255, 255], "effect": FX_NOTIFICATION_FLASH, "speed": 2.0, "camera": "on"},
    EMO_LISTENING:     {"servo": "listening",     "color": [51, 121, 230],  "effect": FX_PULSE,              "speed": 0.6, "camera": "on"},
    EMO_LAUGH:         {"servo": "laugh",         "color": [230, 191, 51],  "effect": FX_BLINK,              "speed": 1.2, "camera": "on"},
    EMO_CONFUSED:      {"servo": "confused",      "color": [224, 71, 25],   "effect": FX_CANDLE,             "speed": 0.6, "camera": "on"},
    EMO_SLEEPY:        {"servo": "sleepy",        "color": [60, 40, 120],   "effect": FX_BREATHING,          "speed": 0.5, "camera": "off"},
    EMO_GREETING:      {"servo": "greeting",      "color": [255, 180, 100], "effect": FX_BLINK,              "speed": 0.8, "camera": "on"},
    EMO_GOODBYE:       {"servo": "goodbye",       "color": [255, 180, 100], "effect": FX_BREATHING,          "speed": 0.5},
    EMO_CARING:        {"servo": "nod",           "color": [255, 160, 120], "effect": FX_BREATHING,          "speed": 0.4, "camera": "on"},
    EMO_ACKNOWLEDGE:   {"servo": "acknowledge",   "color": [51, 230, 141],  "effect": FX_BLINK,              "speed": 1.0, "camera": "on"},
    EMO_STRETCHING:    {"servo": "stretching",    "color": [245, 240, 230], "effect": FX_BREATHING,          "speed": 0.6, "camera": "on"},
    EMO_MUSIC_STRONG:  {"servo": "music_rock",    "color": [155, 221, 155], "effect": FX_RAINBOW,            "speed": 1.5},
    EMO_MUSIC_CHILL:   {"servo": "music_rock",    "color": [252, 136, 3],   "effect": FX_BREATHING,          "speed": 0.5},
    EMO_SCAN:          {"servo": "scanning",      "color": [36, 184, 224],  "effect": FX_PULSE,              "speed": 1.0, "camera": "on"},
    EMO_NOD:           {"servo": "nod",           "color": [51, 230, 141],  "effect": FX_BLINK,              "speed": 1.0, "camera": "on"},
    EMO_HEADSHAKE:     {"servo": "headshake",     "color": [230, 51, 51],   "effect": FX_BLINK,              "speed": 1.0, "camera": "on"},
}

# Lighting scene presets — simulated color temperature via RGB mixing.
# 2200K = very warm amber, 2700K = warm white, 4000K = neutral, 5000K = cool, 6500K = daylight
# "camera": "off" = auto-disable camera (idle scene, no vision needed)
# "camera": "on"  = auto-enable camera (active scene, vision useful)
# omitted          = no camera change
SCENE_PRESETS = {
    SCENE_READING:  {"brightness": 0.80, "color": [255, 225, 180], "aim": AIM_DESK, "camera": "off"},   # ~4000K neutral
    SCENE_FOCUS:    {"brightness": 1.00, "color": [235, 240, 255], "aim": AIM_DESK, "camera": "off"},   # ~5000K cool white
    SCENE_RELAX:    {"brightness": 0.40, "color": [255, 180, 100], "aim": AIM_WALL, "camera": "on"},    # ~2700K warm
    SCENE_MOVIE:    {"brightness": 0.15, "color": [255, 170, 80],  "aim": AIM_WALL, "camera": "off"},   # ~2700K dim amber
    SCENE_NIGHT:    {"brightness": 0.05, "color": [255, 140, 40],  "aim": AIM_DOWN, "camera": "off"},   # ~2200K very warm
    SCENE_ENERGIZE: {"brightness": 1.00, "color": [220, 235, 255], "aim": AIM_UP,   "camera": "on"},    # ~6500K daylight
}

# Servo aim presets — named lamp-head directions mapped to joint positions (normalized -100..100).
# Neutral: base_yaw=3, base_pitch=-30, elbow_pitch=57, wrist_roll=0, wrist_pitch=18
AIM_PRESETS = {
    AIM_CENTER: {"base_yaw.pos": 3.0,   "base_pitch.pos": -20.0, "elbow_pitch.pos": 32.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 0.0},
    AIM_DESK:   {"base_yaw.pos": 3.0,   "base_pitch.pos": 5.0,   "elbow_pitch.pos": 20.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": -40.0},
    AIM_WALL:   {"base_yaw.pos": 3.0,   "base_pitch.pos": 5.0,   "elbow_pitch.pos": 20.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 0.0},
    AIM_LEFT:   {"base_yaw.pos": -90.0, "base_pitch.pos": -30.0, "elbow_pitch.pos": 57.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 18.0},
    AIM_RIGHT:  {"base_yaw.pos": 90.0,  "base_pitch.pos": -30.0, "elbow_pitch.pos": 57.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 18.0},
    AIM_UP:     {"base_yaw.pos": 3.0,   "base_pitch.pos": 10.0,  "elbow_pitch.pos": 5.0,  "wrist_roll.pos": 0.0, "wrist_pitch.pos": 25.0},
    AIM_DOWN:   {"base_yaw.pos": 3.0,   "base_pitch.pos": -50.0, "elbow_pitch.pos": 60.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": -25.0},
    AIM_USER:   {"base_yaw.pos": 3.0,   "base_pitch.pos": -28.0, "elbow_pitch.pos": 55.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 22.0},
}
