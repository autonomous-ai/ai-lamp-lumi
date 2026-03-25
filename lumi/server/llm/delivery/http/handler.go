package http

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"go-lamp.autonomous.ai/internal/llm"

	"go-lamp.autonomous.ai/server/serializers"
)

// LLMHandler represents the HTTP handler for LLM
type LLMHandler struct {
	service *llm.Service
}

func ProvideLLMHandler(svc *llm.Service) LLMHandler {
	return LLMHandler{
		service: svc,
	}
}

// ListProviders godoc
//
//	@Summary	list LLM providers
//	@Schemes
//	@Description	returns the static list of known LLM providers (key and display name)
//	@Tags			llm
//	@Success		200	{object}	[]domain.Provider
//	@Router			/llm/providers [get]
func (h *LLMHandler) ListProviders(c *gin.Context) {
	providers, err := h.service.ListProviders()
	if err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(providers))
}

// ListModels godoc
//
//	@Summary	list models by provider (from openclaw)
//	@Schemes
//	@Description	runs openclaw models list --all --json and returns provider keys with model counts. Optional query: provider=
//	@Tags			llm
//	@Success		200	{object}	domain.LLMModelsListResponse
//	@Router			/llm/models [get]
func (h *LLMHandler) ListModels(c *gin.Context) {
	provider := c.Query("provider")
	response, err := h.service.ListModels(&provider)
	if err != nil {
		c.JSON(http.StatusInternalServerError, serializers.ResponseError(err.Error()))
		return
	}
	c.JSON(http.StatusOK, serializers.ResponseSuccess(response))
}
