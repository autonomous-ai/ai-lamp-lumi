package http

import (
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
	"go-lamp.autonomous.ai/internal/device"
	"go-lamp.autonomous.ai/internal/network"
	"go-lamp.autonomous.ai/server/config"
	"go-lamp.autonomous.ai/server/serializers"
)

// NetworkHandler represents the HTTP handler for network
type NetworkHandler struct {
	config        *config.Config
	service       *network.Service
	deviceService *device.Service
}

func ProvideNetworkHandler(config *config.Config, ns *network.Service, ds *device.Service) NetworkHandler {
	return NetworkHandler{
		config:        config,
		service:       ns,
		deviceService: ds,
	}
}

// GetNetworks godoc
//
//	@Summary	get list networks
//	@Schemes
//	@Description				get list networks
//	@Tags						network
//	@Success					200			{object}	domain.GetNetworksResponse
//	@Router						/network [get]
func (h *NetworkHandler) GetNetworks(c *gin.Context) {
	log.Println("GetNetworks")
	networks, err := h.service.ListNetworks()
	log.Println("GetNetworks", networks, err)
	if err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	log.Println("GetNetworks", networks, err)
	c.JSON(http.StatusOK, serializers.ResponseSuccess(networks))
}

func (h *NetworkHandler) GetCurrentNetwork(c *gin.Context) {
	network, err := h.service.CurrentNetwork()
	if err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}

	c.JSON(http.StatusOK, serializers.ResponseSuccess(network))
}

func (h *NetworkHandler) CheckInternet(c *gin.Context) {
	internet, err := h.service.CheckInternet()
	if err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}

	c.JSON(http.StatusOK, serializers.ResponseSuccess(internet))
}
