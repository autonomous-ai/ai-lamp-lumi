# Vision Tracking — Theo doi vat the bang servo

Lumi co the theo doi va huong theo bat ky vat the nao ma nguoi dung mo ta bang ngon ngu tu nhien. He thong su dung cach tiep can hybrid: LLM vision de phat hien ban dau, OpenCV tracker de bam theo real-time.

## Kien truc

```
User: "Lumi, nhin theo tay minh di"
         |
    OpenClaw Agent (hieu y dinh)
         |
    1. Chup snapshot → LLM vision → bounding box [x, y, w, h]
         |
    2. POST /servo/track {bbox, target}
         |
    3. TrackerService (vong lap nen @ 10 FPS)
         |  lay frame → OpenCV CSRT update → pixel offset → nudge servo
         |
    4. Vat di chuyen → servo bam theo
         |
    5. Mat target → tu dong re-detect hoac dung
```

### Tai sao hybrid?

| Cach tiep can | Toc do | Linh hoat | Van de |
|---------------|--------|-----------|--------|
| Chi LLM vision | ~1-2s/frame | Bat ky vat nao | Qua cham de tracking |
| Chi YOLO/ML | ~30ms/frame | Chi cac class co dinh | Khong track duoc "cai ly xanh ben trai" |
| **Hybrid** | **~100ms/frame** | **Bat ky vat nao** | — |

LLM xu ly phan "cai gi" (ngon ngu tu nhien → bounding box). OpenCV xu ly phan "o dau" (vi tri real-time).

## Thanh phan

### TrackerService (`lelamp/service/tracking/tracker_service.py`)

Engine tracking chinh. Quan ly mot phien tracking duy nhat.

**Vong doi:**
1. `start(bbox, target_label, camera, servo)` — khoi tao OpenCV tracker tren bbox
2. Thread nen chay o `TRACK_FPS` (mac dinh 10)
3. Moi frame: update tracker → tinh offset tu tam frame → nudge servo
4. `stop()` — ket thuc phien, tiep tuc animation idle

**Dieu khien servo khi tracking:**
- Bat `_hold_mode = True` de chan cac animation idle/ambient
- Nudge `base_yaw` va `base_pitch` truc tiep qua `move_to()` (bo qua HTTP de nhanh hon)
- Tat hold mode khi dung

**Tu dong dung:** Tracker mat target trong `MAX_LOST_FRAMES` (15 frame = ~1.5s) → tu dong dung.

### Chuyen doi Pixel sang Do (Degree)

```
Tam frame: (320, 240) cho 640x480
Tam vat the: (cx, cy) tu tracker bbox
Offset: dx = cx - 320, dy = cy - 240

yaw_degrees  = -dx * DEG_PER_PX_YAW   (mac dinh 0.08 deg/px)
pitch_degrees = -dy * DEG_PER_PX_PITCH  (mac dinh 0.08 deg/px)
```

**Cac hang so can chinh** (dau file `tracker_service.py`):

| Hang so | Mac dinh | Mo ta |
|---------|----------|-------|
| `DEG_PER_PX_YAW` | 0.08 | Do moi pixel ngang. ~60 do FOV / 640px |
| `DEG_PER_PX_PITCH` | 0.08 | Do moi pixel doc |
| `DEAD_ZONE_PX` | 20 | Bo qua offset nho hon gia tri nay (chong rung) |
| `MAX_NUDGE_DEG` | 10.0 | Do toi da moi buoc nudge (chong giat manh) |
| `TRACK_FPS` | 10 | Tan suat vong lap tracking |
| `MAX_LOST_FRAMES` | 15 | So frame mat truoc khi tu dong dung (~1.5s o 10 FPS) |
| `NUDGE_DURATION` | 0.15 | Thoi gian di chuyen servo moi buoc (giay) |

Cac gia tri nay can calibrate tren Pi + camera thuc te.

## API Endpoints

Tat ca duoi `/servo/track`.

### POST /servo/track — Bat dau tracking

```json
// Request
{
  "bbox": [200, 150, 80, 100],  // [x, y, w, h] bang pixel tren frame 640x480
  "target": "ly nuoc"           // nhan mo ta (tuy chon)
}

// Response
{
  "status": "ok",
  "tracking": true,
  "target": "ly nuoc",
  "bbox": [200, 150, 80, 100]
}
```

### DELETE /servo/track — Dung tracking

```json
// Response
{"status": "ok", "tracking": false}
```

### GET /servo/track — Kiem tra trang thai

```json
// Response
{
  "status": "ok",
  "tracking": true,
  "target": "ly nuoc",
  "bbox": [210, 155, 78, 98]  // bbox cap nhat tu frame cuoi
}
```

### PUT /servo/track — Khoi tao lai bbox

Dung khi LLM phat hien lai vat the sau khi tracker mat.

```json
// Request
{
  "bbox": [250, 160, 75, 95],
  "target": "ly nuoc"
}
```

## Luong End-to-End

### Truong hop thanh cong

```
1. User: "Lumi, nhin theo cai ly nuoc"
2. OpenClaw agent:
   a. Goi /camera/snapshot → lay frame
   b. Gui frame cho LLM: "Tim cai ly nuoc, tra ve bounding box [x, y, w, h]"
   c. LLM tra ve: [200, 150, 80, 100]
   d. Goi POST /servo/track {"bbox": [200,150,80,100], "target": "ly nuoc"}
3. TrackerService bam theo ly nuoc real-time
4. User: "Thoi di" → agent goi DELETE /servo/track
```

### Re-detect khi mat target

```
1. TrackerService mat target (MAX_LOST_FRAMES dat) → tracking dung
2. Agent co the:
   a. Thong bao user: "Minh mat cai ly roi"
   b. Hoac tu dong re-detect: snapshot → LLM → bbox moi → POST /servo/track
```

### Re-detect trong khi dang tracking (PUT)

```
1. Dang tracking nhung do chinh xac giam dan
2. Agent chup snapshot → LLM → bbox moi → PUT /servo/track
3. Tracker khoi tao lai ma khong dung phien
```

## Lua chon OpenCV Tracker

**Chinh: CSRT** (Channel and Spatial Reliability Tracker)
- Do chinh xac tot, xu ly duoc bi che 1 phan
- ~20-30ms/frame tren Pi 5
- Can `opencv-contrib-python`

**Du phong: KCF** (Kernelized Correlation Filters)
- Nhanh hon nhung kem chinh xac
- Co san trong `opencv-python` co ban
- Tu dong chon neu CSRT khong co

## Phu thuoc

- `opencv-python>=4.8.0` (da co trong `pyproject.toml`)
- Cho CSRT: can `opencv-contrib-python` (thay the `opencv-python` trong pyproject.toml)
- Khong can them ML model nao

## Tuong tac voi cac he thong khac

| He thong | Khi dang tracking | Sau tracking |
|----------|-------------------|--------------|
| Servo idle animation | Bi chan (`_hold_mode`) | Tiep tuc |
| Sensing (face, motion) | Tiep tuc — chia se camera | Tiep tuc |
| Emotion animations | Bi chan boi hold mode | Tiep tuc |
| Camera freeze (snapshot) | Tracker dung `last_frame`, khong anh huong | N/A |
| TTS | Tiep tuc binh thuong | Tiep tuc binh thuong |

## Huong dan Calibrate

Sau khi deploy len Pi:

1. **Test vat co dinh**: Dat vat o tam frame. Bat tracking. Vat nen giu nguyen o trung tam — servo khong nen di chuyen.

2. **Test offset**: Dat vat o ria frame. Servo nen nudge ve phia vat. Neu qua cham → tang `DEG_PER_PX_*`. Neu vuot qua → giam.

3. **Test di chuyen**: Tu tu di chuyen vat. Servo nen bam theo muot. Neu giat → tang `NUDGE_DURATION`. Neu lag → giam `NUDGE_DURATION` hoac tang `TRACK_FPS`.

4. **Test huong yaw**: Di chuyen vat sang phai trong frame. Servo nen quay phai. Neu nguoc → doi dau trong `_nudge_servo`.

5. **Test huong pitch**: Di chuyen vat xuong duoi. Servo pitch nen nghieng xuong. Kiem tra dau tuong tu.

## Cai tien trong tuong lai

- **PID control** thay vi chi proportional nudge
- **Tracking du doan** — du doan huong di chuyen khi vat roi khoi ria frame
- **Nhieu vat the** — track nhieu vat, chuyen doi giua chung
- **Nguong confidence** — dung diem confidence cua tracker de re-detect truoc khi mat hoan toan
- **Thich ung frame-rate** — giam TRACK_FPS khi CPU cao, tang khi load thap
