# MQTT — Documentation

## Overview

Lumi uses MQTT to communicate with the backend server (status reporting, OTA commands, channel management).

- Client: Eclipse Paho autopaho (Go)
- Auto-reconnect on connection loss
- Client ID format: `lumi-device-{DeviceID}`

## Configuration

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

| Topic | Direction | Description |
|-------|-----------|-------------|
| `fa_channel` | Server → Device | Commands from backend (from-agent) |
| `fd_channel` | Device → Server | Responses from device (for-device) |

## Commands

### Envelope Format

```json
{
  "cmd": "info|add_channel|ota",
  ...payload fields
}
```

### `info` — Report device information

**Receive:** `{"cmd": "info"}`

**Response (publish fd_channel):**
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

### `add_channel` — Add messaging channel

**Receive:**
```json
{
  "cmd": "add_channel",
  "channel_type": "telegram|slack",
  "channel_id": "...",
  "channel_token": "..."
}
```

**Response:**
```json
{
  "device": "ai-lamp",
  "type": "add_channel",
  "status": "ok|error",
  "error": "..."
}
```

### `ota` — Trigger OTA update

Handled by bootstrap worker, not through MQTT handler directly.

## Code

| File | Role |
|------|------|
| `lumi/lib/mqtt/client.go` | MQTT client (connect, subscribe, publish) |
| `lumi/lib/mqtt/config.go` | Config struct |
| `lumi/lib/mqtt/options.go` | Connection options |
| `lumi/lib/mqtt/factory.go` | Factory to create client with unique ID |
| `lumi/server/device/delivery/mqtt/handler.go` | Command dispatcher |
| `lumi/server/device/delivery/mqtt/info_handler.go` | Handle `info` command |
| `lumi/server/device/delivery/mqtt/add_channel_hander.go` | Handle `add_channel` command |
| `lumi/domain/device.go` | MQTTMessage, command constants |
