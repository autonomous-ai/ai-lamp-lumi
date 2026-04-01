// Package lelamp provides a lightweight HTTP client for the LeLamp hardware API.
// Both lumi-server and bootstrap-server use this to control LEDs on port 5001.
package lelamp

import (
	"fmt"
	"net/http"
	"strings"
	"time"
)

const BaseURL = "http://127.0.0.1:5001"

var httpClient = &http.Client{Timeout: 5 * time.Second}

// SetEffect starts a named LED effect with the given color and speed.
func SetEffect(effect string, r, g, b int, speed float64) {
	body := fmt.Sprintf(`{"effect":"%s","color":[%d,%d,%d],"speed":%.2f}`, effect, r, g, b, speed)
	post("/led/effect", body)
}

// StopEffect stops any running LED effect.
func StopEffect() {
	post("/led/effect/stop", "{}")
}

// SetSolid sets all LEDs to a single color, stopping any running effect first.
func SetSolid(r, g, b int) {
	post("/led/effect/stop", "{}")
	body := fmt.Sprintf(`{"color":[%d,%d,%d]}`, r, g, b)
	post("/led/solid", body)
}

// Off turns off all LEDs.
func Off() {
	post("/led/off", "{}")
}

func post(path, body string) {
	resp, err := httpClient.Post(BaseURL+path, "application/json", strings.NewReader(body))
	if err != nil {
		return // silent fail — hardware may not be available
	}
	resp.Body.Close()
}
