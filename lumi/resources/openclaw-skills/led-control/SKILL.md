# LED Control

You have access to an LED ring on this device via the intern-server API at `http://127.0.0.1:5000`.

## When to change LED state

- Set **thinking** when you start processing a user message.
- Set **working** when you are executing a command, writing files, or doing any real work.
- Set **idle** when you are done and waiting for the next message.
- Set **error** when something went wrong.

## API

Base URL: `http://127.0.0.1:5000`

### Set LED state

```
POST /api/led
Content-Type: application/json

{"state": "<state>"}
```

Accepted states: `thinking`, `working`, `idle`, `error`, `booting`, `connectionmode`.

Example — set thinking:

```bash
curl -s -X POST http://127.0.0.1:5000/api/led \
  -H "Content-Type: application/json" \
  -d '{"state": "thinking"}'
```

Response: `{"state": "thinking"}`

### Get current LED state

```
GET /api/led
```

Response: `{"state": "idle"}`

## State reference

| State            | Color          | Effect               |
|------------------|----------------|----------------------|
| `thinking`       | Purple         | Rotating spot        |
| `working`        | Blue           | Gentle pulse         |
| `idle`           | Cyan           | Breath               |
| `error`          | Red            | Fast blink           |
| `booting`        | Green          | Breath               |
| `connectionmode` | Orange         | Blink                |

## Auto-rollback

The LED engine automatically rolls back to `idle` after:

- `thinking`: 30 seconds
- `working`: 10 seconds
- `error`: 10 seconds

So you don't need to manually reset to idle after these states — but you can if you want immediate feedback.
