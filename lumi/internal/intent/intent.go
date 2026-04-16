// Package intent provides local intent matching for common voice commands.
// Matched commands execute directly against LeLamp APIs, bypassing OpenClaw
// for instant response (~50ms vs ~3-5s through the agent pipeline).
package intent

import (
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"
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
	// Emotion is the emotion name if this intent triggered an /emotion call.
	Emotion string
	// Rule is the name of the matched rule for debugging.
	Rule string
	// Actions lists hardware API calls made during exec (e.g. "POST /led/solid", "POST /emotion").
	Actions []string
}

// Match tries to match a voice command to a local intent.
// Returns nil if no match — caller should fall through to OpenClaw.
func Match(text string) *Result {
	t := normalize(text)

	for _, r := range rules {
		if r.match(t) {
			res := r.exec(t)
			res.Rule = r.name
			return res
		}
	}
	return nil
}

// --- rules table ---

type rule struct {
	name  string
	match func(string) bool
	exec  func(string) *Result
}

// colorKeywords maps color keywords to RGB values.
// Checked in order — first match wins.
var colorKeywords = []struct {
	keywords []string
	rgb      [3]int
	name     string
}{
	{[]string{"yellow"}, [3]int{255, 220, 0}, "Yellow"},
	{[]string{"red"}, [3]int{255, 0, 0}, "Red"},
	{[]string{"green"}, [3]int{0, 200, 100}, "Green"},
	{[]string{"blue"}, [3]int{0, 100, 255}, "Blue"},
	{[]string{"cyan"}, [3]int{0, 200, 150}, "Cyan"},
	{[]string{"purple", "violet"}, [3]int{100, 50, 200}, "Purple"},
	{[]string{"orange"}, [3]int{255, 100, 0}, "Orange"},
	{[]string{"pink"}, [3]int{255, 80, 150}, "Pink"},
	{[]string{"white"}, [3]int{255, 255, 255}, "White"},
	{[]string{"warm"}, [3]int{255, 180, 100}, "Warm"},
}

// extractColor returns the RGB and name for the first color keyword found in t.
func extractColor(t string) ([3]int, string, bool) {
	for _, c := range colorKeywords {
		for _, kw := range c.keywords {
			if strings.Contains(t, kw) {
				return c.rgb, c.name, true
			}
		}
	}
	return [3]int{}, "", false
}

// isLEDOnCommand returns true if t contains a "turn on light" trigger phrase.
func isLEDOnCommand(t string) bool {
	triggers := []string{"turn on the light", "light on", "set color", "change color", "set the light"}
	for _, kw := range triggers {
		if strings.Contains(t, kw) {
			return true
		}
	}
	return false
}

var rules = []rule{
	// --- LED color (must be before generic LED on/off) ---
	{
		name: "led_color",
		match: func(t string) bool {
			if !isLEDOnCommand(t) {
				return false
			}
			_, _, ok := extractColor(t)
			return ok
		},
		exec: func(t string) *Result {
			rgb, name, _ := extractColor(t)
			post("/led/effect/stop", "")
			body := fmt.Sprintf(`{"color":[%d,%d,%d]}`, rgb[0], rgb[1], rgb[2])
			post("/led/solid", body)
			return &Result{TTSText: name + " light on!", LEDChanged: true, Actions: []string{"POST /led/effect/stop", "POST /led/solid " + body}}
		},
	},

	// --- LED on/off ---
	{
		name:  "led_on",
		match: anyOf("turn on the light", "light on"),
		exec: func(string) *Result {
			post("/led/solid", `{"color":[255,220,180]}`)
			post("/emotion", `{"emotion":"happy","intensity":0.6}`)
			return &Result{TTSText: "Light on!", LEDChanged: true, Actions: []string{`POST /led/solid {"color":[255,220,180]}`, `POST /emotion {"emotion":"happy","intensity":0.6}`}}
		},
	},
	{
		name:  "led_off",
		match: anyOf("turn off the light", "light off"),
		exec: func(string) *Result {
			post("/led/off", "")
			post("/emotion", `{"emotion":"idle","intensity":0.3}`)
			return &Result{TTSText: "Light off!", LEDOff: true, Actions: []string{"POST /led/off", `POST /emotion {"emotion":"idle","intensity":0.3}`}}
		},
	},

	// --- Scenes ---
	{
		name:  "scene_reading",
		match: anyOf("reading mode", "reading light"),
		exec:  sceneExec("reading", "Reading mode!"),
	},
	{
		name:  "scene_focus",
		match: anyOf("focus mode", "focus light"),
		exec:  sceneExec("focus", "Focus mode!"),
	},
	{
		name:  "scene_relax",
		match: anyOf("relax mode", "relax light"),
		exec:  sceneExec("relax", "Relax mode!"),
	},
	{
		name:  "scene_movie",
		match: anyOf("movie mode", "movie light"),
		exec:  sceneExec("movie", "Movie mode!"),
	},
	{
		name:  "scene_night",
		match: anyOf("goodnight", "good night", "night mode"),
		exec: func(string) *Result {
			post("/scene", `{"scene":"night"}`)
			post("/emotion", `{"emotion":"sleepy","intensity":0.4}`)
			return &Result{TTSText: "Goodnight!", LEDChanged: true, Actions: []string{`POST /scene {"scene":"night"}`, `POST /emotion {"emotion":"sleepy","intensity":0.4}`}}
		},
	},
	{
		name:  "scene_energize",
		match: anyOf("brighter", "energize", "max brightness"),
		exec:  sceneExec("energize", "Max brightness!"),
	},

	// --- Volume ---
	{
		name:  "volume_up",
		match: anyOf("volume up", "louder"),
		exec: func(string) *Result {
			post("/audio/volume", `{"volume":80}`)
			return &Result{TTSText: "Volume up!", Actions: []string{`POST /audio/volume {"volume":80}`}}
		},
	},
	{
		name:  "volume_down",
		match: anyOf("volume down", "quieter"),
		exec: func(string) *Result {
			post("/audio/volume", `{"volume":30}`)
			return &Result{TTSText: "Volume down!", Actions: []string{`POST /audio/volume {"volume":30}`}}
		},
	},
	{
		name:  "mute",
		match: anyOf("mute", "shut up"),
		exec: func(string) *Result {
			post("/audio/volume", `{"volume":0}`)
			return &Result{TTSText: "", Actions: []string{`POST /audio/volume {"volume":0}`}}
		},
	},

	// --- Music control ---
	{
		name:  "music_stop",
		match: anyOf("stop music", "stop the music", "music off", "stop playing"),
		exec: func(string) *Result {
			post("/audio/stop", "")
			return &Result{TTSText: "Music stopped.", Actions: []string{"POST /audio/stop"}}
		},
	},

	// --- TTS stop (interrupt Lumi speaking) ---
	{
		name:  "stop_talking",
		match: anyOf("stop talking", "be quiet", "ok stop"),
		exec: func(string) *Result {
			post("/tts/stop", "")
			return &Result{TTSText: "", Actions: []string{"POST /tts/stop"}}
		},
	},

	// --- Time ---
	{
		name:  "what_time",
		match: anyOf("what time", "whats the time", "what's the time"),
		exec: func(string) *Result {
			now := time.Now()
			text := fmt.Sprintf("It's %s.", now.Format("3:04 PM"))
			return &Result{TTSText: text, Actions: []string{"time.Now()"}}
		},
	},

	// --- Dim / brightness ---
	{
		name:  "dim",
		match: anyOf("dim the light", "dimmer", "dim light"),
		exec: func(string) *Result {
			post("/led/solid", `{"color":[80,60,40]}`)
			return &Result{TTSText: "Dimmed.", LEDChanged: true, Actions: []string{`POST /led/solid {"color":[80,60,40]}`}}
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
		body := fmt.Sprintf(`{"scene":"%s"}`, scene)
		post("/scene", body)
		return &Result{TTSText: reply, LEDChanged: true, Actions: []string{"POST /scene " + body}}
	}
}

func emotionExec(emotion, reply string) func(string) *Result {
	return func(string) *Result {
		body := fmt.Sprintf(`{"emotion":"%s","intensity":0.8}`, emotion)
		post("/emotion", body)
		return &Result{TTSText: reply, Emotion: emotion, Actions: []string{"POST /emotion " + body}}
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
	if err != nil {
		slog.Warn("[intent] lelamp call failed", "path", path, "error", err)
		return
	}
	if resp.StatusCode >= 400 {
		slog.Warn("[intent] lelamp returned error", "path", path, "status", resp.StatusCode)
	}
	resp.Body.Close()
}
