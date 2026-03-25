package led

import (
	"testing"
)

func TestEncodeColors_BufferLength(t *testing.T) {
	colors := [WS2812Num]Color{}
	buf := make([]byte, bytesPerLED*WS2812Num)
	encodeColors(colors, buf)
	if len(buf) != 9*WS2812Num {
		t.Errorf("expected buffer length %d, got %d", 9*WS2812Num, len(buf))
	}
}

func TestEncodeColors_OneLEDNineBytes(t *testing.T) {
	var colors [WS2812Num]Color
	colors[0] = Color{R: 255, G: 255, B: 255}
	buf := make([]byte, bytesPerLED*WS2812Num)
	encodeColors(colors, buf)

	// First LED: 9 bytes. For 0xFF in G,R,B each, every bit is 1 → 110
	// So first 3 bytes (G) should be encoded form of 0xFF
	firstLED := buf[:9]
	if len(firstLED) != 9 {
		t.Fatalf("first LED must be 9 bytes, got %d", len(firstLED))
	}

	// 0xFF: all 8 bits are 1 → 8×110 = 110110110110110110110110
	// Byte 0: 11011011 = 0xDB, Byte 1: 01101101 = 0x6D, Byte 2: 10110110 = 0xB6
	enc := encodeLUT[0xFF]
	if enc[0] != 0xDB || enc[1] != 0x6D || enc[2] != 0xB6 {
		t.Errorf("encodeLUT[0xFF] = %02x %02x %02x, want DB 6D B6", enc[0], enc[1], enc[2])
	}
	// First LED is GRB, so first 3 bytes = G, next 3 = R, next 3 = B (all 0xFF)
	expected := []byte{0xDB, 0x6D, 0xB6, 0xDB, 0x6D, 0xB6, 0xDB, 0x6D, 0xB6}
	for i := 0; i < 9; i++ {
		if firstLED[i] != expected[i] {
			t.Errorf("first LED byte[%d] = 0x%02x, want 0x%02x", i, firstLED[i], expected[i])
		}
	}
}

func TestEncodeColors_ZeroBitsProduce100(t *testing.T) {
	// 0x00: all bits 0 → 8×100
	enc := encodeLUT[0x00]
	// 100100100100100100100100
	// Byte 0: 10010010 = 0x92, Byte 1: 01001001 = 0x49, Byte 2: 00100100 = 0x24
	if enc[0] != 0x92 || enc[1] != 0x49 || enc[2] != 0x24 {
		t.Errorf("encodeLUT[0x00] = %02x %02x %02x, want 92 49 24", enc[0], enc[1], enc[2])
	}
}

func TestEncodeColors_GRBOrder(t *testing.T) {
	// Single LED: G=0x00, R=0xFF, B=0x00
	var colors [WS2812Num]Color
	colors[0] = Color{R: 255, G: 0, B: 0}
	buf := make([]byte, bytesPerLED*WS2812Num)
	encodeColors(colors, buf)

	// First 3 bytes = G (0x00) → 92 49 24
	// Next 3 bytes = R (0xFF) → DB 6D B6
	// Last 3 bytes = B (0x00) → 92 49 24
	expG := encodeLUT[0]
	expR := encodeLUT[255]
	expB := encodeLUT[0]
	for i := 0; i < 3; i++ {
		if buf[i] != expG[i] {
			t.Errorf("G byte[%d] = 0x%02x, want 0x%02x", i, buf[i], expG[i])
		}
		if buf[3+i] != expR[i] {
			t.Errorf("R byte[%d] = 0x%02x, want 0x%02x", i, buf[3+i], expR[i])
		}
		if buf[6+i] != expB[i] {
			t.Errorf("B byte[%d] = 0x%02x, want 0x%02x", i, buf[6+i], expB[i])
		}
	}
}
