package http

import (
	"log/slog"
	"math/rand"
	"net/http"
	"strings"
)

// Dead air filler — plays a short TTS cue via LeLamp after forwarding a voice
// command to OpenClaw, filling the silence while the LLM processes (~5-15s).
//
// Uses tts_service.speak() (locks mic) which is intentional — user is done
// speaking and waiting for the response.
//
// Disabled when Fillers slice is empty.

// Fillers is the list of short phrases to play as dead air cues.
// Empty slice = feature disabled. Override at init or via config.
var Fillers = []string{
	"Hmm, let me think",
	"Ok, got it",
	"Sure, one moment",
	"Right, let me check",
	"Alright, hold on",
	"Oh, interesting",
	"Ok, let me see",
	"Hmm, let me work on that",
}

// LeLampSpeakURL is the endpoint to trigger TTS on LeLamp.
const LeLampSpeakURL = "http://127.0.0.1:5001/voice/speak"

// PlayDeadAirFiller sends a random filler phrase to LeLamp TTS.
// No-op if Fillers is empty. Safe to call from a goroutine.
func PlayDeadAirFiller() {
	if len(Fillers) == 0 {
		return
	}
	filler := Fillers[rand.Intn(len(Fillers))]
	slog.Info("dead air filler", "component", "sensing", "filler", filler)
	resp, err := http.Post(
		LeLampSpeakURL,
		"application/json",
		strings.NewReader(`{"text":"`+filler+`"}`),
	)
	if err != nil {
		slog.Warn("dead air filler failed", "component", "sensing", "error", err)
		return
	}
	resp.Body.Close()
	slog.Info("dead air filler sent", "component", "sensing", "filler", filler)
}
