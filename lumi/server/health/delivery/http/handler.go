package http

import (
	"net/http"
	"os"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/server/config"
	"go-lamp.autonomous.ai/server/serializers"
)

// serverStartTime records when the Lumi process started.
var serverStartTime = time.Now()

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
		"cpuLoad":    readCPUPercent(),
		"memTotal":   0,
		"memUsed":    0,
		"memPercent": 0.0,
		"cpuTemp":    readCPUTemp(),
		"uptime":        readUptime(),
		"serviceUptime": int64(time.Since(serverStartTime).Seconds()),
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

	// Disk usage for root filesystem
	diskTotal, diskUsed, diskPercent := readDiskUsage("/")
	info["diskTotal"] = diskTotal
	info["diskUsed"] = diskUsed
	info["diskPercent"] = diskPercent

	c.JSON(http.StatusOK, serializers.ResponseSuccess(info))
}

// readDiskUsage returns total, used (in MB) and usage percent for the given path.
func readDiskUsage(path string) (totalMB, usedMB int64, percent float64) {
	var stat syscall.Statfs_t
	if err := syscall.Statfs(path, &stat); err != nil {
		return 0, 0, 0
	}
	total := stat.Blocks * uint64(stat.Bsize)
	free := stat.Bavail * uint64(stat.Bsize)
	used := total - free
	totalMB = int64(total / (1024 * 1024))
	usedMB = int64(used / (1024 * 1024))
	if total > 0 {
		percent = float64(used) / float64(total) * 100
	}
	return
}

// publicIPCache caches the public IP to avoid calling ifconfig.me on every request.
var publicIPCache = struct {
	mu        sync.Mutex
	ip        string
	fetchedAt time.Time
}{}

func getPublicIP() string {
	publicIPCache.mu.Lock()
	defer publicIPCache.mu.Unlock()
	if time.Since(publicIPCache.fetchedAt) < 5*time.Minute && publicIPCache.ip != "" {
		return publicIPCache.ip
	}
	client := &http.Client{Timeout: 3 * time.Second}
	req, err := http.NewRequest("GET", "https://ifconfig.me/ip", nil)
	if err != nil {
		return ""
	}
	req.Header.Set("User-Agent", "curl/7.64.1")
	resp, err := client.Do(req)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	buf := make([]byte, 64)
	n, _ := resp.Body.Read(buf)
	ip := strings.TrimSpace(string(buf[:n]))
	publicIPCache.ip = ip
	publicIPCache.fetchedAt = time.Now()
	return ip
}

// NetworkInfo returns combined network status: SSID, IP, public IP, signal, internet.
func (h *HealthHandler) NetworkInfo(c *gin.Context) {
	info := map[string]any{
		"ssid":     "",
		"ip":       "",
		"publicIp": "",
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
		info["publicIp"] = getPublicIP()
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

// cpuSampler periodically measures actual CPU usage from /proc/stat.
var cpuSampler = struct {
	mu   sync.RWMutex
	pct  float64
	once sync.Once
}{}

func initCPUSampler() {
	cpuSampler.once.Do(func() {
		go func() {
			prev := readCPUStat()
			for {
				time.Sleep(2 * time.Second)
				cur := readCPUStat()
				totalDelta := cur.total - prev.total
				idleDelta := cur.idle - prev.idle
				if totalDelta > 0 {
					pct := float64(totalDelta-idleDelta) / float64(totalDelta) * 100
					cpuSampler.mu.Lock()
					cpuSampler.pct = pct
					cpuSampler.mu.Unlock()
				}
				prev = cur
			}
		}()
	})
}

type cpuStat struct {
	idle  uint64
	total uint64
}

// readCPUStat reads aggregate CPU times from /proc/stat.
func readCPUStat() cpuStat {
	data, err := os.ReadFile("/proc/stat")
	if err != nil {
		return cpuStat{}
	}
	// First line: cpu  user nice system idle iowait irq softirq steal ...
	line := strings.SplitN(string(data), "\n", 2)[0]
	fields := strings.Fields(line)
	if len(fields) < 5 || fields[0] != "cpu" {
		return cpuStat{}
	}
	var total, idle uint64
	for i, f := range fields[1:] {
		v, _ := strconv.ParseUint(f, 10, 64)
		total += v
		if i == 3 { // 4th value is idle
			idle = v
		}
	}
	return cpuStat{idle: idle, total: total}
}

// readCPUPercent returns the latest sampled CPU usage percentage.
func readCPUPercent() float64 {
	initCPUSampler()
	cpuSampler.mu.RLock()
	defer cpuSampler.mu.RUnlock()
	return cpuSampler.pct
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

