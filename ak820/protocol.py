"""HID protocol definitions for the Ajazz AK820 Pro keyboard.

Port of src/protocol.rs. Based on reverse-engineering from
TaxMachine/ajazz-keyboard-software-linux.
"""

from __future__ import annotations

import os
import sys
from enum import IntEnum
from typing import List, Optional, Tuple

VENDOR_ID = 0x0C45
PRODUCT_ID = 0x8009

PACKET_LENGTH = 64
REPORT_ID = 0x04

# Image upload constants
IMAGE_CHUNK_SIZE = 4123
IMAGE_NUM_CHUNKS = 9
LCD_WIDTH = 128
LCD_HEIGHT = 128
LCD_PIXELS = LCD_WIDTH * LCD_HEIGHT
LCD_DATA_SIZE = LCD_PIXELS * 2  # RGB565 = 2 bytes per pixel

# Command codes (byte 1 of control packets)
CMD_START = 0x18
CMD_FINISH = 0xF0
CMD_MODE = 0x13
CMD_SLEEP = 0x17
CMD_IMAGE = 0x72
CMD_TIME = 0x28
CMD_SAVE = 0x02

# Delimiter magic bytes
DELIMITER_HI = 0xAA
DELIMITER_LO = 0x55

MAX_BRIGHTNESS = 5
MAX_SPEED = 5


def control_packet(command: int, byte2: int, byte8: int) -> bytes:
    """Build a 64-byte control packet: [report_id, command, b2, 0..0, b8]."""
    pkt = bytearray(PACKET_LENGTH)
    pkt[0] = REPORT_ID
    pkt[1] = command
    pkt[2] = byte2
    pkt[8] = byte8
    return bytes(pkt)


def start_packet() -> bytes:
    return control_packet(CMD_START, 0x00, 0x01)


def finish_packet() -> bytes:
    return control_packet(CMD_FINISH, 0x00, 0x01)


def mode_preamble_packet() -> bytes:
    return control_packet(CMD_MODE, 0x00, 0x01)


def sleep_preamble_packet() -> bytes:
    return control_packet(CMD_SLEEP, 0x01, 0x01)


def image_preamble_packet() -> bytes:
    return control_packet(CMD_IMAGE, 0x02, 0x09)


def time_preamble_packet() -> bytes:
    return control_packet(CMD_TIME, 0x00, 0x01)


def save_packet() -> bytes:
    return control_packet(CMD_SAVE, 0x00, 0x00)


class Direction(IntEnum):
    Left = 0
    Down = 1
    Up = 2
    Right = 3

    @classmethod
    def from_name(cls, name: str) -> Optional["Direction"]:
        return {
            "left": cls.Left, "l": cls.Left,
            "down": cls.Down, "d": cls.Down,
            "up": cls.Up, "u": cls.Up,
            "right": cls.Right, "r": cls.Right,
        }.get(name.lower())


class LightingMode(IntEnum):
    Off = 0x00
    Static = 0x01
    SingleOn = 0x02
    SingleOff = 0x03
    Glittering = 0x04
    Falling = 0x05
    Colourful = 0x06
    Breath = 0x07
    Spectrum = 0x08
    Outward = 0x09
    Scrolling = 0x0A
    Rolling = 0x0B
    Rotating = 0x0C
    Explode = 0x0D
    Launch = 0x0E
    Ripples = 0x0F
    Flowing = 0x10
    Pulsating = 0x11
    Tilt = 0x12
    Shuttle = 0x13

    @property
    def label(self) -> str:
        """CLI name of the mode (kebab-case, e.g. 'single-on')."""
        return _MODE_NAMES[self]

    @classmethod
    def all(cls) -> List["LightingMode"]:
        return list(cls)

    @classmethod
    def from_name(cls, name: str) -> Optional["LightingMode"]:
        lowered = name.lower()
        for mode in cls:
            if mode.label == lowered:
                return mode
        return None

    @classmethod
    def from_index(cls, idx: int) -> Optional["LightingMode"]:
        if 0 <= idx <= 0x13:
            return cls(idx)
        return None

    def supported_directions(self) -> List[Direction]:
        """Which directions this mode supports, if any."""
        if self is LightingMode.Scrolling:
            return [Direction.Up, Direction.Down]
        if self in (LightingMode.Rolling, LightingMode.Flowing, LightingMode.Tilt):
            return [Direction.Left, Direction.Right]
        return []


_MODE_NAMES = {
    LightingMode.Off: "off",
    LightingMode.Static: "static",
    LightingMode.SingleOn: "single-on",
    LightingMode.SingleOff: "single-off",
    LightingMode.Glittering: "glittering",
    LightingMode.Falling: "falling",
    LightingMode.Colourful: "colourful",
    LightingMode.Breath: "breath",
    LightingMode.Spectrum: "spectrum",
    LightingMode.Outward: "outward",
    LightingMode.Scrolling: "scrolling",
    LightingMode.Rolling: "rolling",
    LightingMode.Rotating: "rotating",
    LightingMode.Explode: "explode",
    LightingMode.Launch: "launch",
    LightingMode.Ripples: "ripples",
    LightingMode.Flowing: "flowing",
    LightingMode.Pulsating: "pulsating",
    LightingMode.Tilt: "tilt",
    LightingMode.Shuttle: "shuttle",
}


class SleepTime(IntEnum):
    Never = 0
    OneMinute = 1
    FiveMinutes = 2
    ThirtyMinutes = 3

    @classmethod
    def from_name(cls, name: str) -> Optional["SleepTime"]:
        return {
            "never": cls.Never, "off": cls.Never, "0": cls.Never,
            "1": cls.OneMinute, "1m": cls.OneMinute, "1min": cls.OneMinute,
            "5": cls.FiveMinutes, "5m": cls.FiveMinutes, "5min": cls.FiveMinutes,
            "30": cls.ThirtyMinutes, "30m": cls.ThirtyMinutes, "30min": cls.ThirtyMinutes,
        }.get(name.lower())


def mode_data_packet(
    mode: int,
    r: int, g: int, b: int,
    rainbow: bool,
    brightness: int,
    speed: int,
    direction: int,
) -> bytes:
    """Build the 64-byte mode data packet.

    Note: byte 0 is the mode value itself, which is sent as the report ID.
    """
    pkt = bytearray(PACKET_LENGTH)
    pkt[0] = int(mode)              # report ID = mode value
    pkt[1] = r
    pkt[2] = g
    pkt[3] = b
    # bytes 4-7: padding (zero)
    pkt[8] = 1 if rainbow else 0
    pkt[9] = min(brightness, MAX_BRIGHTNESS)
    pkt[10] = min(speed, MAX_SPEED)
    pkt[11] = int(direction)
    # bytes 12-13: padding
    pkt[14] = DELIMITER_LO          # 0x55 (little-endian 0xAA55)
    pkt[15] = DELIMITER_HI          # 0xAA
    return bytes(pkt)


def rgb565_encode(r: int, g: int, b: int) -> bytes:
    """Encode an RGB888 pixel to RGB565 (little-endian bytes)."""
    r5 = r >> 3
    g6 = g >> 2
    b5 = b >> 3
    pixel = (r5 << 11) | (g6 << 5) | b5
    return pixel.to_bytes(2, "little")


def split_image_data(data: bytes) -> List[bytes]:
    """Split image data into IMAGE_NUM_CHUNKS chunks of IMAGE_CHUNK_SIZE bytes,
    padded with 0xFF (matching the C++ reference)."""
    chunks: List[bytes] = []
    for i in range(IMAGE_NUM_CHUNKS):
        start = i * IMAGE_CHUNK_SIZE
        chunk = bytearray(b"\xff" * IMAGE_CHUNK_SIZE)
        if start < len(data):
            end = min(start + IMAGE_CHUNK_SIZE, len(data))
            chunk[: end - start] = data[start:end]
        chunks.append(bytes(chunk))
    return chunks


def time_data_packet(
    year: int, month: int, day: int,
    hour: int, minute: int, second: int,
) -> bytes:
    """Build the 64-byte time data packet.

    Report ID is 0x00 (not 0x04), with magic byte 0x5A.
    """
    pkt = bytearray(PACKET_LENGTH)
    pkt[0] = 0x00                       # report ID
    pkt[1] = 0x01                       # fixed
    pkt[2] = 0x5A                       # magic marker
    pkt[3] = max(year - 2000, 0)
    pkt[4] = month
    pkt[5] = day
    pkt[6] = hour
    pkt[7] = minute
    pkt[8] = second
    pkt[9] = 0x00
    pkt[10] = 0x04                      # fixed
    pkt[PACKET_LENGTH - 2] = DELIMITER_HI   # 0xAA at byte 62
    pkt[PACKET_LENGTH - 1] = DELIMITER_LO   # 0x55 at byte 63
    return bytes(pkt)


def sleep_data_packet(sleep_time: int) -> bytes:
    """Build the 64-byte sleep data packet."""
    pkt = bytearray(PACKET_LENGTH)
    pkt[8] = int(sleep_time)
    pkt[PACKET_LENGTH - 2] = DELIMITER_HI   # 0xAA at byte 62
    pkt[PACKET_LENGTH - 1] = DELIMITER_LO   # 0x55 at byte 63
    return bytes(pkt)


def resolve_lighting(
    mode: LightingMode, brightness: int, speed: int
) -> Tuple[LightingMode, int, int]:
    """Apply the device quirks used by every backend.

    'off' is emulated as single-on with brightness 0, and 'static' is
    emulated as breath with speed 0.
    Returns (actual_mode, actual_brightness, actual_speed).
    """
    if mode is LightingMode.Off:
        return LightingMode.SingleOn, 0, 0
    if mode is LightingMode.Static:
        return LightingMode.Breath, brightness, 0
    return mode, brightness, speed


def interface_from_env(default: int = 3) -> int:
    """Read the AK820_IFACE override, falling back to `default`."""
    try:
        return int(os.environ["AK820_IFACE"])
    except (KeyError, ValueError):
        return default


def debug_enabled() -> bool:
    return "AK820_DEBUG" in os.environ


def debug_dump(data: bytes) -> None:
    """Hex-dump a TX packet to stderr when AK820_DEBUG is set."""
    if not debug_enabled():
        return
    out = [f"  TX [{len(data)}]: "]
    for i, b in enumerate(data):
        if i > 0 and i % 16 == 0:
            out.append("\n          ")
        out.append(f"{b:02x} ")
    print("".join(out), file=sys.stderr)
