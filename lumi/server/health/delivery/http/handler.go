package http

import (
	"net/http"
	"os"
	"runtime"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/server/config"
	"go-lamp.autonomous.ai/server/serializers"
)

// HealthHandler represents the HTTP handler for health and system info.
type HealthHandler struct {
	config         *config.Config
	networkService *network.Service
	agentGateway   domain.AgentGateway
}

func ProvideHealthHandler(cfg *config.Config, ns *network.Service, gw domain.AgentGateway) HealthHandler {
	return HealthHandler{config: cfg, networkService: ns, agentGateway: gw}
}

func (h *HealthHandler) Live(c *gin.Context) {
	c.JSON(http.StatusOK, serializers.ResponseSuccess("OK"))
}

func (h *HealthHandler) Readiness(c *gin.Context) {
	c.JSON(http.StatusOK, serializers.ResponseSuccess("OK"))
}

// SystemInfo returns CPU load, RAM usage, temperature, and uptime.
func (h *HealthHandler) SystemInfo(c *gin.Context) {
	info := map[string]any{
		"cpuLoad":    readLoadAvg(),
		"memTotal":   0,
		"memUsed":    0,
		"memPercent": 0.0,
		"cpuTemp":    readCPUTemp(),
		"uptime":     readUptime(),
		"goRoutines": runtime.NumGoroutine(),
		"version":    config.LumiVersion,
		"deviceId":   h.config.DeviceID,
	}

	// Parse /proc/meminfo for RAM
	if data, err := os.ReadFile("/proc/meminfo"); err == nil {
		memTotal, memAvail := parseMeminfo(string(data))
		info["memTotal"] = memTotal
		info["memUsed"] = memTotal - memAvail
		if memTotal > 0 {
			info["memPercent"] = float64(memTotal-memAvail) / float64(memTotal) * 100
		}
	}

	c.JSON(http.StatusOK, serializers.ResponseSuccess(info))
}

// NetworkInfo returns combined network status: SSID, IP, signal, internet.
func (h *HealthHandler) NetworkInfo(c *gin.Context) {
	info := map[string]any{
		"ssid":     "",
		"ip":       "",
		"signal":   0,
		"internet": false,
	}

	if net, err := h.networkService.CurrentNetwork(); err == nil && net != nil {
		info["ssid"] = net.SSID
		info["signal"] = net.Signal
	}

	if ip, err := h.networkService.GetCurrentIP(); err == nil {
		info["ip"] = ip
	}

	// Quick internet check (non-blocking, use cached result if possible)
	if ok, _ := h.networkService.CheckInternet(); ok {
		info["internet"] = true
	}

	c.JSON(http.StatusOK, serializers.ResponseSuccess(info))
}

// Dashboard returns a combined status snapshot for the monitor page.
func (h *HealthHandler) Dashboard(c *gin.Context) {
	dash := map[string]any{
		"openclaw": map[string]any{
			"connected":  h.agentGateway.IsReady(),
			"sessionKey": h.agentGateway.GetSessionKey() != "",
		},
		"version":  config.LumiVersion,
		"deviceId": h.config.DeviceID,
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(dash))
}

// readLoadAvg reads 1-min load average from /proc/loadavg.
func readLoadAvg() float64 {
	data, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		return 0
	}
	parts := strings.Fields(string(data))
	if len(parts) < 1 {
		return 0
	}
	v, _ := strconv.ParseFloat(parts[0], 64)
	return v
}

// readCPUTemp reads CPU temperature in celsius from thermal zone.
func readCPUTemp() float64 {
	data, err := os.ReadFile("/sys/class/thermal/thermal_zone0/temp")
	if err != nil {
		return 0
	}
	milliC, _ := strconv.Atoi(strings.TrimSpace(string(data)))
	return float64(milliC) / 1000.0
}

// readUptime reads system uptime in seconds from /proc/uptime.
func readUptime() int64 {
	data, err := os.ReadFile("/proc/uptime")
	if err != nil {
		return 0
	}
	parts := strings.Fields(string(data))
	if len(parts) < 1 {
		return 0
	}
	f, _ := strconv.ParseFloat(parts[0], 64)
	return int64(f)
}

// parseMeminfo extracts MemTotal and MemAvailable (in KB) from /proc/meminfo content.
func parseMeminfo(content string) (total, available int64) {
	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		v, _ := strconv.ParseInt(fields[1], 10, 64)
		switch {
		case strings.HasPrefix(line, "MemTotal:"):
			total = v
		case strings.HasPrefix(line, "MemAvailable:"):
			available = v
		}
	}
	return
}

