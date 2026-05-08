package server

// System-originated prompts sent to the OpenClaw agent. Kept separate from
// server.go so they can be translated without touching boot wiring, and so
// future system messages (skill watcher updates, wellbeing nudges, …) have
// an obvious home next to the wake greeting.

// wakeGreetingPrompt is the system message fired right after the voice
// pipeline becomes ready. SOUL.md already tells the agent to mirror the
// owner's language, but an English prompt still primes English replies for
// the very first turn — so emit the prompt itself in the owner's language.
// Empty / unknown lang → English.
func wakeGreetingPrompt(lang string) string {
	switch lang {
	case "vi":
		return "Bạn vừa thức dậy. Chào hỏi chủ nhân ngắn gọn."
	case "zh-CN":
		return "你刚刚醒来，请简短地问候一下主人。"
	case "zh-TW":
		return "你剛剛醒來，請簡短地問候一下主人。"
	}
	return "You just woke up. Greet the user briefly."
}
