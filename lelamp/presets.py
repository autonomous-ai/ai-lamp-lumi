"""
LeLamp presets — emotion, scene, and LED effect constants.

All pure data, no runtime dependencies. Import from server.py.
"""

# Valid LED effect names
VALID_LED_EFFECTS = ["breathing", "candle", "rainbow", "notification_flash", "pulse"]

# Emotion presets: maps emotion name to servo recording + LED color + optional LED effect.
# "effect" triggers a background LED animation; "color" is the base color for that effect.
# When no "effect" is set, LED is a simple solid fill.
EMOTION_PRESETS = {
    "curious":       {"servo": "curious",       "color": [255, 200, 80],  "effect": "pulse",              "speed": 1.2},
    "happy":         {"servo": "happy_wiggle",  "color": [255, 220, 0],   "effect": "pulse",              "speed": 1.5},
    "sad":           {"servo": "sad",           "color": [80, 80, 200],   "effect": "breathing",          "speed": 0.4},
    "thinking":      {"servo": "thinking_deep", "color": [180, 100, 255], "effect": "pulse",              "speed": 0.8},
    "idle":          {"servo": "idle",          "color": [100, 200, 220], "effect": "breathing",          "speed": 0.3},
    "excited":       {"servo": "excited",       "color": [255, 100, 0],   "effect": "rainbow",            "speed": 2.5},
    "shy":           {"servo": "shy",           "color": [255, 150, 180], "effect": "breathing",          "speed": 0.5},
    "shock":         {"servo": "shock",         "color": [255, 255, 255], "effect": "notification_flash", "speed": 3.0},
    "listening":     {"servo": "listening",     "color": [100, 180, 255], "effect": "breathing",          "speed": 0.6},
    "laugh":         {"servo": "laugh",         "color": [255, 200, 50],  "effect": "rainbow",            "speed": 2.0},
    "confused":      {"servo": "confused",      "color": [200, 150, 255], "effect": "pulse",              "speed": 0.8},
    "sleepy":        {"servo": "sleepy",        "color": [60, 40, 120],   "effect": "breathing",          "speed": 0.2},
    "greeting":      {"servo": "greeting",      "color": [255, 180, 100], "effect": "pulse",              "speed": 1.5},
    "acknowledge":   {"servo": "acknowledge",   "color": [100, 255, 150], "effect": "pulse",              "speed": 1.0},
    "stretching":    {"servo": "stretching",    "color": [255, 230, 180], "effect": "candle",             "speed": 0.6},
}

# Lighting scene presets — simulated color temperature via RGB mixing.
# 2200K = very warm amber, 2700K = warm white, 4000K = neutral, 5000K = cool, 6500K = daylight
SCENE_PRESETS = {
    "reading":  {"brightness": 0.80, "color": [255, 225, 180]},  # ~4000K neutral
    "focus":    {"brightness": 1.00, "color": [235, 240, 255]},  # ~5000K cool white
    "relax":    {"brightness": 0.40, "color": [255, 180, 100]},  # ~2700K warm
    "movie":    {"brightness": 0.15, "color": [255, 170, 80]},   # ~2700K dim amber
    "night":    {"brightness": 0.05, "color": [255, 140, 40]},   # ~2200K very warm
    "energize": {"brightness": 1.00, "color": [220, 235, 255]},  # ~6500K daylight
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
