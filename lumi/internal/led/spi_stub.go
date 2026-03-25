//go:build !linux

package led

import (
	"fmt"
	"os"
)

// openSPI is not available on non-Linux platforms.
func openSPI(device string, speedHz uint32) (*os.File, error) {
	return nil, fmt.Errorf("SPI LED driver requires Linux (target: Raspberry Pi)")
}
