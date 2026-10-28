"""Direct hidraw interface for the AK820 Pro.

Port of src/hidraw.rs. Uses Linux ioctl for feature reports. The kernel's HID
driver handles USB error recovery (STALL clearing) transparently, unlike raw
libusb.
"""

from __future__ import annotations

import fcntl
import os
import sys
from typing import Optional

from . import protocol as p

_IOC_WRITE_READ = 3


def _hid_ioctl(nr: int, length: int) -> int:
    # _IOC(_IOC_WRITE|_IOC_READ, 'H', nr, len)
    return (_IOC_WRITE_READ << 30) | (length << 16) | (ord("H") << 8) | nr


def hidiocsfeature(length: int) -> int:
    return _hid_ioctl(0x06, length)


def hidiocgfeature(length: int) -> int:
    return _hid_ioctl(0x07, length)


class HidrawError(Exception):
    pass


class HidrawDevice:
    def __init__(self) -> None:
        iface = p.interface_from_env(3)
        self.fd: Optional[int] = None
        self.path = ""

        try:
            entries = sorted(os.listdir("/sys/class/hidraw/"))
        except OSError as e:
            raise HidrawError(f"Cannot list /sys/class/hidraw/: {e}") from e

        wanted_id = f"HID_ID=0003:{p.VENDOR_ID:08X}:{p.PRODUCT_ID:08X}"

        for name in entries:
            uevent_path = f"/sys/class/hidraw/{name}/device/uevent"
            try:
                with open(uevent_path, "r") as f:
                    uevent = f.read()
            except OSError:
                continue

            if wanted_id not in uevent:
                continue

            phys_iface: Optional[int] = None
            for line in uevent.splitlines():
                if line.startswith("HID_PHYS="):
                    try:
                        phys_iface = int(line.rsplit("/input", 1)[-1])
                    except ValueError:
                        phys_iface = None
                    break

            if phys_iface != iface:
                continue

            dev_path = f"/dev/{name}"
            print(f"Opening {dev_path} (interface {iface})", file=sys.stderr)
            try:
                self.fd = os.open(dev_path, os.O_RDWR)
            except OSError as e:
                raise HidrawError(
                    f"Failed to open {dev_path}. Check udev rules / permissions. ({e})"
                ) from e
            self.path = dev_path
            return

        raise HidrawError(
            f"AK820 Pro interface {iface} not found. Is the keyboard connected via USB?"
        )

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def __enter__(self) -> "HidrawDevice":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _set_feature(self, data: bytes) -> None:
        """Send a SET_REPORT (Feature) via ioctl."""
        p.debug_dump(data)
        try:
            fcntl.ioctl(self.fd, hidiocsfeature(p.PACKET_LENGTH), bytes(data))
        except OSError as e:
            raise HidrawError(f"HIDIOCSFEATURE failed on {self.path}: {e}") from e

    def _get_feature_handshake(self, report_id: int) -> None:
        """GET_REPORT handshake via ioctl with length=0, matching the C++ reference.

        buf[0] holds the report ID; the length in the ioctl is 0. The result is
        intentionally ignored: this is only a sync handshake.
        """
        buf = bytearray([report_id])
        try:
            fcntl.ioctl(self.fd, hidiocgfeature(0), buf, True)
        except OSError:
            pass

    def _send(self, data: bytes) -> None:
        self._set_feature(data)
        self._get_feature_handshake(data[0])

    def _transaction(self, preamble: bytes, data: bytes) -> None:
        self._send(p.start_packet())
        self._send(preamble)
        self._send(data)
        self._send(p.finish_packet())

    def set_lighting(
        self,
        mode: p.LightingMode,
        r: int, g: int, b: int,
        rainbow: bool,
        brightness: int,
        speed: int,
        direction: p.Direction,
    ) -> None:
        actual_mode, actual_brightness, actual_speed = p.resolve_lighting(
            mode, brightness, speed
        )
        data = p.mode_data_packet(
            actual_mode, r, g, b, rainbow, actual_brightness, actual_speed, direction
        )
        try:
            self._transaction(p.mode_preamble_packet(), data)
        except HidrawError as e:
            raise HidrawError(f"Failed to set lighting mode: {e}") from e

    def set_sleep_time(self, sleep_time: p.SleepTime) -> None:
        self._send(p.start_packet())
        self._send(p.sleep_preamble_packet())
        self._send(p.sleep_data_packet(sleep_time))
