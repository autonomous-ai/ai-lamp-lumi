//go:build wireinject

package server

import (
	"github.com/google/wire"

	"go-lamp.autonomous.ai/internal/beclient"
	"go-lamp.autonomous.ai/internal/device"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/internal/openclaw"
	"go-lamp.autonomous.ai/internal/resetbutton"
	"go-lamp.autonomous.ai/lib/mqtt"
	"go-lamp.autonomous.ai/server/config"
	_deviceGPIODeliver "go-lamp.autonomous.ai/server/device/delivery/gpio"
	_deviceHttpDeliver "go-lamp.autonomous.ai/server/device/delivery/http"
	_deviceMQTTDeliver "go-lamp.autonomous.ai/server/device/delivery/mqtt"
	_healthHttpDeliver "go-lamp.autonomous.ai/server/health/delivery/http"
	_networkHttpDeliver "go-lamp.autonomous.ai/server/network/delivery/http"
	_openclawSse "go-lamp.autonomous.ai/server/openclaw/delivery/sse"
)

func InitializeServer() (*Server, error) {
	panic(wire.Build(
		config.ProviderSet,
		mqtt.ProviderSet,
		beclient.ProviderSet,
		network.ProviderSet,
		openclaw.ProviderSet,
		device.ProviderSet,
		resetbutton.ProviderSet,
		_healthHttpDeliver.ProviderSet,
		_networkHttpDeliver.ProviderSet,
		_deviceHttpDeliver.ProviderSet,
		_deviceMQTTDeliver.ProviderSet,
		_deviceGPIODeliver.ProviderSet,
		_openclawSse.ProviderSet,
		ProvideServer,
	))
}
