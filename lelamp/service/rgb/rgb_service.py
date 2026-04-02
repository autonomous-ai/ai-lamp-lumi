from typing import Any, List, Union
from ..base import ServiceBase


def _is_pi5() -> bool:
    """Detect Raspberry Pi 5 via device-tree model string."""
    try:
        with open("/proc/device-tree/model", "r") as f:
            return "pi 5" in f.read().lower()
    except OSError:
        return False


def _color_tuple(color_code):
    """Convert color (int or RGB tuple) to (r, g, b) tuple."""
    if isinstance(color_code, tuple) and len(color_code) == 3:
        return color_code
    elif isinstance(color_code, int):
        r = (color_code >> 16) & 0xFF
        g = (color_code >> 8) & 0xFF
        b = color_code & 0xFF
        return (r, g, b)
    return None


class _StripPWM:
    """Pi 4 — rpi_ws281x PWM driver on GPIO 12."""

    def __init__(self, led_count, led_pin, led_freq_hz, led_dma,
                 led_invert, led_brightness, led_channel):
        from rpi_ws281x import PixelStrip
        self._strip = PixelStrip(
            led_count, led_pin, led_freq_hz, led_dma,
            led_invert, led_brightness, led_channel,
        )
        self._strip.begin()

    def setPixelColor(self, i, color_tuple):
        from rpi_ws281x import Color
        self._strip.setPixelColor(i, Color(*color_tuple))

    def fill(self, color_tuple, count):
        from rpi_ws281x import Color
        c = Color(*color_tuple)
        for i in range(count):
            self._strip.setPixelColor(i, c)

    def show(self):
        self._strip.show()

    def getPixelColor(self, index):
        raw = self._strip.getPixelColor(index)
        return (raw >> 16) & 0xFF, (raw >> 8) & 0xFF, raw & 0xFF

    def deinit(self):
        pass


class _StripSPI:
    """Pi 5 — neopixel_spi over SPI MOSI (GPIO 10)."""

    def __init__(self, led_count, led_brightness):
        import board
        import busio
        import neopixel_spi
        spi = busio.SPI(board.SCK, MOSI=board.MOSI)
        self._pixels = neopixel_spi.NeoPixel_SPI(
            spi, led_count,
            brightness=led_brightness,
            auto_write=False,
            pixel_order=neopixel_spi.GRB,
        )

    def setPixelColor(self, i, color_tuple):
        self._pixels[i] = color_tuple

    def fill(self, color_tuple, count):
        self._pixels.fill(color_tuple)

    def show(self):
        self._pixels.show()

    def getPixelColor(self, index):
        return tuple(self._pixels[index])

    def deinit(self):
        self._pixels.deinit()


class RGBService(ServiceBase):
    """Unified RGB LED service — auto-detects Pi 4 (PWM) vs Pi 5 (SPI)."""

    def __init__(self,
                 led_count: int = 64,
                 led_pin: int = 12,
                 led_freq_hz: int = 800000,
                 led_dma: int = 10,
                 led_brightness: int = 255,
                 led_invert: bool = False,
                 led_channel: int = 0):
        super().__init__("rgb")
        self.led_count = led_count
        self._driver = None

        pi5 = _is_pi5()
        try:
            if pi5:
                self._driver = _StripSPI(led_count, led_brightness / 255.0)
                self.logger.info("RGB using SPI driver (Pi 5)")
            else:
                self._driver = _StripPWM(
                    led_count, led_pin, led_freq_hz, led_dma,
                    led_invert, led_brightness, led_channel,
                )
                self.logger.info("RGB using PWM driver (Pi 4)")
        except Exception as e:
            self.logger.error(f"RGB driver init failed: {e}")

        # Expose .strip.getPixelColor() for server.py compatibility
        self.strip = self

    def getPixelColor(self, index: int) -> int:
        """Return packed 0xRRGGBB int for server.py compatibility."""
        if not self._driver:
            return 0
        r, g, b = self._driver.getPixelColor(index)
        return (r << 16) | (g << 8) | b

    def handle_event(self, event_type: str, payload: Any):
        if event_type == "solid":
            self._handle_solid(payload)
        elif event_type == "paint":
            self._handle_paint(payload)
        else:
            self.logger.warning(f"Unknown event type: {event_type}")

    def _handle_solid(self, color_code: Union[int, tuple]):
        """Fill entire strip with single color"""
        if not self._driver:
            return
        color = _color_tuple(color_code)
        if color is None:
            self.logger.error(f"Invalid color format: {color_code}")
            return
        self._driver.fill(color, self.led_count)
        self._driver.show()
        self.logger.debug(f"Applied solid color: {color_code}")

    def _handle_paint(self, colors: List[Union[int, tuple]]):
        """Set individual pixel colors from array"""
        if not self._driver:
            return
        if not isinstance(colors, list):
            self.logger.error(f"Paint payload must be a list, got: {type(colors)}")
            return
        max_pixels = min(len(colors), self.led_count)
        for i in range(max_pixels):
            color = _color_tuple(colors[i])
            if color is None:
                self.logger.warning(f"Invalid color at index {i}: {colors[i]}")
                continue
            self._driver.setPixelColor(i, color)
        self._driver.show()
        self.logger.debug(f"Applied paint pattern with {max_pixels} colors")

    def clear(self):
        """Turn off all LEDs"""
        if not self._driver:
            return
        self._driver.fill((0, 0, 0), self.led_count)
        self._driver.show()

    def stop(self, timeout: float = 5.0):
        """Override stop to clear LEDs before stopping"""
        self.clear()
        if self._driver:
            self._driver.deinit()
        super().stop(timeout)
