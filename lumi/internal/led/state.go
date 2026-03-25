package led

import (
	"fmt"
	"strings"
	"time"
)

// Transition describes how the LED ring moves from one state to another.
type Transition int

const (
	// TransitionInstant snaps immediately to the new state (no blending).
	TransitionInstant Transition = iota
	// TransitionCrossfade linearly interpolates RGB from old colors to new over the transition duration.
	TransitionCrossfade
	// TransitionFadeThroughBlack fades old colors to black, then fades new colors from black.
	TransitionFadeThroughBlack
)

// DefaultTransitionDuration is the default time for crossfade / fade-through-black.
const DefaultTransitionDuration = 300 * time.Millisecond

// State represents the LED display state (priority-based state machine).
type State int

const (
	Booting State = iota
	// Idle: LED off (no color).
	Idle
	// ConnectionMode: has internet but network/LLM/Telegram not set (needs configuration).
	ConnectionMode
	Thinking
	Working
	// WorkingNoInternet: in STA mode but no internet connectivity.
	WorkingNoInternet
	Error
	// PowerOff: turn off the LED ring.
	PowerOff
	// FactoryReset: reset the LED ring to factory defaults.
	FactoryReset
)

// ValidStateNames lists accepted values for ParseState.
var ValidStateNames = []string{"booting", "idle", "connectionmode", "thinking", "working", "workingnointernet", "error"}

// String returns the lowercase name of the state.
func (s State) String() string {
	switch s {
	case Booting:
		return "booting"
	case Idle:
		return "idle"
	case ConnectionMode:
		return "connectionmode"
	case Thinking:
		return "thinking"
	case Working:
		return "working"
	case WorkingNoInternet:
		return "workingnointernet"
	case Error:
		return "error"
	case PowerOff:
		return "poweroff"
	case FactoryReset:
		return "factoryreset"
	default:
		return fmt.Sprintf("unknown(%d)", int(s))
	}
}

// ParseState converts a case-insensitive string to a State.
// Returns an error when the name is not recognised.
func ParseState(name string) (State, error) {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "booting":
		return Booting, nil
	case "idle":
		return Idle, nil
	case "connectionmode", "connection":
		return ConnectionMode, nil
	case "thinking":
		return Thinking, nil
	case "working":
		return Working, nil
	case "workingnointernet", "working_no_internet":
		return WorkingNoInternet, nil
	case "error":
		return Error, nil
	case "poweroff":
		return PowerOff, nil
	case "factoryreset":
		return FactoryReset, nil
	default:
		return 0, fmt.Errorf("unknown LED state %q", name)
	}
}

// priority returns the state priority (higher wins).
func priority(s State) int {
	switch s {
	case FactoryReset:
		return 100
	case PowerOff:
		return 90
	case Error:
		return 80
	case WorkingNoInternet:
		return 60
	case Working:
		return 50
	case Thinking:
		return 40
	case ConnectionMode:
		return 30
	case Booting:
		return 20
	case Idle:
		return 10
	default:
		return 0
	}
}
