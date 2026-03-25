package device

import (
	"os"
	"regexp"
	"strings"
)

// GetDeviceMac returns the hardware ID in Intern-XXXX format (last 4 chars of Pi serial).
// Same logic as setup.sh. Empty string if not on Pi or serial unavailable.
func GetDeviceMac() string {
	serial := readSerial()
	if serial == "" {
		return ""
	}
	suffix := serial
	if len(serial) > 4 {
		suffix = serial[len(serial)-4:]
	}
	return "Intern-" + suffix
}

func readSerial() string {
	// Pi 5: device-tree; fallback: cpuinfo
	if b, err := os.ReadFile("/proc/device-tree/serial-number"); err == nil {
		return strings.TrimSpace(strings.TrimRight(string(b), "\x00"))
	}
	if b, err := os.ReadFile("/proc/cpuinfo"); err == nil {
		re := regexp.MustCompile(`(?m)^Serial\s*:\s*(\S+)`)
		if m := re.FindSubmatch(b); len(m) >= 2 {
			return strings.TrimSpace(string(m[1]))
		}
	}
	return ""
}
