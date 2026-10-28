"""LCD framebuffer renderer for the AK820 Pro's 128x128 TFT screen.

Port of src/lcd.rs. Uses Pillow for text rendering and exports RGB565
little-endian bytes ready for UsbDevice.upload_image().
"""

from __future__ import annotations

import datetime
from typing import Optional

from . import protocol as p
from .stats import Stats

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]

# Rgb565::new(31, 63, 0): bright yellow. White is nearly invisible on this TFT.
TEXT_COLOR = (255, 255, 0)


def _load_font():
    try:
        return ImageFont.load_default(size=10)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


class LcdFramebuffer:
    """A 128x128 RGB framebuffer that exports as RGB565."""

    def __init__(self) -> None:
        if Image is None:
            raise RuntimeError("Pillow is not installed. Run: pip install Pillow")
        self.image = Image.new("RGB", (p.LCD_WIDTH, p.LCD_HEIGHT), (0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)
        self.draw.fontmode = "1"  # no anti-aliasing: crisp pixels like a bitmap font
        self.font = _load_font()

    def clear_black(self) -> None:
        self.draw.rectangle([0, 0, p.LCD_WIDTH, p.LCD_HEIGHT], fill=(0, 0, 0))

    def as_rgb565_bytes(self) -> bytes:
        """Export the framebuffer as raw RGB565 bytes (little-endian, 32768 bytes)."""
        rgb = self.image.tobytes()
        out = bytearray(p.LCD_DATA_SIZE)
        j = 0
        for i in range(0, len(rgb), 3):
            pixel = ((rgb[i] >> 3) << 11) | ((rgb[i + 1] >> 2) << 5) | (rgb[i + 2] >> 3)
            out[j] = pixel & 0xFF
            out[j + 1] = pixel >> 8
            j += 2
        return bytes(out)

    def _text_centered(self, text: str, cx: int, baseline: int) -> None:
        """Draw text horizontally centered on `cx` with its baseline at `baseline`."""
        try:
            self.draw.text((cx, baseline), text, font=self.font,
                           fill=TEXT_COLOR, anchor="ms")
        except ValueError:
            # Old bitmap fonts do not support anchors: position manually.
            width = self.draw.textlength(text, font=self.font)
            ascent = self.font.getmetrics()[0] if hasattr(self.font, "getmetrics") else 8
            self.draw.text((cx - width / 2, baseline - ascent), text,
                           font=self.font, fill=TEXT_COLOR)

    def render_stats(self, stats: Stats, now: Optional[datetime.datetime] = None) -> None:
        """Render current time, CPU temp and GPU temp, all centered."""
        self.clear_black()
        now = now or datetime.datetime.now()

        self._text_centered(now.strftime("%H:%M:%S"), 64, 35)

        cpu = f"CPU {stats.cpu_temp_c:.0f}C" if stats.cpu_temp_c is not None else "CPU --"
        self._text_centered(cpu, 64, 65)

        gpu = f"GPU {stats.gpu_temp_c:.0f}C" if stats.gpu_temp_c is not None else "GPU --"
        self._text_centered(gpu, 64, 95)
