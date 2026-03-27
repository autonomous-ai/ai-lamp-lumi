package resetbutton

import (
	"context"
	"log/slog"
	"sync"
	"time"

	"github.com/warthog618/go-gpiocdev"
)

const (
	gpioResetButton       = 26
	powerOffThreshold     = 3 * time.Second
	factoryResetThreshold = 10 * time.Second
	pollInterval          = 200 * time.Millisecond
)

// Service watches GPIO 26 (reset button). On short press (release before hold
// threshold) it calls onPress once. When pressed and held then released: 3s+
// triggers onPowerOff, 10s+ triggers onFactoryReset (mutually exclusive; onPress
// is not fired for long press). All actions fire on button release. Button is
// active-low with internal pull-up (press = pin to GND).
type Service struct {
	chip *gpiocdev.Chip
	line *gpiocdev.Line

	mu      sync.Mutex
	started bool
	stop    chan struct{}
	done    chan struct{} // closed when run() has exited
}

// ProvideService opens gpiochip0. The line is requested with pull-up when Start() is called.
// Returns (nil, error) when not on a device with GPIO (e.g. dev machine).
// For Wire: use as resetbutton.ProvideService; injector returns (*Server, error).
func ProvideService() (*Service, error) {
	chip, err := gpiocdev.NewChip("gpiochip0")
	if err != nil {
		return nil, err
	}
	return &Service{chip: chip}, nil
}

// Start requests the GPIO line with pull-up (pin idle at 1) then starts watching the button
// in a goroutine. On short press (release before hold threshold), onPress is called once.
// When press-and-hold then release: 3s+ calls onPowerOff, 10s+ calls onFactoryReset
// (mutually exclusive). All action callbacks fire on button release. Optional
// onPowerOffThreshold and onFactoryResetThreshold fire when hold duration crosses 3s or 10s
// (while still holding), for LED feedback. Call Close when done.
func (s *Service) Start(ctx context.Context, onPress, onPowerOff, onFactoryReset func(), onPowerOffThreshold, onFactoryResetThreshold func()) {
	s.mu.Lock()
	if s.started {
		s.mu.Unlock()
		return
	}
	line, err := s.chip.RequestLine(gpioResetButton, gpiocdev.AsInput, gpiocdev.WithPullUp)
	if err != nil {
		s.mu.Unlock()
		slog.Error("request line failed", "component", "resetbutton", "gpio", gpioResetButton, "error", err)
		return
	}
	s.line = line
	s.started = true
	s.stop = make(chan struct{})
	s.done = make(chan struct{})
	s.mu.Unlock()

	go func() {
		defer close(s.done)
		s.run(ctx, onPress, onPowerOff, onFactoryReset, onPowerOffThreshold, onFactoryResetThreshold)
	}()
}

func (s *Service) run(ctx context.Context, onPress, onPowerOff, onFactoryReset func(), onPowerOffThreshold, onFactoryResetThreshold func()) {
	var holdStart time.Time
	powerOffThresholdFired := false
	factoryResetThresholdFired := false
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-s.stop:
			return
		case <-ticker.C:
			val, err := s.line.Value()
			if err != nil {
				slog.Error("read GPIO failed", "component", "resetbutton", "gpio", gpioResetButton, "error", err)
				holdStart = time.Time{}
				powerOffThresholdFired = false
				factoryResetThresholdFired = false
				continue
			}
			// Active low: 0 = pressed, 1 = released
			if val == 0 {
				if holdStart.IsZero() {
					holdStart = time.Now()
				}
				elapsed := time.Since(holdStart)
				if !powerOffThresholdFired && elapsed >= powerOffThreshold {
					powerOffThresholdFired = true
					if onPowerOffThreshold != nil {
						go onPowerOffThreshold()
					}
				}
				if !factoryResetThresholdFired && elapsed >= factoryResetThreshold {
					factoryResetThresholdFired = true
					if onFactoryResetThreshold != nil {
						go onFactoryResetThreshold()
					}
				}
			} else {
				// Released: fire action based on hold duration
				if !holdStart.IsZero() {
					elapsed := time.Since(holdStart)
					if elapsed >= factoryResetThreshold {
						slog.Info("factory reset detected", "component", "resetbutton", "gpio", gpioResetButton, "threshold", factoryResetThreshold)
						if onFactoryReset != nil {
							go onFactoryReset()
						}
					} else if elapsed >= powerOffThreshold {
						slog.Info("power off detected", "component", "resetbutton", "gpio", gpioResetButton, "threshold", powerOffThreshold)
						if onPowerOff != nil {
							go onPowerOff()
						}
					} else if onPress != nil {
						go onPress()
					}
				}
				holdStart = time.Time{}
				powerOffThresholdFired = false
				factoryResetThresholdFired = false
			}
		}
	}
}

// Close stops the watch and releases the GPIO line and chip.
func (s *Service) Close() error {
	s.mu.Lock()
	if s.stop != nil {
		close(s.stop)
		s.stop = nil
	}
	done := s.done
	s.mu.Unlock()
	if done != nil {
		<-done
	}
	s.mu.Lock()
	s.started = false
	line := s.line
	s.line = nil
	s.mu.Unlock()
	if line != nil {
		_ = line.Close()
	}
	if s.chip != nil {
		return s.chip.Close()
	}
	return nil
}
