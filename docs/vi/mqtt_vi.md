# MQTT — Tài Liệu

## Tổng Quan

Lumi sử dụng MQTT để giao tiếp với backend server (báo cáo trạng thái, nhận lệnh OTA, thêm channel).

- Client: Eclipse Paho autopaho (Go)
- Auto-reconnect khi mất kết nối
- Client ID format: `lumi-device-{DeviceID}`

## Cấu Hình

```json
// config/config.json
{
  "mqtt_endpoint": "broker.example.com",
  "mqtt_port": 8883,
  "mqtt_username": "...",
  "mqtt_password": "...",
  "fa_channel": "fa/{device_id}",
  "fd_channel": "fd/{device_id}"
}
```

## Topics

| Topic | Hướng | Mô tả |
|-------|-------|-------|
| `fa_channel` | Server → Device | Lệnh từ backend (from-agent) |
| `fd_channel` | Device → Server | Phản hồi từ thiết bị (for-device) |

## Commands

### Envelope Format

```json
{
  "cmd": "info|add_channel|ota",
  ...payload fields
}
```

### `info` — Báo cáo thông tin thiết bị

**Nhận:** `{"cmd": "info"}`

**Phản hồi (publish fd_channel):**
```json
{
  "device": "ai-lamp",
  "type": "info",
  "version": "0.0.35",
  "id": "{DeviceID}",
  "mac": "{MAC address}",
  "time": "2026-03-26T17:00:00Z"
}
```

### `add_channel` — Thêm messaging channel

**Nhận:**
```json
{
  "cmd": "add_channel",
  "channel_type": "telegram|slack",
  "channel_id": "...",
  "channel_token": "..."
}
```

**Phản hồi:**
```json
{
  "device": "ai-lamp",
  "type": "add_channel",
  "status": "ok|error",
  "error": "..."
}
```

### `ota` — Trigger OTA update

Xử lý bởi bootstrap worker, không qua MQTT handler trực tiếp.

## Code

| File | Vai trò |
|------|---------|
| `lumi/lib/mqtt/client.go` | MQTT client (connect, subscribe, publish) |
| `lumi/lib/mqtt/config.go` | Config struct |
| `lumi/lib/mqtt/options.go` | Connection options |
| `lumi/lib/mqtt/factory.go` | Factory tạo client với unique ID |
| `lumi/server/device/delivery/mqtt/handler.go` | Command dispatcher |
| `lumi/server/device/delivery/mqtt/info_handler.go` | Handle `info` command |
| `lumi/server/device/delivery/mqtt/add_channel_hander.go` | Handle `add_channel` command |
| `lumi/domain/device.go` | MQTTMessage, command constants |
