from typing import Any, List, Union
from ..base import ServiceBase

try:
    import board
    import busio
    import neopixel_spi
    _HAS_SPI = True
except ImportError:
    _HAS_SPI = False


def _color_to_int(color_code):
    """Convert RGB tuple or int to (r, g, b) tuple for neopixel_spi."""
    if isinstance(color_code, tuple) and len(color_code) == 3:
        return color_code
    elif isinstance(color_code, int):
        # Extract RGB from packed int (0xRRGGBB)
        r = (color_code >> 16) & 0xFF
        g = (color_code >> 8) & 0xFF
        b = color_code & 0xFF
        return (r, g, b)
    return None


class _StripCompat:
    """Thin wrapper around NeoPixel_SPI that adds getPixelColor()
    so server.py code (rgb_service.strip.getPixelColor) works unchanged."""

    def __init__(self, pixels):
        self._pixels = pixels

    def getPixelColor(self, index: int) -> int:
        r, g, b = self._pixels[index]
        return (r << 16) | (g << 8) | b

    def __getattr__(self, name):
        return getattr(self._pixels, name)


class RGBService(ServiceBase):
    """Pi 5 SPI-based NeoPixel RGB service.

    Uses adafruit-circuitpython-neopixel-spi on SPI MOSI (GPIO 10)
    because Pi 5 RP1 chip does not support rpi_ws281x PWM.
    """

    def __init__(self,
                 led_count: int = 64,
                 led_brightness: float = 1.0):
        super().__init__("rgb")

        self.led_count = led_count

        if not _HAS_SPI:
            self.logger.error("neopixel_spi not available — install adafruit-circuitpython-neopixel-spi")
            self.strip = None
            self._pixels = None
            return

        try:
            spi = busio.SPI(board.SCK, MOSI=board.MOSI)
            self._pixels = neopixel_spi.NeoPixel_SPI(
                spi,
                led_count,
                brightness=led_brightness,
                auto_write=False,
                pixel_order=neopixel_spi.GRB,
            )
            self.strip = _StripCompat(self._pixels)
        except Exception as e:
            self.logger.error(f"Failed to init SPI NeoPixel: {e}")
            self.strip = None
            self._pixels = None

    def handle_event(self, event_type: str, payload: Any):
        if event_type == "solid":
            self._handle_solid(payload)
        elif event_type == "paint":
            self._handle_paint(payload)
        else:
            self.logger.warning(f"Unknown event type: {event_type}")

    def _handle_solid(self, color_code: Union[int, tuple]):
        """Fill entire strip with single color"""
        if not self._pixels:
            return

        color = _color_to_int(color_code)
        if color is None:
            self.logger.error(f"Invalid color format: {color_code}")
            return

        self._pixels.fill(color)
        self._pixels.show()
        self.logger.debug(f"Applied solid color: {color_code}")

    def _handle_paint(self, colors: List[Union[int, tuple]]):
        """Set individual pixel colors from array"""
        if not self._pixels:
            return

        if not isinstance(colors, list):
            self.logger.error(f"Paint payload must be a list, got: {type(colors)}")
            return

        max_pixels = min(len(colors), self.led_count)

        for i in range(max_pixels):
            color = _color_to_int(colors[i])
            if color is None:
                self.logger.warning(f"Invalid color at index {i}: {colors[i]}")
                continue
            self._pixels[i] = color

        self._pixels.show()
        self.logger.debug(f"Applied paint pattern with {max_pixels} colors")

    def clear(self):
        """Turn off all LEDs"""
        if not self._pixels:
            return
        self._pixels.fill((0, 0, 0))
        self._pixels.show()

    def stop(self, timeout: float = 5.0):
        """Override stop to clear LEDs before stopping"""
        self.clear()
        if self._pixels:
            self._pixels.deinit()
        super().stop(timeout)
