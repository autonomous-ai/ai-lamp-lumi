package http

import (
	"encoding/json"
	"net/http"

	"github.com/gin-gonic/gin"
	_deviceMQTT "go-lamp.autonomous.ai/server/device/delivery/mqtt"
	"go-lamp.autonomous.ai/server/serializers"
)

// GWSHandler provides HTTP endpoints to test GWS commands without MQTT.
type GWSHandler struct {
	mqttHandler _deviceMQTT.DeviceMQTTHandler
}

func ProvideGWSHandler(h _deviceMQTT.DeviceMQTTHandler) GWSHandler {
	return GWSHandler{mqttHandler: h}
}

// InstallGWS godoc
//
//	@Summary	install gws CLI and skills
//	@Description	test endpoint — triggers install_gws command
//	@Tags		gws
//	@Accept		json
//	@Produce	json
//	@Param		body	body	installGWSRequest	false	"install request"
//	@Success	200	{object}	serializers.ResponseSuccess
//	@Router		/gws/install [post]
func (h *GWSHandler) InstallGWS(c *gin.Context) {
	body, _ := c.GetRawData()
	if len(body) == 0 {
		body = []byte(`{"cmd":"install_gws","skills":"all"}`)
	} else {
		// Inject cmd field if missing
		body = ensureCmd(body, "install_gws")
	}

	if err := h.mqttHandler.HandleMessage("http-test", body); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess("install_gws dispatched"))
}

// SetGoogleCredentials godoc
//
//	@Summary	set Google OAuth credentials
//	@Description	test endpoint — triggers set_google_credentials command
//	@Tags		gws
//	@Accept		json
//	@Produce	json
//	@Param		body	body	setCredentialsRequest	false	"credentials"
//	@Success	200	{object}	serializers.ResponseSuccess
//	@Router		/gws/credentials [post]
func (h *GWSHandler) SetGoogleCredentials(c *gin.Context) {
	body, _ := c.GetRawData()
	if len(body) == 0 {
		c.JSON(http.StatusBadRequest, serializers.ResponseError("request body required"))
		return
	}
	body = ensureCmd(body, "set_google_credentials")

	if err := h.mqttHandler.HandleMessage("http-test", body); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess("set_google_credentials dispatched"))
}

// RemoveGoogleCredentials godoc
//
//	@Summary	remove Google OAuth credentials
//	@Description	test endpoint — triggers remove_google_credentials command
//	@Tags		gws
//	@Accept		json
//	@Produce	json
//	@Success	200	{object}	serializers.ResponseSuccess
//	@Router		/gws/credentials [delete]
func (h *GWSHandler) RemoveGoogleCredentials(c *gin.Context) {
	body := []byte(`{"cmd":"remove_google_credentials"}`)

	if err := h.mqttHandler.HandleMessage("http-test", body); err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess("remove_google_credentials dispatched"))
}

// ensureCmd injects the "cmd" field into raw JSON if not present.
func ensureCmd(data []byte, cmd string) []byte {
	// Simple approach: unmarshal, set cmd, remarshal
	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		return data
	}
	m["cmd"] = cmd
	out, err := json.Marshal(m)
	if err != nil {
		return data
	}
	return out
}

// Swagger types (not used in code, only for docs)
type installGWSRequest struct {
	Skills string `json:"skills" example:"all"`
}
type setCredentialsRequest struct {
	ClientID     string   `json:"client_id"`
	ClientSecret string   `json:"client_secret"`
	RefreshToken string   `json:"refresh_token"`
	Scopes       []string `json:"scopes"`
}
