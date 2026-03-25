package server

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/internal/device"
	"go-lamp.autonomous.ai/internal/led"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/internal/openclaw"
	"go-lamp.autonomous.ai/internal/resetbutton"
	"go-lamp.autonomous.ai/lib/mqtt"
	"go-lamp.autonomous.ai/server/config"
	_deviceGPIODeliver "go-lamp.autonomous.ai/server/device/delivery/gpio"
	_deviceHttpDeliver "go-lamp.autonomous.ai/server/device/delivery/http"
	_deviceMQTTDeliver "go-lamp.autonomous.ai/server/device/delivery/mqtt"
	_healthHttpDeliver "go-lamp.autonomous.ai/server/health/delivery/http"
	_ledHttpDeliver "go-lamp.autonomous.ai/server/led/delivery/http"
	_networkHttpDeliver "go-lamp.autonomous.ai/server/network/delivery/http"
	_openclawSseDeliver "go-lamp.autonomous.ai/server/openclaw/delivery/sse"
)

type Server struct {
	engine *gin.Engine
	config *config.Config

	// handlers
	healthHandler     _healthHttpDeliver.HealthHandler
	ledHandler        _ledHttpDeliver.LedHandler
	networkHandler    _networkHttpDeliver.NetworkHandler
	deviceHandler     _deviceHttpDeliver.DeviceHandler
	deviceMQTTHandler _deviceMQTTDeliver.DeviceMQTTHandler
	deviceGPIOHandler _deviceGPIODeliver.DeviceGPIOHandler
	openclawHandler   _openclawSseDeliver.OpenClawHandler

	openclawService *openclaw.Service
	networkService  *network.Service
	deviceService   *device.Service

	// ledEngine controls RGB LED state (Booting / ConnectionMode / Online / Error). Nil when not on Pi or GPIO unavailable.
	ledEngine *led.Engine
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
	ledH _ledHttpDeliver.LedHandler,
	nh _networkHttpDeliver.NetworkHandler,
	dh _deviceHttpDeliver.DeviceHandler,
	dqth _deviceMQTTDeliver.DeviceMQTTHandler,
	dgph _deviceGPIODeliver.DeviceGPIOHandler,
	openclawH _openclawSseDeliver.OpenClawHandler,
	ds *device.Service,
	openclawSvc *openclaw.Service,
	ns *network.Service,
	ledEngine *led.Engine,
	resetBtn *resetbutton.Service,
	mqttFactory *mqtt.Factory,
) *Server {
	return &Server{
		config:            cfg,
		healthHandler:     hh,
		ledHandler:        ledH,
		networkHandler:    nh,
		deviceHandler:     dh,
		deviceMQTTHandler: dqth,
		deviceGPIOHandler: dgph,
		openclawHandler:   openclawH,
		openclawService:   openclawSvc,
		networkService:    ns,
		deviceService:     ds,
		ledEngine:         ledEngine,
		resetButton:       resetBtn,
		mqttFactory:       mqttFactory,
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
		log.Printf("[mqtt] received %s: %s", topic, string(payload))
		s.deviceMQTTHandler.HandleMessage(topic, payload)
	})
	s.mqttClient = client
	s.mqttCancel = cancel
	s.mqttMu.Unlock()

	go func() {
		if err := client.Connect(ctx); err != nil && ctx.Err() == nil {
			log.Printf("[mqtt] Connect: %v", err)
		}
	}()
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
	if s.ledEngine != nil {
		s.ledEngine.SetState(led.Booting, "server-start")
		defer s.ledEngine.Close()
	}

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
	go s.openclawService.StartWS(eventCtx, s.openclawHandler.HandleEvent)

	r := gin.Default()
	r.RedirectTrailingSlash = false // avoid 301 redirect loop on /network vs /network/
	r.Use(corsMiddleware())
	r.Use(gin.Recovery())

	api := r.Group("api")

	health := r.Group("health")
	health.GET("/live", s.healthHandler.Live)
	health.GET("/readiness", s.healthHandler.Readiness)

	device := api.Group("device")
	device.POST("setup", s.deviceHandler.Setup)
	device.POST("channel", s.deviceHandler.ChangeChannel)

	network := api.Group("network")
	network.GET("", s.networkHandler.GetNetworks)
	network.GET("current", s.networkHandler.GetCurrentNetwork)
	network.GET("check-internet", s.networkHandler.CheckInternet)

	api.GET("led", s.ledHandler.GetState)
	api.POST("led", s.ledHandler.UpdateState)

	log.Println("Start server completed")

	errChan := make(chan error)
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGINT, syscall.SIGTERM)

	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", s.config.HttpPort),
		Handler: r,
	}

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

		log.Println("[config] setup completed, starting internet monitor")
		s.networkService.StartNetworkMonitor(s.monitorCtx)
		log.Println("[config] setup completed, starting status reporter")
		go s.deviceService.StartStatusReporter(s.monitorCtx)

		s.restartMQTT()

		go func() {
			if ok := s.deviceService.WaitForOpenclawReady(120 * time.Second); ok {
				if s.ledEngine != nil {
					s.ledEngine.SetState(led.Working, "server-ready")
				}
			} else if s.ledEngine != nil {
				s.ledEngine.SetState(led.Error, "openclaw-ready-timeout")
			}
		}()
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
