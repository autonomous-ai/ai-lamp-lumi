package main

import (
	"encoding/json"
	"flag"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"gopkg.in/natefinch/lumberjack.v2"
)

// Config is loaded from buddy.json.
type Config struct {
	Enabled            bool   `json:"enabled"`
	DeviceName         string `json:"device_name"`
	HTTPPort           int    `json:"http_port"`
	LeLampURL          string `json:"lelamp_url"`
	LumiURL            string `json:"lumi_url"`
	ApprovalTimeoutSec int    `json:"approval_timeout_sec"`
}

func main() {
	configPath := flag.String("config", "/root/config/buddy.json", "path to config file")
	logPath := flag.String("log", "/var/log/lumi-buddy.log", "path to log file")
	flag.Parse()

	// Rotating log file: 2 MB per file, keep 10 backups (same as lumi)
	rotatingWriter := &lumberjack.Logger{
		Filename:   *logPath,
		MaxSize:    2, // MB
		MaxBackups: 10,
		MaxAge:     0,
		Compress:   false,
	}
	defer rotatingWriter.Close()
	log.SetOutput(io.MultiWriter(os.Stdout, rotatingWriter))
	log.SetFlags(log.Ldate | log.Ltime)

	cfg := loadConfig(*configPath)
	if !cfg.Enabled {
		log.Println("[buddy] disabled in config, exiting")
		return
	}

	cfg.DeviceName = resolveDeviceName(cfg.DeviceName, cfg.LumiURL)

	// Register a BlueZ agent so LE Secure Connections pairing can complete.
	// Without an agent, BlueZ rejects pairing requests and Claude Desktop's
	// Hardware Buddy picker won't see (or won't connect to) the device.
	if err := registerBluezAgent(); err != nil {
		log.Printf("[buddy] WARN: register agent failed: %v (pairing will likely fail)", err)
	}

	bridge := NewBridge(cfg.LeLampURL, cfg.LumiURL)
	startTime := time.Now()

	// State machine with bridge callback
	sm := NewStateMachine(bridge.OnStateChange)

	// BLE server — assign to package-level `ble` so the onMessage closure
	// captures the same variable the closure body dereferences. Using `:=`
	// here would shadow the package var and leave the closure seeing nil.
	ble = NewBLEServer(cfg.DeviceName, func(data []byte) {
		handleBLEMessage(data, sm, ble, cfg.DeviceName, startTime)
	}, func(connected bool) {
		sm.SetConnected(connected)
		if !connected {
			xfer.Abort()
		}
	})

	// Transient state expiry ticker
	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			sm.CheckTransientExpiry()
		}
	}()

	// HTTP server for OpenClaw skill
	httpSrv := NewHTTPServer(cfg.HTTPPort, sm, ble)
	go func() {
		if err := httpSrv.Start(); err != nil {
			log.Fatalf("[buddy] http server error: %v", err)
		}
	}()

	// Start BLE (blocking — advertising loop)
	log.Printf("[buddy] starting Claude Desktop Buddy plugin (%s)", cfg.DeviceName)
	log.Printf("[buddy] LeLamp: %s, Lumi: %s, HTTP: :%d", cfg.LeLampURL, cfg.LumiURL, cfg.HTTPPort)

	if err := ble.Start(); err != nil {
		log.Fatalf("[buddy] BLE start error: %v", err)
	}

	// Mark as connected once BLE is advertising
	// Actual connection detection happens via heartbeat receipt
	log.Println("[buddy] BLE advertising started, waiting for Claude Desktop connection...")

	// Keep main goroutine alive
	select {}
}

// ble is declared as package var so handleBLEMessage can reference it via closure
var ble *BLEServer

// xfer holds the single active folder-push transfer from Claude Desktop.
var xfer Transfer

func handleBLEMessage(data []byte, sm *StateMachine, bleSrv *BLEServer, deviceName string, startTime time.Time) {
	msg, lost, err := ParseOrSalvage(data)
	if err != nil {
		log.Printf("[ble] parse error: %v (data: %s)", err, string(data))
		return
	}
	if lost > 0 {
		// Claude Desktop writes BLE chunks via Write-Without-Response, which
		// has no ATT_CONFIRM, so BlueZ silently drops packets under load. When
		// that happens we salvage the tail of the line. The dropped bytes are
		// gone — affected file transfers will be incomplete but the session
		// stays alive for the remaining chunks.
		log.Printf("[ble] WARN: dropped %d corrupted prefix bytes (BLE packet loss)", lost)
		xfer.Abort()
	}

	switch m := msg.(type) {
	case *Heartbeat:
		// First heartbeat means Desktop is connected
		if !sm.Connected() {
			sm.SetConnected(true)
			log.Println("[ble] Claude Desktop connected")
		}
		sm.HandleHeartbeat(m)

	case *TimeSync:
		log.Printf("[ble] time sync: epoch=%d, offset=%d", m.Time[0], m.Time[1])
		// Ack not required for time sync (no cmd field)

	case *Command:
		log.Printf("[ble] command: %s", m.Cmd)
		switch m.Cmd {
		case "status":
			approved, denied := sm.ApprovalStats()
			resp := MakeStatusAck(deviceName, time.Since(startTime), approved, denied)
			if err := bleSrv.Send(resp); err != nil {
				log.Printf("[ble] send status ack error: %v", err)
			}
		case "owner":
			log.Printf("[ble] owner set to: %s", m.Name)
			if err := bleSrv.Send(MakeAck("owner", true)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
		case "name":
			log.Printf("[ble] name set to: %s", m.Name)
			if err := bleSrv.Send(MakeAck("name", true)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
		case "unpair":
			log.Println("[ble] unpair requested")
			xfer.Abort()
			if err := bleSrv.Send(MakeAck("unpair", true)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
			sm.SetConnected(false)

		// Folder-push streaming protocol — persist to disk under CharsRoot.
		case "char_begin":
			ok := true
			if err := xfer.Begin(m.Name, m.Total); err != nil {
				log.Printf("[xfer] begin error: %v", err)
				ok = false
			}
			if err := bleSrv.Send(MakeAck("char_begin", ok)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
		case "file":
			ok := true
			if err := xfer.StartFile(m.Path, m.Size); err != nil {
				log.Printf("[xfer] file error: %v", err)
				ok = false
			}
			if err := bleSrv.Send(MakeAck("file", ok)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
		case "chunk":
			n, err := xfer.WriteChunk(m.D)
			if err != nil {
				log.Printf("[xfer] chunk error: %v", err)
				if err := bleSrv.Send(MakeAckN("chunk", false, n)); err != nil {
					log.Printf("[ble] send ack error: %v", err)
				}
				break
			}
			if err := bleSrv.Send(MakeAckN("chunk", true, n)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
		case "file_end":
			n, err := xfer.EndFile()
			ok := err == nil
			if err != nil {
				log.Printf("[xfer] file_end error: %v", err)
			}
			if err := bleSrv.Send(MakeAckN("file_end", ok, n)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
		case "char_end":
			xfer.End()
			if err := bleSrv.Send(MakeAck("char_end", true)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}

		default:
			log.Printf("[ble] unknown command: %s", m.Cmd)
			if err := bleSrv.Send(MakeAck(m.Cmd, false)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
		}
	}
}

func loadConfig(path string) Config {
	cfg := Config{
		Enabled:            true,
		DeviceName:         "Claude-{deviceid}",
		HTTPPort:           5002,
		LeLampURL:          "http://127.0.0.1:5001",
		LumiURL:            "http://127.0.0.1:5000",
		ApprovalTimeoutSec: 30,
	}

	data, err := os.ReadFile(path)
	if err != nil {
		log.Printf("[buddy] config %s not found, using defaults", path)
		return cfg
	}

	if err := json.Unmarshal(data, &cfg); err != nil {
		log.Printf("[buddy] config parse error: %v, using defaults", err)
		return cfg
	}

	log.Printf("[buddy] loaded config from %s", path)
	return cfg
}

// resolveDeviceName expands the {deviceid} placeholder in name by fetching
// device_id from Lumi's /api/system/info. Buddy may start before Lumi is
// ready, so we retry transport errors for a short window. Names without
// the placeholder pass through untouched.
//
// The default uses a "Claude-" prefix because Claude Desktop's Hardware
// Buddy device picker filters scan results to names starting with "Claude"
// (per the BLE advertisement requirements at
// github.com/anthropics/claude-desktop-buddy). Renaming away from that
// prefix makes the device invisible in the official picker.
//
// {deviceid} is shortened to its trailing segment (last 4 chars after the
// last dash) so the resolved name fits in the 31-byte primary BLE
// advertisement alongside the 128-bit Nordic UART service UUID. With a
// long name the system pushes it to the scan response, which some
// scanners only fetch via active scan and may miss.
func resolveDeviceName(name, lumiURL string) string {
	if name == "" {
		name = "Claude-{deviceid}"
	}
	if !strings.Contains(name, "{deviceid}") {
		return name
	}

	id, reason := fetchDeviceID(lumiURL)
	switch {
	case id != "":
		log.Printf("[buddy] resolved device_id=%q from Lumi", id)
	case reason == "empty":
		log.Printf("[buddy] WARN: Lumi reachable at %s but device_id is empty — device not yet provisioned via /device/setup", lumiURL)
		id = "unknown"
	default:
		log.Printf("[buddy] WARN: failed to fetch device_id from %s after %d attempts (%s)",
			lumiURL, fetchAttempts, reason)
		id = "unknown"
	}
	short := shortDeviceID(id)
	if short != id {
		log.Printf("[buddy] shortened device_id %q → %q for BLE adv fit", id, short)
	}
	return strings.ReplaceAll(name, "{deviceid}", short)
}

// shortDeviceID returns a compact form of the device id suitable for the
// BLE local name. Takes the last dash-separated segment (e.g. "lumi-004"
// → "004"; "abc-def-12" → "12"; "abcdef" → "abcdef") and truncates to 4
// chars. The 4-char cap leaves room for the "Claude-" prefix plus the
// 128-bit Nordic UART UUID inside the 31-byte primary advertisement
// payload, so macOS picks up the name in passive scan without requiring
// a SCAN_REQ round-trip.
func shortDeviceID(id string) string {
	if id == "" {
		return "unk"
	}
	if i := strings.LastIndexByte(id, '-'); i >= 0 && i+1 < len(id) {
		id = id[i+1:]
	}
	if len(id) > 4 {
		id = id[len(id)-4:]
	}
	return id
}

const fetchAttempts = 15

// fetchDeviceID returns (id, reason). reason is one of:
//   "" on success, "empty" if Lumi answered with an empty device_id (not
//   provisioned), or a transport-level failure summary if all retries failed.
func fetchDeviceID(lumiURL string) (string, string) {
	client := &http.Client{Timeout: 3 * time.Second}
	url := lumiURL + "/api/system/info"
	var lastErr string
	for i := 0; i < fetchAttempts; i++ {
		id, ok, errStr := tryFetchDeviceID(client, url)
		if ok {
			if id == "" {
				return "", "empty"
			}
			return id, ""
		}
		lastErr = errStr
		time.Sleep(2 * time.Second)
	}
	if lastErr == "" {
		lastErr = "unknown error"
	}
	return "", lastErr
}

// tryFetchDeviceID returns (id, ok, errStr). ok=true means Lumi answered with
// a parseable response (id may still be empty if device_id is unset). ok=false
// means transport/decode failure — caller should retry.
func tryFetchDeviceID(client *http.Client, url string) (string, bool, string) {
	resp, err := client.Get(url)
	if err != nil {
		return "", false, "http: " + err.Error()
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", false, "http " + resp.Status
	}
	var wrap struct {
		Data struct {
			DeviceID string `json:"deviceId"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&wrap); err != nil {
		return "", false, "decode: " + err.Error()
	}
	return wrap.Data.DeviceID, true, ""
}
