package agent

import (
	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/monitor"
	"go-lamp.autonomous.ai/internal/openclaw"
	"go-lamp.autonomous.ai/server/config"
)

// ProvideGateway returns the AgentGateway implementation based on config.AgentRuntime.
func ProvideGateway(cfg *config.Config, bus *monitor.Bus) domain.AgentGateway {
	switch cfg.AgentRuntime {
	// Future runtimes go here:
	// case "picoclaw":
	//     return picoclaw.ProvideService(cfg, bus)
	// case "claudecode":
	//     return claudecode.ProvideService(cfg, bus)
	default:
		return openclaw.ProvideService(cfg, bus)
	}
}
