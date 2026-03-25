package led

import (
	"math"
	"math/rand"
	"sync"
)

// breathState holds state for the idle breath effect (random cycle length).
var breathState struct {
	mu        sync.Mutex
	cycle     float64
	nextCycle float64
	phase     float64
	lastT     float64
}

// MaxBrightness is the global brightness cap (percent) to extend LED lifespan.
const MaxBrightness = 80.0

// colorWithBrightness returns c with brightness scaled by percent (0–100),
// capped at MaxBrightness to protect the LEDs.
func colorWithBrightness(c Color, percent float64) Color {
	if percent <= 0 {
		return Color{}
	}
	if percent > MaxBrightness {
		percent = MaxBrightness
	}
	scale := percent / 100
	return Color{
		R: uint8(float64(c.R) * scale),
		G: uint8(float64(c.G) * scale),
		B: uint8(float64(c.B) * scale),
	}
}

// effectIdle: dim blue (0, 135, 255) at 5% brightness. Transition from previous state is handled by the engine crossfade.
func effectIdle(t float64) [WS2812Num]Color {
	c := Color{R: 0, G: 135, B: 255}
	cc := colorWithBrightness(c, 5)
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectThinking: one bright spot (purple) rotating around the ring.
func effectThinking(t float64) [WS2812Num]Color {
	breathState.mu.Lock()
	if breathState.lastT < 0 {
		breathState.lastT = t
	}
	dt := t - breathState.lastT
	breathState.lastT = t
	breathState.phase += dt * (2 * math.Pi / breathState.cycle)
	if breathState.phase >= 2*math.Pi {
		breathState.phase -= 2 * math.Pi
		breathState.cycle = breathState.nextCycle
		breathState.nextCycle = 2.0 + rand.Float64()*5.0 // 2s to 7s
	}
	phase := breathState.phase
	breathState.mu.Unlock()

	breath := (math.Sin(phase-math.Pi/2) + 1) / 2
	mix := 0.05 + 0.95*breath
	var out [WS2812Num]Color
	c := Color{R: uint8(0), G: uint8(200 * mix), B: uint8(255 * mix)}
	cc := colorWithBrightness(c, 80)
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectWorking: plain blue (0, 135, 255), no animation.
func effectWorking(t float64) [WS2812Num]Color {
	c := Color{R: 0, G: 135, B: 255}
	cc := colorWithBrightness(c, 80)
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectWorkingNoInternet: amber/orange to indicate connected but no internet (slow blink).
func effectWorkingNoInternet(t float64) [WS2812Num]Color {
	on := int(t/1.0)%2 == 0 // 1s on, 1s off
	var c Color
	if on {
		c = Color{R: 255, G: 50, B: 0}
	} else {
		c = Color{R: 0, G: 0, B: 0}
	}
	cc := colorWithBrightness(c, 80)
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectConnectionMode: orange blink (on/off every 0.25s).
func effectConnectionMode(t float64) [WS2812Num]Color {
	on := int(t/0.5)%2 == 0
	var c Color
	if on {
		c = Color{R: 255, G: 255, B: 255}
	} else {
		c = Color{R: 0, G: 0, B: 0}
	}
	var out [WS2812Num]Color
	cc := colorWithBrightness(c, 80)
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectBooting: white (setup style).
func effectBooting(t float64) [WS2812Num]Color {
	c := Color{R: 255, G: 255, B: 255}
	cc := colorWithBrightness(c, 80)
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectError: red blink.
func effectError(t float64) [WS2812Num]Color {
	c := Color{R: 255, G: 50, B: 0}
	cc := colorWithBrightness(c, 80)
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectPowerOff: off.
func effectPowerOff(t float64) [WS2812Num]Color {
	c := Color{R: 255, G: 50, B: 0}
	cc := colorWithBrightness(c, 80)
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectFactoryReset: white (setup style).
func effectFactoryReset(t float64) [WS2812Num]Color {
	c := Color{R: 255, G: 255, B: 255}
	cc := colorWithBrightness(c, 80)
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = cc
	}
	return out
}

// effectRun returns the current frame for the given state and elapsed time t (seconds).
func effectRun(s State, t float64) [WS2812Num]Color {
	switch s {
	case Idle:
		return effectIdle(t)
	case Thinking:
		return effectThinking(t)
	case Working:
		return effectWorking(t)
	case WorkingNoInternet:
		return effectWorkingNoInternet(t)
	case ConnectionMode:
		return effectConnectionMode(t)
	case Booting:
		return effectBooting(t)
	case Error:
		return effectError(t)
	case PowerOff:
		return effectPowerOff(t)
	case FactoryReset:
		return effectFactoryReset(t)
	default:
		return effectIdle(t)
	}
}

// lerpColor linearly interpolates between two colors by t (0.0 = a, 1.0 = b).
func lerpColor(a, b Color, t float64) Color {
	if t <= 0 {
		return a
	}
	if t >= 1 {
		return b
	}
	return Color{
		R: uint8(float64(a.R) + (float64(b.R)-float64(a.R))*t),
		G: uint8(float64(a.G) + (float64(b.G)-float64(a.G))*t),
		B: uint8(float64(a.B) + (float64(b.B)-float64(a.B))*t),
	}
}

// blendFrames blends two LED frames by t (0.0 = from, 1.0 = to).
func blendFrames(from, to [WS2812Num]Color, t float64) [WS2812Num]Color {
	var out [WS2812Num]Color
	for i := 0; i < WS2812Num; i++ {
		out[i] = lerpColor(from[i], to[i], t)
	}
	return out
}

func init() {
	breathState.cycle = 4.0
	breathState.nextCycle = 4.0
	breathState.lastT = -1
}
