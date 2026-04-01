# Plan: Face Enroll via Telegram Chat

## Context
Lumi's FaceRecognizer (`facerecognizer.py`) has `train()` and `reset_owners()` but they're never called — all faces are classified as strangers. We need a way for users to send a selfie via Telegram + tag someone → enroll that face for recognition.

Inspired by doggi-sdk's approach: save original JPEG photos per person, re-train from photos on startup.

## Flow
```
User sends photo + @mention via Telegram
  → OpenClaw AI receives image (mediaPaths) + extracts name from @mention
  → AI: curl POST http://127.0.0.1:5001/face/enroll  {image_base64, label}
  → LeLamp saves JPEG to data/owner_photos/{label}/
  → LeLamp trains FaceRecognizer with the image
  → On startup: LeLamp scans owner_photos/ dir → re-trains all
```

## Changes

### 1. `lelamp/service/sensing/sensing_service.py`
- Keep named `self._face_recognizer` reference (currently anonymous in `_perceptions` list)
- On init after creating FaceRecognizer, call `self._face_recognizer.load_from_disk()` to re-train from saved photos

### 2. `lelamp/service/sensing/perceptions/facerecognizer.py`
- Add constant `OWNER_PHOTOS_DIR = Path(os.environ.get("LELAMP_DATA_DIR", "/root/lelamp/data")) / "owner_photos"`
- Add `save_photo(image_bytes: bytes, label: str) -> str`:
  - Create dir `{OWNER_PHOTOS_DIR}/{label}/`
  - Save JPEG with timestamp filename
  - Return saved path
- Add `load_from_disk() -> int`:
  - Scan `OWNER_PHOTOS_DIR` subdirectories
  - For each subdir (= label): read all JPEGs, call `train(images, [label]*n)`
  - Return total owner count
  - Log result
- Add `remove_owner(label: str)`:
  - Delete `{OWNER_PHOTOS_DIR}/{label}/` directory
  - Call `reset_owners()` then `load_from_disk()` to re-train without that person
- Add `owner_count() -> int` and `owner_names() -> list[str]`
- Modify `reset_owners()`: also delete all photos from disk

### 3. `lelamp/server.py`
- Add Pydantic models: `FaceEnrollRequest(image_base64, label)`, `FaceEnrollResponse`, `FaceStatusResponse`
- `POST /face/enroll` — decode base64 → save photo → train → return status
- `POST /face/reset` — clear all owner photos + embeddings
- `POST /face/remove` — remove specific owner by label
- `GET /face/status` — return owner_count + owner_names
- All endpoints guard on `sensing_service` and `sensing_service._face_recognizer`

### 4. `lumi/resources/openclaw-skills/face-enroll/SKILL.md`
- New skill file instructing OpenClaw AI:
  - Trigger: user sends photo + "add owner" / @mention / "remember this face"
  - Extract name from @mention or ask user
  - base64 encode photo from mediaPaths
  - curl POST /face/enroll to LeLamp
  - Confirm to user with owner_count
  - Also handle: "who do you recognize?" → GET /face/status
  - Also handle: "forget face" / "reset faces" → POST /face/remove or /face/reset

### 5. `lumi/internal/openclaw/onboarding.go`
- Add `"face-enroll"` to the skills download list (~line 38-50)

## File list
- `lelamp/service/sensing/perceptions/facerecognizer.py` — persistence + photo storage
- `lelamp/service/sensing/sensing_service.py` — named reference + load on init
- `lelamp/server.py` — HTTP endpoints
- `lumi/resources/openclaw-skills/face-enroll/SKILL.md` — new skill (new file)
- `lumi/internal/openclaw/onboarding.go` — register skill

## Storage
```
/root/lelamp/data/owner_photos/
├── alice/
│   ├── 1711929600000.jpg
│   ├── 1711929601000.jpg
│   └── 1711929602000.jpg
└── bob/
    └── 1711929610000.jpg
```

## Verification
1. Start LeLamp with sensing enabled
2. `curl POST /face/enroll` with a base64 selfie + label → check 200 + photo saved to disk
3. `curl GET /face/status` → verify owner_count = 1
4. Restart LeLamp → `GET /face/status` → still shows owner (re-trained from disk)
5. Via Telegram: send photo + tag → AI calls enroll → confirm face recognized next time camera sees that person
6. `curl POST /face/reset` → owner_photos/ emptied, owner_count = 0
