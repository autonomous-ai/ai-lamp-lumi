// Package intent provides local intent matching for common voice commands.
// Matched commands execute directly against LeLamp APIs, bypassing OpenClaw
// for instant response (~50ms vs ~3-5s through the agent pipeline).
package intent

import (
	"fmt"
	"net/http"
	"strings"
)

const lelampBase = "http://127.0.0.1:5001"

// Result holds what to do after a match: the LeLamp action + a TTS reply.
type Result struct {
	// TTSText is spoken back to the user via /voice/speak.
	TTSText string
	// LEDChanged is true when this intent sets an LED color/scene (locks ambient breathing).
	LEDChanged bool
	// LEDOff is true when this intent turns the LED off (unlocks ambient breathing).
	LEDOff bool
}

// Match tries to match a voice command to a local intent.
// Returns nil if no match — caller should fall through to OpenClaw.
func Match(text string) *Result {
	t := normalize(text)

	for _, r := range rules {
		if r.match(t) {
			return r.exec(t)
		}
	}
	return nil
}

// --- rules table ---

type rule struct {
	match func(string) bool
	exec  func(string) *Result
}

var rules = []rule{
	// --- LED on/off ---
	{
		match: anyOf("bật đèn", "mở đèn", "bat den", "mo den", "turn on the light", "light on", "turn on"),
		exec: func(string) *Result {
			post("/led/solid", `{"color":[255,220,180]}`)
			post("/emotion", `{"emotion":"happy","intensity":0.6}`)
			return &Result{TTSText: "Light on!", LEDChanged: true}
		},
	},
	{
		match: anyOf("tắt đèn", "tắt hết đèn", "tat den", "turn off the light", "light off", "turn off"),
		exec: func(string) *Result {
			post("/led/off", "")
			post("/emotion", `{"emotion":"idle","intensity":0.3}`)
			return &Result{TTSText: "Light off!", LEDOff: true}
		},
	},

	// --- Scenes ---
	{
		match: anyOf("đọc sách", "chế độ đọc", "doc sach", "reading mode", "reading"),
		exec: sceneExec("reading", "Reading mode!"),
	},
	{
		match: anyOf("tập trung", "làm việc", "tap trung", "lam viec", "focus mode", "focus"),
		exec: sceneExec("focus", "Focus mode!"),
	},
	{
		match: anyOf("thư giãn", "thu gian", "relax", "chill"),
		exec: sceneExec("relax", "Relax mode!"),
	},
	{
		match: anyOf("xem phim", "xem film", "movie mode", "movie"),
		exec: sceneExec("movie", "Movie mode!"),
	},
	{
		match: anyOf("đèn ngủ", "ngủ đi", "chúc ngủ ngon", "den ngu", "ngu di", "goodnight", "night mode", "sleep"),
		exec: func(string) *Result {
			post("/scene", `{"scene":"night"}`)
			post("/emotion", `{"emotion":"sleepy","intensity":0.4}`)
			return &Result{TTSText: "Goodnight!", LEDChanged: true}
		},
	},
	{
		match: anyOf("sáng lên", "sáng hơn", "sang len", "sang hon", "brighter", "bright", "energize"),
		exec: sceneExec("energize", "Max brightness!"),
	},

	// --- Emotions ---
	{
		match: anyOf("vui lên", "vui đi", "happy"),
		exec: emotionExec("happy", "Yay!"),
	},
	{
		match: anyOf("buồn", "buon", "sad"),
		exec: emotionExec("sad", "Aww."),
	},
	{
		match: anyOf("ngạc nhiên", "ngac nhien", "wow", "shock", "surprised"),
		exec: emotionExec("shock", "Wow!"),
	},

	// --- Volume ---
	{
		match: anyOf("tăng âm", "to hơn", "lớn hơn", "tang am", "to hon", "lon hon", "volume up", "louder"),
		exec: func(string) *Result {
			post("/audio/volume", `{"volume":80}`)
			return &Result{TTSText: "Volume up!"}
		},
	},
	{
		match: anyOf("giảm âm", "nhỏ hơn", "bé hơn", "giam am", "nho hon", "be hon", "volume down", "quieter", "softer"),
		exec: func(string) *Result {
			post("/audio/volume", `{"volume":30}`)
			return &Result{TTSText: "Volume down!"}
		},
	},
	{
		match: anyOf("im", "im đi", "tắt tiếng", "tat tieng", "mute", "shut up", "quiet"),
		exec: func(string) *Result {
			post("/audio/volume", `{"volume":0}`)
			return &Result{TTSText: ""}
		},
	},
}

// --- helpers ---

func normalize(s string) string {
	return strings.ToLower(strings.TrimSpace(s))
}

func anyOf(keywords ...string) func(string) bool {
	return func(t string) bool {
		for _, kw := range keywords {
			if strings.Contains(t, kw) {
				return true
			}
		}
		return false
	}
}

func sceneExec(scene, reply string) func(string) *Result {
	return func(string) *Result {
		post("/scene", fmt.Sprintf(`{"scene":"%s"}`, scene))
		return &Result{TTSText: reply, LEDChanged: true}
	}
}

func emotionExec(emotion, reply string) func(string) *Result {
	return func(string) *Result {
		post("/emotion", fmt.Sprintf(`{"emotion":"%s","intensity":0.8}`, emotion))
		return &Result{TTSText: reply}
	}
}

func post(path, body string) {
	url := lelampBase + path
	var resp *http.Response
	var err error
	if body == "" {
		resp, err = http.Post(url, "application/json", nil)
	} else {
		resp, err = http.Post(url, "application/json", strings.NewReader(body))
	}
	if err == nil {
		resp.Body.Close()
	}
}
