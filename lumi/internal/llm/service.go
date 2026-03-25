package llm

import (
	"encoding/json"
	"fmt"
	"os/exec"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/server/config"
)

// v1ModelsResponse is the JSON shape from GET {base}/v1/models (e.g. eternalai).
type v1ModelsResponse struct {
	Type string         `json:"type"`
	Data []v1ModelEntry `json:"data"`
}

type v1ModelEntry struct {
	ID            string   `json:"id"`
	Name          string   `json:"name"`
	Reasoning     bool     `json:"reasoning"`
	Input         []string `json:"input"`
	ContextWindow *int     `json:"contextWindow"`
	MaxTokens     *int     `json:"maxTokens"`
	Privacy       string   `json:"privacy"`
	Capabilities  *struct {
		SupportsReasoning       bool `json:"supportsReasoning"`
		SupportsVision          bool `json:"supportsVision"`
		SupportsFunctionCalling bool `json:"supportsFunctionCalling"`
	} `json:"capabilities"`
}

type Service struct {
	config *config.Config
}

func ProvideService(config *config.Config) *Service {
	return &Service{config: config}
}

// ListProviders returns the static list of known LLM providers (key and display name).
func (s *Service) ListProviders() ([]domain.LLMProvider, error) {
	return domain.ListProviders, nil
}

// ListModels runs `openclaw models list --all --json` and returns unique provider keys
// with model counts (the segment before the first "/" in each model key, e.g. "amazon-bedrock").
func (s *Service) ListModels(provider *string) (*domain.LLMModelsListResponse, error) {
	providerFlag := ""
	if provider != nil && *provider != "" {
		providerFlag = fmt.Sprintf("--provider=%s", *provider)
	}
	cmd := exec.Command("openclaw", "models", "list", "--all", "--json", providerFlag)
	out, err := cmd.Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok && len(ee.Stderr) > 0 {
			return nil, fmt.Errorf("openclaw models list: %w (stderr: %s)", err, string(ee.Stderr))
		}
		return nil, fmt.Errorf("openclaw models list: %w", err)
	}

	var resp domain.LLMModelsListResponse
	if err := json.Unmarshal(out, &resp); err != nil {
		return nil, fmt.Errorf("parse openclaw models json: %w", err)
	}

	return &resp, nil
}

var tmpModels = []domain.LLMModel{
	{
		Key:           "claude-opus-4-6",
		Name:          "claude-opus-4-6",
		Reasoning:     true,
		Input:         []string{"text"},
		ContextWindow: nil,
		MaxTokens:     nil,
		Privacy:       "private",
		Capabilities: &domain.LLMModelCapabilities{
			SupportsReasoning:       true,
			SupportsVision:          false,
			SupportsFunctionCalling: true,
		},
	},
	{
		Key:           "claude-haiku-4-5",
		Name:          "claude-haiku-4-5",
		Reasoning:     true,
		Input:         []string{"text"},
		ContextWindow: nil,
		MaxTokens:     nil,
		Privacy:       "private",
		Capabilities: &domain.LLMModelCapabilities{
			SupportsReasoning:       true,
			SupportsVision:          false,
			SupportsFunctionCalling: true,
		},
	},
}

// ListModelsFromAPI fetches models from GET {apiBaseURL}/v1/models and returns them as LLMModelsListResponse.
// apiBaseURL should be the base URL with or without /v1 (e.g. https://mvp-b.eternalai.org or https://mvp-b.eternalai.org/v1).
func (s *Service) ListModelsFromAPI(apiBaseURL string) (*domain.LLMModelsListResponse, error) {
	return &domain.LLMModelsListResponse{
		Count:  len(tmpModels),
		Models: tmpModels,
	}, nil
	// base := strings.TrimSuffix(apiBaseURL, "/")
	// if !strings.HasSuffix(base, "/v1") {
	// 	base = base + "/v1"
	// }
	// url := base + "/models"

	// req, err := http.NewRequest(http.MethodGet, url, nil)
	// if err != nil {
	// 	return nil, fmt.Errorf("list models request: %w", err)
	// }
	// resp, err := http.DefaultClient.Do(req)
	// if err != nil {
	// 	return nil, fmt.Errorf("list models get %s: %w", url, err)
	// }
	// defer resp.Body.Close()

	// if resp.StatusCode != http.StatusOK {
	// 	return nil, fmt.Errorf("list models: %s returned %s", url, resp.Status)
	// }

	// var raw v1ModelsResponse
	// if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
	// 	return nil, fmt.Errorf("parse list models json: %w", err)
	// }

	// models := make([]domain.LLMModel, 0, len(raw.Data))
	// for _, e := range raw.Data {
	// 	input := "text"
	// 	if len(e.Input) > 0 {
	// 		input = strings.Join(e.Input, ",")
	// 	}
	// 	ctxWindow := 0
	// 	if e.ContextWindow != nil {
	// 		ctxWindow = *e.ContextWindow
	// 	}
	// 	models = append(models, domain.LLMModel{
	// 		Key:           e.ID,
	// 		Name:          e.Name,
	// 		Input:         input,
	// 		ContextWindow: ctxWindow,
	// 		Available:     true,
	// 	})
	// }

	// return &domain.LLMModelsListResponse{
	// 	Count:  len(models),
	// 	Models: models,
	// }, nil
}
