package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"
)

// Bridge maps buddy state changes to LeLamp and Lumi HTTP calls.
type Bridge struct {
	lelampURL string
	lumiURL   string
	client    *http.Client
}

func NewBridge(lelampURL, lumiURL string) *Bridge {
	return &Bridge{
		lelampURL: lelampURL,
		lumiURL:   lumiURL,
		client:    &http.Client{Timeout: 5 * time.Second},
	}
}

// OnStateChange is called by StateMachine when state transitions.
func (b *Bridge) OnStateChange(old, next BuddyState, hb *Heartbeat) {
	log.Printf("[bridge] %s → %s", old, next)

	switch next {
	case StateSleep:
		b.ledOff()
		b.displayEyes("sleepy")

	case StateIdle:
		// Don't set LED — let ambient service handle it
		b.displayEyesMode()

	case StateBusy:
		b.ledEffect("pulse", [3]int{0, 100, 255}, 0.8, 0)
		if hb != nil {
			b.displayInfo(
				fmt.Sprintf("%s tokens", formatTokens(hb.TokensToday)),
				fmt.Sprintf("%d sessions running", hb.Running),
			)
		}

	case StateAttention:
		b.ledEffect("blink", [3]int{255, 80, 0}, 1.5, 0)
		if hb != nil && hb.Prompt != nil {
			b.displayInfo(
				fmt.Sprintf("Approve %s?", hb.Prompt.Tool),
				truncate(hb.Prompt.Hint, 40),
			)
			b.postSensingEvent(hb.Prompt)
		}

	case StateHeart:
		b.ledSolid([3]int{255, 200, 100})
		b.displayEyes("happy")

	case StateCelebrate:
		b.ledEffect("rainbow", [3]int{255, 255, 255}, 2.0, 3000)
		b.displayEyes("excited")
	}

	b.postBuddyState(next, hb)
}

// --- LeLamp calls (port 5001) ---

func (b *Bridge) ledOff() {
	b.post(b.lelampURL+"/led/off", nil)
}

func (b *Bridge) ledSolid(color [3]int) {
	b.post(b.lelampURL+"/led/solid", map[string]interface{}{
		"color": color,
	})
}

func (b *Bridge) ledEffect(effect string, color [3]int, speed float64, durationMs int) {
	payload := map[string]interface{}{
		"effect": effect,
		"color":  color,
		"speed":  speed,
	}
	if durationMs > 0 {
		payload["duration_ms"] = durationMs
	}
	b.post(b.lelampURL+"/led/effect", payload)
}

func (b *Bridge) displayInfo(text, subtitle string) {
	b.post(b.lelampURL+"/display/info", map[string]interface{}{
		"text":     text,
		"subtitle": subtitle,
	})
}

func (b *Bridge) displayEyes(expression string) {
	b.post(b.lelampURL+"/display/eyes", map[string]interface{}{
		"expression": expression,
	})
}

func (b *Bridge) displayEyesMode() {
	b.post(b.lelampURL+"/display/eyes-mode", nil)
}

// --- Lumi calls (port 5000) ---

// postBuddyState sends buddy state to Lumi monitor bus.
func (b *Bridge) postBuddyState(state BuddyState, hb *Heartbeat) {
	detail := map[string]interface{}{
		"state": string(state),
	}
	if hb != nil && hb.Prompt != nil {
		detail["tool"] = hb.Prompt.Tool
		detail["hint"] = hb.Prompt.Hint
	}

	b.post(b.lumiURL+"/api/monitor/event", map[string]interface{}{
		"type":    "buddy_state",
		"summary": fmt.Sprintf("buddy: %s", state),
		"detail":  detail,
	})
}

// postSensingEvent sends approval event to Lumi sensing pipeline.
func (b *Bridge) postSensingEvent(prompt *Prompt) {
	b.post(b.lumiURL+"/api/sensing/event", map[string]interface{}{
		"type":    "buddy_approval",
		"message": fmt.Sprintf("Claude Desktop needs approval: %s on %s [prompt_id:%s]", prompt.Tool, prompt.Hint, prompt.ID),
	})
}

// --- Helpers ---

func (b *Bridge) post(url string, payload interface{}) {
	var body []byte
	if payload != nil {
		var err error
		body, err = json.Marshal(payload)
		if err != nil {
			log.Printf("[bridge] marshal error for %s: %v", url, err)
			return
		}
	}

	var resp *http.Response
	var err error
	if body != nil {
		resp, err = b.client.Post(url, "application/json", bytes.NewReader(body))
	} else {
		resp, err = b.client.Post(url, "application/json", nil)
	}
	if err != nil {
		log.Printf("[bridge] %s error: %v", url, err)
		return
	}
	resp.Body.Close()
}

func formatTokens(n int) string {
	if n >= 1000 {
		return fmt.Sprintf("%.1fK", float64(n)/1000)
	}
	return fmt.Sprintf("%d", n)
}

func truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max-3] + "..."
}
