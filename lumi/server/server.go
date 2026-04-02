package server

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"log"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/ambient"
	"go-lamp.autonomous.ai/internal/device"
	"go-lamp.autonomous.ai/internal/healthwatch"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/internal/resetbutton"
	"go-lamp.autonomous.ai/internal/statusled"
	"go-lamp.autonomous.ai/lib/mqtt"
	"go-lamp.autonomous.ai/lib/safego"
	"go-lamp.autonomous.ai/server/config"
	"go-lamp.autonomous.ai/server/serializers"
	_deviceGPIODeliver "go-lamp.autonomous.ai/server/device/delivery/gpio"
	_deviceHttpDeliver "go-lamp.autonomous.ai/server/device/delivery/http"
	_deviceMQTTDeliver "go-lamp.autonomous.ai/server/device/delivery/mqtt"
	_healthHttpDeliver "go-lamp.autonomous.ai/server/health/delivery/http"
	_networkHttpDeliver "go-lamp.autonomous.ai/server/network/delivery/http"
	_openclawSseDeliver "go-lamp.autonomous.ai/server/openclaw/delivery/sse"
	_sensingHttpDeliver "go-lamp.autonomous.ai/server/sensing/delivery/http"
)

type Server struct {
	engine *gin.Engine
	config *config.Config

	// handlers
	healthHandler     _healthHttpDeliver.HealthHandler
	networkHandler    _networkHttpDeliver.NetworkHandler
	deviceHandler     _deviceHttpDeliver.DeviceHandler
	deviceMQTTHandler _deviceMQTTDeliver.DeviceMQTTHandler
	deviceGPIOHandler _deviceGPIODeliver.DeviceGPIOHandler
	openclawHandler   _openclawSseDeliver.OpenClawHandler
	sensingHandler    _sensingHttpDeliver.SensingHandler

	agentGateway   domain.AgentGateway
	networkService *network.Service
	deviceService  *device.Service
	ambientService *ambient.Service
	healthWatch    *healthwatch.Service
	statusLED      *statusled.Service

	// resetButton watches GPIO 23 for press-and-hold >= 10s to trigger factory reset. Nil when GPIO unavailable.
	resetButton *resetbutton.Service
	// mqttFactory is the optional MQTT factory (nil when broker not configured).
	mqttFactory *mqtt.Factory
	// mqttClient is the active MQTT client when setup is complete; guarded by mqttMu.
	mqttClient *mqtt.MQTT
	mqttCancel context.CancelFunc
	mqttMu     sync.Mutex

	// monitorCtx: context for network monitor + status reporter. Created when SetUpCompleted true, cancelled when false or on shutdown.
	monitorCtx context.Context
	// monitorCancel cancels monitorCtx.
	monitorCancel context.CancelFunc
	// monitorMu guards monitorCtx and monitorCancel.
	monitorMu sync.Mutex
	// lastSetupCompleted is the last SetUpCompleted value we acted on. Used to avoid redundant handleSetUpCompleteChanged when config notifies but value unchanged.
	lastSetupCompleted *bool
}

// Engine ...
func (s *Server) Engine() *gin.Engine {
	return s.engine
}

// GetContext ...
func (s *Server) GetContext(c *gin.Context) context.Context {
	ctx := c.Request.Context()
	if ctx == nil {
		ctx = context.Background()
	}

	return ctx
}

func ProvideServer(
	cfg *config.Config,
	hh _healthHttpDeliver.HealthHandler,
	nh _networkHttpDeliver.NetworkHandler,
	dh _deviceHttpDeliver.DeviceHandler,
	dqth _deviceMQTTDeliver.DeviceMQTTHandler,
	dgph _deviceGPIODeliver.DeviceGPIOHandler,
	openclawH _openclawSseDeliver.OpenClawHandler,
	sensingH _sensingHttpDeliver.SensingHandler,
	ds *device.Service,
	agentGW domain.AgentGateway,
	ns *network.Service,
	resetBtn *resetbutton.Service,
	mqttFactory *mqtt.Factory,
	ambientSvc *ambient.Service,
	hw *healthwatch.Service,
	sled *statusled.Service,
) *Server {
	return &Server{
		config:            cfg,
		healthHandler:     hh,
		networkHandler:    nh,
		deviceHandler:     dh,
		deviceMQTTHandler: dqth,
		deviceGPIOHandler: dgph,
		openclawHandler:   openclawH,
		sensingHandler:    sensingH,
		agentGateway:      agentGW,
		networkService:    ns,
		deviceService:     ds,
		resetButton:       resetBtn,
		mqttFactory:       mqttFactory,
		ambientService:    ambientSvc,
		healthWatch:       hw,
		statusLED:         sled,
	}
}

// restartMQTT stops the current MQTT client and starts a new one (e.g. when backend pushes new MQTT config).
func (s *Server) restartMQTT() {
	s.stopMQTT()
	s.startMQTT()
}

// startMQTT creates a client from the factory, subscribes to the topic, and connects. Idempotent if already running.
func (s *Server) startMQTT() {
	s.mqttMu.Lock()
	if s.mqttClient != nil {
		s.mqttMu.Unlock()
		return
	}
	if s.mqttFactory == nil {
		s.mqttMu.Unlock()
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	client := s.mqttFactory.GetClient("lumi-server-" + s.config.DeviceID)
	client.Subscribe(s.config.FAChannel, 1, func(topic string, payload []byte) {
		slog.Debug("message received", "component", "mqtt", "topic", topic, "payload", string(payload))
		s.deviceMQTTHandler.HandleMessage(topic, payload)
	})
	s.mqttClient = client
	s.mqttCancel = cancel
	s.mqttMu.Unlock()

	safego.Go("mqtt", func() {
		if err := client.Connect(ctx); err != nil && ctx.Err() == nil {
			slog.Error("connect failed", "component", "mqtt", "error", err)
		}
	})
}

// stopMQTT disconnects and clears the MQTT client. Safe to call when not connected.
func (s *Server) stopMQTT() {
	s.mqttMu.Lock()
	client := s.mqttClient
	cancel := s.mqttCancel
	s.mqttClient = nil
	s.mqttCancel = nil
	s.mqttMu.Unlock()

	if cancel != nil {
		cancel()
	}
	if client != nil {
		_ = client.Close()
	}
}

func corsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*")
		c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Origin, Content-Type, Accept, Authorization")
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

func (s *Server) Serve(closeFn func()) error {
	// Signal booting state so the LED shows a slow blue pulse while initializing.
	s.statusLED.Set(statusled.StateBooting)

	if s.resetButton != nil {
		resetCtx, cancelReset := context.WithCancel(context.Background())
		defer cancelReset()
		s.resetButton.Start(resetCtx, s.deviceGPIOHandler.HandleResetButtonPress, s.deviceGPIOHandler.HandleResetButtonPowerOff, s.deviceGPIOHandler.HandleResetButtonFactoryReset, s.deviceGPIOHandler.HandleResetButtonPowerOffThreshold, s.deviceGPIOHandler.HandleResetButtonFactoryResetThreshold)
		defer s.resetButton.Close()
	}

	s.handleSetUpCompleteChange(s.config.SetUpCompleted)

	configCtx, cancelConfig := context.WithCancel(context.Background())
	defer cancelConfig()
	go s.runConfigChangeListener(configCtx)

	eventCtx, cancelEvents := context.WithCancel(context.Background())
	defer cancelEvents()
	go s.agentGateway.StartWS(eventCtx, s.openclawHandler.HandleEvent)

	r := gin.Default()
	r.RedirectTrailingSlash = false // avoid 301 redirect loop on /network vs /network/
	r.Use(corsMiddleware())
	r.Use(gin.Recovery())

	api := r.Group("api")

	health := api.Group("health")
	health.GET("/live", s.healthHandler.Live)
	health.GET("/readiness", s.healthHandler.Readiness)

	system := api.Group("system")
	system.GET("info", s.healthHandler.SystemInfo)
	system.GET("network", s.healthHandler.NetworkInfo)
	system.GET("dashboard", s.healthHandler.Dashboard)
	system.POST("force-update", s.forceUpdate)

	device := api.Group("device")
	device.POST("setup", s.deviceHandler.Setup)
	device.POST("channel", s.deviceHandler.ChangeChannel)

	network := api.Group("network")
	network.GET("", s.networkHandler.GetNetworks)
	network.GET("current", s.networkHandler.GetCurrentNetwork)
	network.GET("check-internet", s.networkHandler.CheckInternet)

	sensing := api.Group("sensing")
	sensing.POST("event", s.sensingHandler.PostEvent)
	sensing.GET("snapshot/:name", s.sensingHandler.GetSnapshot)

	oc := api.Group("openclaw")
	oc.POST("busy", s.openclawHandler.SetBusy)
	oc.GET("status", s.openclawHandler.Status)
	oc.GET("events", s.openclawHandler.Events)
	oc.GET("recent", s.openclawHandler.Recent)
	oc.GET("flow-events", s.openclawHandler.FlowEvents)
	oc.GET("flow-stream", s.openclawHandler.FlowStream)
	oc.GET("flow-logs", s.openclawHandler.FlowLogs)
	oc.DELETE("flow-logs", s.openclawHandler.ClearFlowLogs)
	oc.GET("debug-logs", s.openclawHandler.DebugLogs)
	oc.DELETE("debug-logs", s.openclawHandler.ClearDebugLogs)
	oc.GET("debug-lines", s.openclawHandler.DebugLogLines)
	oc.GET("analytics", s.openclawHandler.Analytics)

	logs := api.Group("logs")
	logs.GET("tail", s.logTail)
	logs.GET("stream", s.logStream)

	slog.Info("server started", "component", "server")

	errChan := make(chan error)
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGINT, syscall.SIGTERM)

	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", s.config.HttpPort),
		Handler: r,
	}

	// HTTP server is about to listen — booting is done.
	s.statusLED.Clear(statusled.StateBooting)

	go func() {
		if err := srv.ListenAndServe(); err != nil {
			errChan <- err
		}
	}()

	for {
		select {
		case <-stop:
			// The context is used to inform the server it has 5 seconds to finish
			// the request it is currently handling
			cancelConfig()
			s.monitorMu.Lock()
			if s.monitorCancel != nil {
				s.monitorCancel()
			}
			s.monitorMu.Unlock()
			cancelEvents()
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if err := srv.Shutdown(ctx); err != nil {
				log.Fatal("Server forced to shutdown: ", err)
			}
			closeFn()
			return nil
		case err := <-errChan:
			return err
		}
	}
}

// runConfigChangeListener listens for config changes and calls handleSetUpCompleteChange only when SetUpCompleted changed.
func (s *Server) runConfigChangeListener(ctx context.Context) {
	ch := s.config.GetNotifyChannel()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ch:
			s.handleSetUpCompleteChange(s.config.SetUpCompleted)
		}
	}
}

// handleSetUpCompleteChange starts or stops the network monitor and status reporter based on SetUpCompleted.
// When true: cancels any previous monitor context, creates a new one, starts monitor and reporter, and runs OpenClaw ready check.
// When false: cancels monitor/reporter (they exit on ctx.Done()) and switches to AP mode.
func (s *Server) handleSetUpCompleteChange(setupCompleted bool) {
	if s.lastSetupCompleted != nil && *s.lastSetupCompleted == setupCompleted {
		return
	}
	if setupCompleted {
		s.monitorMu.Lock()
		if s.monitorCancel != nil {
			s.monitorCancel()
		}
		s.monitorCtx, s.monitorCancel = context.WithCancel(context.Background())
		s.monitorMu.Unlock()

		slog.Info("setup completed, starting internet monitor", "component", "config")
		s.networkService.StartNetworkMonitor(s.monitorCtx,
			func() { s.statusLED.Set(statusled.StateConnectivity) },
			func() { s.statusLED.Clear(statusled.StateConnectivity) },
		)
		slog.Info("setup completed, starting status reporter", "component", "config")
		safego.Go("status-reporter", func() { s.deviceService.StartStatusReporter(s.monitorCtx) })

		s.restartMQTT()

		safego.Go("startup-sequence", func() {
			// Seed SOUL.md + IDENTITY.md into workspace (factory defaults, once only)
			if err := s.agentGateway.EnsureOnboarding(); err != nil {
				slog.Error("onboarding seed failed", "component", "server", "error", err)
			}

			if ok := s.deviceService.WaitForAgentReady(120 * time.Second); ok {
				slog.Info("agent gateway ready", "component", "server")
				s.statusLED.FlashReady()
			} else {
				slog.Warn("agent gateway ready timeout", "component", "server")
			}
			// Start voice pipeline on LeLamp (if Deepgram key configured)
			// Retry because lumi-lelamp may not be running yet at setup time.
			if s.config.DeepgramAPIKey != "" {
				for attempt := 1; attempt <= 10; attempt++ {
					err := s.agentGateway.StartLeLampVoice(s.config.DeepgramAPIKey, s.config.LLMAPIKey, s.config.LLMBaseURL)
					if err == nil {
						break
					}
					slog.Warn("start LeLamp voice failed", "component", "server", "attempt", attempt, "maxAttempts", 10, "error", err)
					time.Sleep(5 * time.Second)
				}
			}

			// Greet user now that agent + voice pipeline are ready
			if _, err := s.agentGateway.SendChatMessage("You just woke up. Greet the user briefly."); err != nil {
				slog.Warn("startup greeting failed", "component", "server", "error", err)
			}

			// Start ambient life behaviors (breathing LED, micro-movements, mumbles)
			safego.Go("ambient", func() { s.ambientService.Start(s.monitorCtx) })
			// Watch LeLamp component health; auto-restart voice on ALSA failure
			safego.Go("healthwatch", func() { s.healthWatch.Start(s.monitorCtx) })
		})
	} else {
		s.monitorMu.Lock()
		if s.monitorCancel != nil {
			s.monitorCancel()
			s.monitorCancel = nil
		}
		s.monitorMu.Unlock()
		s.stopMQTT()
		s.networkService.SwitchToAPMode()
	}
	s.lastSetupCompleted = &setupCompleted
}

// allowedLogs maps source names to their log file paths (supports glob patterns).
var allowedLogs = map[string]string{
	"lelamp":   "/var/log/lelamp/server.log",
	"lumi":     "/var/log/lumi.log",
	"openclaw": "/var/log/openclaw/lumi.log",
}

// resolveLogPaths expands a pattern (plain path or glob) to matching files.
func resolveLogPaths(pattern string) ([]string, error) {
	if !strings.ContainsAny(pattern, "*?[") {
		return []string{pattern}, nil
	}
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return nil, fmt.Errorf("glob: %w", err)
	}
	sort.Strings(matches)
	return matches, nil
}

// logTail returns the last N lines of a whitelisted log file (or merged glob).
// GET /api/logs/tail?source=lelamp|lumi|openclaw&lines=200
func (s *Server) logTail(c *gin.Context) {
	source := c.DefaultQuery("source", "lumi")
	pattern, ok := allowedLogs[source]
	if !ok {
		c.JSON(http.StatusBadRequest, serializers.ResponseError("unknown log source"))
		return
	}

	n, _ := strconv.Atoi(c.DefaultQuery("lines", "200"))
	if n <= 0 || n > 5000 {
		n = 200
	}

	paths, err := resolveLogPaths(pattern)
	if err != nil || len(paths) == 0 {
		errMsg := "no log files found"
		if err != nil {
			errMsg = err.Error()
		}
		c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
			"source": source,
			"path":   pattern,
			"lines":  []string{},
			"error":  errMsg,
		}))
		return
	}

	var allLines []string
	for _, p := range paths {
		lines, _ := tailFile(p, n)
		allLines = append(allLines, lines...)
	}
	// Keep only last n lines across all files
	if len(allLines) > n {
		allLines = allLines[len(allLines)-n:]
	}

	c.JSON(http.StatusOK, serializers.ResponseSuccess(map[string]any{
		"source": source,
		"path":   pattern,
		"lines":  allLines,
	}))
}

// logStream streams new log lines via SSE from one or more log files.
// GET /api/logs/stream?source=lelamp|lumi|openclaw
func (s *Server) logStream(c *gin.Context) {
	source := c.DefaultQuery("source", "lumi")
	pattern, ok := allowedLogs[source]
	if !ok {
		c.JSON(http.StatusBadRequest, serializers.ResponseError("unknown log source"))
		return
	}

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	paths, err := resolveLogPaths(pattern)
	if err != nil || len(paths) == 0 {
		errMsg := "no log files found"
		if err != nil {
			errMsg = err.Error()
		}
		c.SSEvent("error", errMsg)
		return
	}

	type fileTail struct {
		f      *os.File
		reader *bufio.Reader
	}
	var tails []fileTail
	for _, p := range paths {
		f, err := os.Open(p)
		if err != nil {
			continue
		}
		// Seek to end
		_, _ = f.Seek(0, 2)
		tails = append(tails, fileTail{f: f, reader: bufio.NewReader(f)})
	}
	if len(tails) == 0 {
		c.SSEvent("error", "cannot open any log files")
		return
	}
	defer func() {
		for _, t := range tails {
			t.f.Close()
		}
	}()

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	c.Stream(func(w io.Writer) bool {
		select {
		case <-c.Request.Context().Done():
			return false
		case <-ticker.C:
			for i := range tails {
				for {
					line, err := tails[i].reader.ReadString('\n')
					if len(line) > 0 {
						c.SSEvent("log", strings.TrimRight(line, "\n"))
					}
					if err != nil {
						break
					}
				}
			}
			return true
		}
	})
}

// forceUpdate proxies a force-check request to the bootstrap OTA worker.
// POST /api/system/force-update
func (s *Server) forceUpdate(c *gin.Context) {
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodPost, "http://127.0.0.1:8080/force-check", nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError("build request: "+err.Error()))
		return
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, serializers.ResponseError("bootstrap unreachable: "+err.Error()))
		return
	}
	defer resp.Body.Close()
	c.JSON(http.StatusOK, serializers.ResponseSuccess("update check triggered"))
}

// tailFile reads the last n lines from a single file.
func tailFile(path string, n int) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open: %w", err)
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 256*1024), 256*1024)

	var ring []string
	for scanner.Scan() {
		ring = append(ring, scanner.Text())
		if len(ring) > n {
			ring = ring[1:]
		}
	}
	if err := scanner.Err(); err != nil {
		return ring, fmt.Errorf("scan: %w", err)
	}
	return ring, nil
}
