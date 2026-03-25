package led

import (
	"os"
	"sync"
	"time"
)

// WS2812 strip size; data line is SPI MOSI (GPIO10) on Raspberry Pi.
const (
	WS2812Num = 8
)

// Default SPI device and speed for WS2812 on Raspberry Pi.
const (
	defaultSPIDevice  = "/dev/spidev0.0"
	defaultSPISpeedHz = 2_400_000
)

// Color is RGB 0–255.
type Color struct {
	R, G, B uint8
}

// Driver drives an 8-LED ring via SPI (/dev/spidev0.0). Pure Go, no CGO.
type Driver struct {
	spi    *os.File
	buffer []byte
	mu     sync.Mutex
	colors [WS2812Num]Color
	stop   chan struct{}
	done   chan struct{}
}

// ProvideDriver initializes the SPI device and returns a driver for an 8-LED ring.
// Uses /dev/spidev0.0 at 2.4 MHz. Requires root or SPI device access on Raspberry Pi.
func ProvideDriver() (*Driver, error) {
	return ProvideDriverDevice(defaultSPIDevice)
}

// ProvideDriverDevice is like ProvideDriver but allows specifying the SPI device path.
func ProvideDriverDevice(device string) (*Driver, error) {
	spi, err := openSPI(device, defaultSPISpeedHz)
	if err != nil {
		return nil, err
	}
	bufSize := bytesPerLED * WS2812Num
	d := &Driver{
		spi:    spi,
		buffer: make([]byte, bufSize),
		stop:   make(chan struct{}),
		done:   make(chan struct{}),
	}
	// One-time clear: ensure strip starts in a known state (all off).
	d.mu.Lock()
	for i := range d.colors {
		d.colors[i] = Color{}
	}
	d.mu.Unlock()
	d.Render()
	go d.loop()
	return d, nil
}

func (d *Driver) loop() {
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	defer close(d.done)
	for {
		select {
		case <-d.stop:
			return
		case <-ticker.C:
			d.Render()
		}
	}
}

func (d *Driver) SetColor(c Color) {
	d.mu.Lock()
	for i := 0; i < WS2812Num; i++ {
		d.colors[i] = c
	}
	d.mu.Unlock()
	d.Render()
}

func (d *Driver) SetColors(colors [WS2812Num]Color) {
	d.mu.Lock()
	d.colors = colors
	d.mu.Unlock()
	d.Render()
}

func (d *Driver) Render() {
	d.mu.Lock()
	colors := d.colors
	d.mu.Unlock()

	encodeColors(colors, d.buffer)

	for n := 0; n < len(d.buffer); {
		written, err := d.spi.Write(d.buffer[n:])
		if err != nil {
			return
		}
		n += written
	}

	// WS2812 reset/latch: ≥50µs low. Use 80µs for safety.
	time.Sleep(80 * time.Microsecond)
}

func (d *Driver) Close() error {
	close(d.stop)
	<-d.done
	return d.spi.Close()
}
