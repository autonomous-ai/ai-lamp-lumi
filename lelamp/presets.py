"""
LeLamp presets — emotion, scene, and LED effect constants.

All pure data, no runtime dependencies. Import from server.py.
"""

# Valid LED effect names
VALID_LED_EFFECTS = ["breathing", "candle", "rainbow", "notification_flash", "pulse", "blink", "speaking_wave"]

# Emotion presets: maps emotion name to servo recording + LED color + optional LED effect.
# "effect" triggers a background LED animation; "color" is the base color for that effect.
# When no "effect" is set, LED is a simple solid fill.
# "camera": "off" = auto-disable camera (e.g. sleepy — lamp going to sleep)
# "camera": "on"  = auto-enable camera if off (active interaction, need vision)
# omitted         = no camera change
EMOTION_PRESETS = {
    "curious":       {"servo": "curious",       "color": [255, 191, 0],   "effect": "breathing",          "speed": 1.0, "camera": "on"},
    "happy":         {"servo": "happy_wiggle",  "color": [255, 220, 0],   "effect": "candle",             "speed": 1.0, "camera": "on"},
    "sad":           {"servo": "sad",           "color": [80, 80, 200],   "effect": "breathing",          "speed": 0.8, "camera": "on"},
    "thinking":      {"servo": "thinking_deep", "color": [180, 100, 255], "effect": "pulse",              "speed": 0.5, "camera": "on"},
    "idle":          {"servo": "idle",          "color": [183, 235, 234], "effect": "breathing",          "speed": 0.8},
    "excited":       {"servo": "excited",       "color": [230, 51, 230],  "effect": "blink",              "speed": 2.5, "camera": "on"},
    "shy":           {"servo": "shy",           "color": [255, 150, 180], "effect": "blink",              "speed": 0.5, "camera": "on"},
    "shock":         {"servo": "shock",         "color": [255, 255, 255], "effect": "notification_flash", "speed": 2.0, "camera": "on"},
    "listening":     {"servo": "listening",     "color": [51, 121, 230],  "effect": "pulse",              "speed": 0.6, "camera": "on"},
    "laugh":         {"servo": "laugh",         "color": [230, 191, 51],  "effect": "blink",              "speed": 1.2, "camera": "on"},
    "confused":      {"servo": "confused",      "color": [224, 71, 25],   "effect": "candle",             "speed": 0.6, "camera": "on"},
    "sleepy":        {"servo": "sleepy",        "color": [60, 40, 120],   "effect": "breathing",          "speed": 0.5, "camera": "off"},
    "greeting":      {"servo": "greeting",      "color": [255, 180, 100], "effect": "blink",              "speed": 0.8, "camera": "on"},
    "goodbye":       {"servo": "goodbye",       "color": [255, 180, 100], "effect": "breathing",          "speed": 0.5},
    "caring":        {"servo": "nod",           "color": [255, 160, 120], "effect": "breathing",          "speed": 0.4, "camera": "on"},
    "acknowledge":   {"servo": "acknowledge",   "color": [51, 230, 141],  "effect": "blink",              "speed": 1.0, "camera": "on"},
    "stretching":    {"servo": "stretching",    "color": [245, 240, 230], "effect": "breathing",          "speed": 0.6, "camera": "on"},
    "music_strong":  {"servo": "music_rock",    "color": [155, 221, 155], "effect": "rainbow",            "speed": 1.5},
    "music_chill":   {"servo": "music_rock",    "color": [252, 136, 3],   "effect": "breathing",          "speed": 0.5},
    "scan":          {"servo": "scanning",      "color": [36, 184, 224],  "effect": "pulse",              "speed": 1.0, "camera": "on"},
    "nod":           {"servo": "nod",           "color": [51, 230, 141],  "effect": "blink",              "speed": 1.0, "camera": "on"},
    "headshake":     {"servo": "headshake",     "color": [230, 51, 51],   "effect": "blink",              "speed": 1.0, "camera": "on"},
}

# Lighting scene presets — simulated color temperature via RGB mixing.
# 2200K = very warm amber, 2700K = warm white, 4000K = neutral, 5000K = cool, 6500K = daylight
# "camera": "off" = auto-disable camera (idle scene, no vision needed)
# "camera": "on"  = auto-enable camera (active scene, vision useful)
# omitted          = no camera change
SCENE_PRESETS = {
    "reading":  {"brightness": 0.80, "color": [255, 225, 180], "aim": "desk", "camera": "off"},   # ~4000K neutral
    "focus":    {"brightness": 1.00, "color": [235, 240, 255], "aim": "desk", "camera": "off"},   # ~5000K cool white
    "relax":    {"brightness": 0.40, "color": [255, 180, 100], "aim": "wall", "camera": "on"},    # ~2700K warm
    "movie":    {"brightness": 0.15, "color": [255, 170, 80],  "aim": "wall", "camera": "off"},   # ~2700K dim amber
    "night":    {"brightness": 0.05, "color": [255, 140, 40],  "aim": "down", "camera": "off"},   # ~2200K very warm
    "energize": {"brightness": 1.00, "color": [220, 235, 255], "aim": "up",   "camera": "on"},    # ~6500K daylight
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
