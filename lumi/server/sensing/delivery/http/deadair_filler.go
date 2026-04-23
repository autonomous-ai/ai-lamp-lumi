package http

import (
	"log/slog"
	"math/rand"

	"go-lamp.autonomous.ai/lib/lelamp"
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
	"One sec",
	"Ah, ok ok",
	"Let me figure this out",
	"Hmm, give me a moment",
	"Oh, right",
	"Let me look into that",
	"Sure, hang on",
	"Ok, thinking",
	"Ah, let me see",
	"Hmm, hold on a sec",
	"Got it, one moment",
	"Oh, let me check that",
}

// PlayDeadAirFiller sends a random filler phrase to LeLamp TTS.
// No-op if Fillers is empty. Safe to call from a goroutine.
func PlayDeadAirFiller() {
	if len(Fillers) == 0 {
		return
	}
	filler := Fillers[rand.Intn(len(Fillers))]
	slog.Info("dead air filler", "component", "sensing", "filler", filler)
	if err := lelamp.SpeakInterruptible(filler); err != nil {
		slog.Warn("dead air filler failed", "component", "sensing", "error", err)
		return
	}
	slog.Info("dead air filler sent", "component", "sensing", "filler", filler)
}
