package led

// SPI encoding for WS2812 over SPI:
//
// Each WS2812 data bit is encoded as 3 SPI bits for timing:
//   - WS2812 bit 0 → SPI bits 100
//   - WS2812 bit 1 → SPI bits 110
//
// Each LED uses 24 bits in GRB order (G high byte first), yielding 72 SPI bits = 9 bytes per LED.

// encodeLUT maps each byte value 0-255 to its 3-byte SPI encoding.
// Built at init: for each of the 8 bits (MSB first), emit 3 SPI bits (0→100, 1→110), pack into 3 bytes.
var encodeLUT [256][3]byte

func init() {
	for b := 0; b < 256; b++ {
		var out [3]byte
		for i := 0; i < 8; i++ {
			inputBit := (b >> (7 - i)) & 1
			var spiBits byte
			if inputBit == 1 {
				spiBits = 0b110
			} else {
				spiBits = 0b100
			}
			for j := 0; j < 3; j++ {
				k := i*3 + j
				byteIdx := k / 8
				shift := 7 - (k % 8)
				if (spiBits>>(2-j))&1 != 0 {
					out[byteIdx] |= 1 << shift
				}
			}
		}
		encodeLUT[b] = out
	}
}

// bytesPerLED is the SPI byte count for one WS2812 LED (24 bits × 3 = 72 bits = 9 bytes).
const bytesPerLED = 9

// EncodeColors converts colors to the SPI waveform and writes into buf.
// buf must have length at least bytesPerLED*WS2812Num (i.e. 9*WS2812Num).
// Colors are sent in GRB order per WS2812 convention.
func encodeColors(colors [WS2812Num]Color, buf []byte) {
	for i := 0; i < WS2812Num; i++ {
		c := colors[i]
		// GRB order
		grb := [3]byte{c.G, c.R, c.B}
		base := i * bytesPerLED
		for ch := 0; ch < 3; ch++ {
			enc := encodeLUT[grb[ch]]
			buf[base+0] = enc[0]
			buf[base+1] = enc[1]
			buf[base+2] = enc[2]
			base += 3
		}
	}
}
