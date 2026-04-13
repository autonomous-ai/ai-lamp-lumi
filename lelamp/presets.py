"""
LeLamp presets — emotion, scene, and LED effect constants.

All pure data, no runtime dependencies. Import from server.py.
"""

# Valid LED effect names
VALID_LED_EFFECTS = ["breathing", "candle", "rainbow", "notification_flash", "pulse", "blink"]

# Emotion presets: maps emotion name to servo recording + LED color + optional LED effect.
# "effect" triggers a background LED animation; "color" is the base color for that effect.
# When no "effect" is set, LED is a simple solid fill.
EMOTION_PRESETS = {
    "curious":       {"servo": "curious",       "color": [255, 191, 0],   "effect": "breathing",          "speed": 1.0},
    "happy":         {"servo": "happy_wiggle",  "color": [255, 220, 0],   "effect": "candle",             "speed": 1.0},
    "sad":           {"servo": "sad",           "color": [80, 80, 200],   "effect": "breathing",          "speed": 0.8},
    "thinking":      {"servo": "thinking_deep", "color": [180, 100, 255], "effect": "pulse",              "speed": 0.5},
    "idle":          {"servo": "idle",          "color": [183, 235, 234], "effect": "breathing",          "speed": 0.8},
    "excited":       {"servo": "excited",       "color": [230, 51, 230],  "effect": "blink",              "speed": 2.5},
    "shy":           {"servo": "shy",           "color": [255, 150, 180], "effect": "blink",              "speed": 0.5},
    "shock":         {"servo": "shock",         "color": [255, 255, 255], "effect": "notification_flash", "speed": 2.0},
    "listening":     {"servo": "listening",     "color": [51, 121, 230],  "effect": "pulse",              "speed": 0.6},
    "laugh":         {"servo": "laugh",         "color": [230, 191, 51],  "effect": "blink",              "speed": 1.2},
    "confused":      {"servo": "confused",      "color": [200, 150, 255], "effect": "candle",             "speed": 0.6},
    "sleepy":        {"servo": "sleepy",        "color": [60, 40, 120],   "effect": "breathing",          "speed": 0.5},
    "greeting":      {"servo": "greeting",      "color": [255, 180, 100], "effect": "blink",              "speed": 0.8},
    "goodbye":       {"servo": "goodbye",       "color": [255, 180, 100], "effect": "breathing",          "speed": 0.5},
    "caring":        {"servo": "nod",           "color": [255, 160, 120], "effect": "breathing",          "speed": 0.4},
    "acknowledge":   {"servo": "acknowledge",   "color": [100, 255, 150], "effect": "blink",              "speed": 1.0},
    "stretching":    {"servo": "stretching",    "color": [255, 230, 180], "effect": "breathing",          "speed": 0.6},
    "music_strong":  {"servo": "music_rock",    "color": [155, 221, 155], "effect": "rainbow",            "speed": 1.5},
    "music_chill":   {"servo": "music_rock",    "color": [252, 136, 3],   "effect": "breathing",          "speed": 0.5},
    "scan":          {"servo": "scanning",      "color": [155, 221, 155], "effect": "pulse",              "speed": 1.0},
    "nod":           {"servo": "nod",           "color": [51, 230, 141],  "effect": "blink",              "speed": 1.0},
    "headshake":     {"servo": "headshake",     "color": [230, 51, 51],   "effect": "blink",              "speed": 1.0},
}

# Lighting scene presets — simulated color temperature via RGB mixing.
# 2200K = very warm amber, 2700K = warm white, 4000K = neutral, 5000K = cool, 6500K = daylight
SCENE_PRESETS = {
    "reading":  {"brightness": 0.80, "color": [255, 225, 180], "aim": "desk"},   # ~4000K neutral
    "focus":    {"brightness": 1.00, "color": [235, 240, 255], "aim": "desk"},   # ~5000K cool white
    "relax":    {"brightness": 0.40, "color": [255, 180, 100], "aim": "wall"},   # ~2700K warm
    "movie":    {"brightness": 0.15, "color": [255, 170, 80],  "aim": "wall"},   # ~2700K dim amber
    "night":    {"brightness": 0.05, "color": [255, 140, 40],  "aim": "down"},   # ~2200K very warm
    "energize": {"brightness": 1.00, "color": [220, 235, 255], "aim": "up"},     # ~6500K daylight
}

# Servo aim presets — named lamp-head directions mapped to joint positions (normalized -100..100).
# Neutral: base_yaw=3, base_pitch=-30, elbow_pitch=57, wrist_roll=0, wrist_pitch=18
AIM_PRESETS = {
    "center":  {"base_yaw.pos": 3.0,   "base_pitch.pos": -20.0, "elbow_pitch.pos": 32.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 0.0},
    "desk":    {"base_yaw.pos": 3.0,   "base_pitch.pos": 5.0,   "elbow_pitch.pos": 20.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": -40.0},
    "wall":    {"base_yaw.pos": 3.0,   "base_pitch.pos": 5.0,   "elbow_pitch.pos": 20.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 0.0},
    "left":    {"base_yaw.pos": -90.0, "base_pitch.pos": -30.0, "elbow_pitch.pos": 57.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 18.0},
    "right":   {"base_yaw.pos": 90.0,  "base_pitch.pos": -30.0, "elbow_pitch.pos": 57.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 18.0},
    "up":      {"base_yaw.pos": 3.0,   "base_pitch.pos": 10.0,  "elbow_pitch.pos": 5.0,  "wrist_roll.pos": 0.0, "wrist_pitch.pos": 25.0},
    "down":    {"base_yaw.pos": 3.0,   "base_pitch.pos": -50.0, "elbow_pitch.pos": 60.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": -25.0},
    "user":    {"base_yaw.pos": 3.0,   "base_pitch.pos": -28.0, "elbow_pitch.pos": 55.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 22.0},
}
