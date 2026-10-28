"""HID device communication for the AK820 Pro via the `hidapi` backend.

Port of src/device.rs. This is an alternative backend (the CLI/GUI use
`ak820.usb.UsbDevice`). Requires: pip install hidapi

Interface 3 is the vendor control interface for lighting/config.
"""

from __future__ import annotations

import sys

from . import protocol as p

CONTROL_INTERFACE = 3


class HidApiError(Exception):
    pass


class AK820Device:
    def __init__(self) -> None:
        try:
            import hid  # type: ignore[import-not-found]
        except ImportError as e:
            raise HidApiError("The 'hidapi' package is not installed (pip install hidapi).") from e

        iface = p.interface_from_env(CONTROL_INTERFACE)
        devices = hid.enumerate(p.VENDOR_ID, p.PRODUCT_ID)

        if not devices:
            raise HidApiError(
                f"AK820 Pro not found (VID {p.VENDOR_ID:04x}, PID {p.PRODUCT_ID:04x}). "
                "Is it connected via USB cable?"
            )

        print(f"Found {len(devices)} HID interface(s) for AK820", file=sys.stderr)

        info = next((d for d in devices if d.get("interface_number") == iface), None)
        if info is None:
            available = [d.get("interface_number") for d in devices]
            raise HidApiError(f"Interface {iface} not found. Available: {available}")

        print(f"Opening interface {iface}", file=sys.stderr)
        self.device = hid.device()
        try:
            self.device.open_path(info["path"])
        except (OSError, ValueError) as e:
            raise HidApiError(f"Failed to open interface {iface}: {e}") from e

        self.device.set_nonblocking(0)
        print(f"Connected to AK820 Pro (interface {iface})", file=sys.stderr)

    def close(self) -> None:
        try:
            self.device.close()
        except Exception:
            pass

    def __enter__(self) -> "AK820Device":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _send_feature(self, data: bytes) -> None:
        """Send a feature report followed by a GET_REPORT handshake.

        The C++ reference does get_feature_report after every send; the
        handshake appears required for the device to process commands.
        """
        p.debug_dump(data)
        try:
            self.device.send_feature_report(list(data))
        except (OSError, ValueError) as e:
            raise HidApiError(f"Failed to send feature report: {e}") from e

        # Errors are non-fatal: some report IDs don't support GET.
        try:
            self.device.get_feature_report(data[0], 1)
        except (OSError, ValueError):
            pass

    def _transaction(self, preamble: bytes, data: bytes) -> None:
        self._send_feature(p.start_packet())
        self._send_feature(preamble)
        self._send_feature(data)
        self._send_feature(p.finish_packet())

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
        except HidApiError as e:
            raise HidApiError(f"Failed to set lighting mode: {e}") from e

    def set_sleep_time(self, sleep_time: p.SleepTime) -> None:
        self._send_feature(p.start_packet())
        self._send_feature(p.sleep_preamble_packet())
        self._send_feature(p.sleep_data_packet(sleep_time))
