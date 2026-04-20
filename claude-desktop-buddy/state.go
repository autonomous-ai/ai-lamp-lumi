package main

import (
	"log"
	"sync"
	"time"
)

type BuddyState string

const (
	StateSleep     BuddyState = "sleep"
	StateIdle      BuddyState = "idle"
	StateBusy      BuddyState = "busy"
	StateAttention BuddyState = "attention"
	StateHeart     BuddyState = "heart"
	StateCelebrate BuddyState = "celebrate"
)

// StateMachine derives buddy state from BLE heartbeats.
type StateMachine struct {
	mu sync.RWMutex

	connected    bool
	current      BuddyState
	lastHB       *Heartbeat
	lastHBTime   time.Time
	prevTokens   int
	transientEnd time.Time // when heart/celebrate expires

	// Approval tracking
	pendingPrompt *Prompt
	promptTime    time.Time
	approvedCount int
	deniedCount   int

	// Callbacks
	onStateChange func(old, new BuddyState, hb *Heartbeat)
}

func NewStateMachine(onChange func(old, new BuddyState, hb *Heartbeat)) *StateMachine {
	return &StateMachine{
		current:       StateSleep,
		onStateChange: onChange,
	}
}

func (sm *StateMachine) State() BuddyState {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return sm.current
}

func (sm *StateMachine) Connected() bool {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return sm.connected
}

func (sm *StateMachine) LastHeartbeat() *Heartbeat {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return sm.lastHB
}

func (sm *StateMachine) PendingPrompt() *Prompt {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return sm.pendingPrompt
}

func (sm *StateMachine) ApprovalStats() (approved, denied int) {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return sm.approvedCount, sm.deniedCount
}

func (sm *StateMachine) SetConnected(connected bool) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sm.connected = connected
	if !connected {
		sm.pendingPrompt = nil
		sm.transition(StateSleep)
	} else {
		sm.transition(StateIdle)
	}
}

// HandleHeartbeat processes a heartbeat and derives state.
func (sm *StateMachine) HandleHeartbeat(hb *Heartbeat) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sm.lastHB = hb
	sm.lastHBTime = time.Now()

	// Check for token milestone (every 50K)
	if sm.prevTokens > 0 && hb.Tokens/50000 > sm.prevTokens/50000 {
		log.Printf("[buddy] token milestone: %d", hb.Tokens)
		sm.prevTokens = hb.Tokens
		sm.transientEnd = time.Now().Add(3 * time.Second)
		sm.transition(StateCelebrate)
		return
	}
	sm.prevTokens = hb.Tokens

	// Don't override transient states until they expire
	if (sm.current == StateHeart || sm.current == StateCelebrate) && time.Now().Before(sm.transientEnd) {
		return
	}

	// Derive state from heartbeat fields
	if hb.Prompt != nil {
		sm.pendingPrompt = hb.Prompt
		sm.promptTime = time.Now()
		sm.transition(StateAttention)
	} else if hb.Running > 0 {
		sm.pendingPrompt = nil
		sm.transition(StateBusy)
	} else {
		sm.pendingPrompt = nil
		sm.transition(StateIdle)
	}
}

// Approved records an approval and triggers heart state if fast enough.
func (sm *StateMachine) Approved() {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sm.approvedCount++
	sm.pendingPrompt = nil

	if time.Since(sm.promptTime) < 5*time.Second {
		sm.transientEnd = time.Now().Add(3 * time.Second)
		sm.transition(StateHeart)
	} else {
		sm.transition(StateIdle)
	}
}

// Denied records a denial.
func (sm *StateMachine) Denied() {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sm.deniedCount++
	sm.pendingPrompt = nil
	sm.transition(StateIdle)
}

func (sm *StateMachine) transition(next BuddyState) {
	if sm.current == next {
		return
	}
	old := sm.current
	sm.current = next
	log.Printf("[buddy] state: %s → %s", old, next)
	if sm.onStateChange != nil {
		go sm.onStateChange(old, next, sm.lastHB)
	}
}

// RunTransientExpiry checks if transient states have expired.
// Call this from a ticker goroutine.
func (sm *StateMachine) CheckTransientExpiry() {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	if (sm.current == StateHeart || sm.current == StateCelebrate) && time.Now().After(sm.transientEnd) {
		// Re-derive from last heartbeat
		if sm.lastHB != nil {
			if sm.lastHB.Running > 0 {
				sm.transition(StateBusy)
			} else {
				sm.transition(StateIdle)
			}
		} else {
			sm.transition(StateIdle)
		}
	}
}
