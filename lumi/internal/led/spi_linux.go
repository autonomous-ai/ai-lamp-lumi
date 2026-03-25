//go:build linux

package led

import (
	"fmt"
	"os"
	"unsafe"

	"golang.org/x/sys/unix"
)

// Linux SPI ioctl constants from <linux/spi/spidev.h>
const (
	spiIOCMagic = 'k'
)

func iow(t int, nr, size int) uint {
	return uint((1 << 30) | (t << 8) | nr | (size << 16))
}

var (
	spiIOCWRMode        = iow(int(spiIOCMagic), 1, 1)
	spiIOCWRBitsPerWord = iow(int(spiIOCMagic), 3, 1)
	spiIOCWRMaxSpeedHz  = iow(int(spiIOCMagic), 4, 4)
)

// openSPI opens the SPI device, configures mode 0, 8 bits/word, and the given speed.
// Returns an *os.File that must be closed by the caller.
func openSPI(device string, speedHz uint32) (*os.File, error) {
	f, err := os.OpenFile(device, os.O_WRONLY, 0)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", device, err)
	}
	fd := int(f.Fd())

	// SPI mode 0 (CPOL=0, CPHA=0)
	mode := uint8(0)
	if _, _, errno := unix.Syscall(unix.SYS_IOCTL, uintptr(fd), uintptr(spiIOCWRMode), uintptr(unsafe.Pointer(&mode))); errno != 0 {
		f.Close()
		return nil, fmt.Errorf("set SPI mode: %w", errno)
	}

	// 8 bits per word
	bits := uint8(8)
	if _, _, errno := unix.Syscall(unix.SYS_IOCTL, uintptr(fd), uintptr(spiIOCWRBitsPerWord), uintptr(unsafe.Pointer(&bits))); errno != 0 {
		f.Close()
		return nil, fmt.Errorf("set SPI bits per word: %w", errno)
	}

	// Speed in Hz
	if _, _, errno := unix.Syscall(unix.SYS_IOCTL, uintptr(fd), uintptr(spiIOCWRMaxSpeedHz), uintptr(unsafe.Pointer(&speedHz))); errno != 0 {
		f.Close()
		return nil, fmt.Errorf("set SPI speed: %w", errno)
	}

	return f, nil
}
