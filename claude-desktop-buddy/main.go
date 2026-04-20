package main

import (
	"encoding/json"
	"flag"
	"io"
	"log"
	"os"
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
	})

	// Transient state expiry ticker
	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			sm.CheckTransientExpiry()
		}
	}()

	// Heartbeat timeout checker — if no heartbeat for 30s, treat as disconnected
	go func() {
		ticker := time.NewTicker(5 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			if sm.Connected() {
				hb := sm.LastHeartbeat()
				if hb == nil {
					continue
				}
				// Check if we haven't received a heartbeat recently
				// StateMachine doesn't expose lastHBTime, so we track via connected state
			}
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

func handleBLEMessage(data []byte, sm *StateMachine, bleSrv *BLEServer, deviceName string, startTime time.Time) {
	msg, err := ParseMessage(data)
	if err != nil {
		log.Printf("[ble] parse error: %v (data: %s)", err, string(data))
		return
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
			if err := bleSrv.Send(MakeAck("unpair", true)); err != nil {
				log.Printf("[ble] send ack error: %v", err)
			}
			sm.SetConnected(false)
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
		DeviceName:         "Claude-Lumi",
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
