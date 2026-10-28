"""Direct USB control transfer implementation for the AK820 Pro.

Port of src/usb.rs. Uses pyusb (libusb) to detach the kernel driver and send
SET_REPORT directly. The kernel's hid-generic driver interferes with feature
reports, so we bypass it via libusb.
"""

from __future__ import annotations

import sys
import time
from typing import Optional

from . import protocol as p

try:  # pyusb is imported lazily-friendly so `list-modes` works without it
    import usb.core
    import usb.util
except ImportError:  # pragma: no cover - exercised only when pyusb is missing
    usb = None  # type: ignore[assignment]

CONTROL_INTERFACE = 3
DATA_INTERFACE = 2
DATA_EP_OUT = 0x03  # EP3 OUT on interface 2
TIMEOUT_MS = 1000

# USB HID class request codes
HID_SET_REPORT = 0x09
HID_GET_REPORT = 0x01

# Report type: Feature = 3
HID_FEATURE_REPORT = 0x0300

# Short timeout for GET_REPORT handshake: device may STALL, that's OK
HANDSHAKE_TIMEOUT_MS = 100

# bmRequestType: Class request addressed to an interface
REQ_TYPE_OUT = 0x21  # host-to-device | class | interface
REQ_TYPE_IN = 0xA1   # device-to-host | class | interface


class DeviceError(Exception):
    """Raised for any failure talking to the keyboard."""


class UsbDevice:
    def __init__(self) -> None:
        if usb is None:
            raise DeviceError(
                "pyusb is not installed. Run: pip install pyusb "
                "(and make sure libusb-1.0 is installed)."
            )

        self.iface = p.interface_from_env(CONTROL_INTERFACE)
        self.data_iface_claimed = False
        self._closed = False

        try:
            dev = usb.core.find(idVendor=p.VENDOR_ID, idProduct=p.PRODUCT_ID)
        except usb.core.NoBackendError as e:
            raise DeviceError(
                "No libusb backend found. Install libusb "
                "(e.g. 'sudo apt install libusb-1.0-0')."
            ) from e
        if dev is None:
            raise DeviceError(
                f"AK820 Pro not found (VID {p.VENDOR_ID:04x}, PID {p.PRODUCT_ID:04x}). "
                "Is it connected via USB?"
            )
        self.dev = dev

        self._detach_kernel_driver(self.iface)

        try:
            usb.util.claim_interface(self.dev, self.iface)
        except usb.core.USBError as e:
            raise DeviceError(f"Failed to claim interface {self.iface}: {e}") from e

        print(f"Connected to AK820 Pro (interface {self.iface})", file=sys.stderr)

    # ------------------------------------------------------------------ #
    # Context manager / cleanup (replaces Rust's Drop)
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "UsbDevice":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.data_iface_claimed:
            self._release(DATA_INTERFACE)
            self.data_iface_claimed = False
        self._release(self.iface)
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass

    def _release(self, iface: int) -> None:
        try:
            usb.util.release_interface(self.dev, iface)
        except Exception:
            pass
        try:
            self.dev.attach_kernel_driver(iface)
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #

    def _detach_kernel_driver(self, iface: int) -> None:
        """Detach the kernel driver if one is attached (hid-generic blocks feature
        reports on Linux). On macOS/Windows libusb cannot detach drivers and pyusb
        raises NotImplementedError: that is fine, we just try to claim the interface."""
        try:
            if self.dev.is_kernel_driver_active(iface):
                self.dev.detach_kernel_driver(iface)
                print(f"Detached kernel driver from interface {iface}", file=sys.stderr)
        except NotImplementedError:
            pass
        except usb.core.USBError as e:
            raise DeviceError(f"Failed to detach kernel driver: {e}") from e

    def claim_data_interface(self) -> None:
        """Claim interface 2 for sustained image transfers (LCD loop).

        Call once before repeated upload_image calls.
        """
        if self.data_iface_claimed:
            return
        self._detach_kernel_driver(DATA_INTERFACE)
        try:
            usb.util.claim_interface(self.dev, DATA_INTERFACE)
        except usb.core.USBError as e:
            raise DeviceError(f"Failed to claim data interface {DATA_INTERFACE}: {e}") from e
        self.data_iface_claimed = True

    def send_feature(self, data: bytes) -> None:
        """Send a HID SET_REPORT(Feature) via USB control transfer.

        The GET_REPORT handshake is only done for control report ID 0x04.
        """
        if len(data) != p.PACKET_LENGTH:
            raise ValueError(f"packet must be {p.PACKET_LENGTH} bytes, got {len(data)}")
        report_id = data[0]
        p.debug_dump(data)

        w_value = HID_FEATURE_REPORT | report_id
        try:
            self.dev.ctrl_transfer(
                REQ_TYPE_OUT, HID_SET_REPORT, w_value, self.iface,
                bytes(data), TIMEOUT_MS,
            )
        except usb.core.USBError as e:
            raise DeviceError(f"SET_REPORT failed: {e}") from e

        # GET_REPORT handshake: the firmware needs this to advance its state
        # machine, but only for control report ID 0x04. Mode data packets use
        # the mode value as report ID and the device doesn't support GET_REPORT
        # for those. Errors (STALL, timeout) are expected and ignored.
        if report_id == p.REPORT_ID:
            try:
                self.dev.ctrl_transfer(
                    REQ_TYPE_IN, HID_GET_REPORT, w_value, self.iface,
                    p.PACKET_LENGTH, HANDSHAKE_TIMEOUT_MS,
                )
            except usb.core.USBError:
                pass

        # Small delay for device to process
        time.sleep(0.010)

    def _transaction(self, preamble: bytes, data: bytes) -> None:
        self.send_feature(p.start_packet())
        self.send_feature(preamble)
        self.send_feature(data)
        self.send_feature(p.finish_packet())
        # Extra delay after full transaction for device processing
        time.sleep(0.100)

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
        except DeviceError as e:
            raise DeviceError(f"Failed to set lighting mode: {e}") from e

    def upload_image(self, rgb565_data: bytes) -> None:
        """Upload a 128x128 RGB565 image to the LCD screen.

        `rgb565_data` must be exactly LCD_DATA_SIZE bytes (32768).
        For repeated uploads (LCD loop), call `claim_data_interface()` first.
        """
        if len(rgb565_data) != p.LCD_DATA_SIZE:
            raise ValueError(f"Image must be {p.LCD_DATA_SIZE} bytes")

        # Claim interface 2 if not already held
        need_release = not self.data_iface_claimed
        if need_release:
            self.claim_data_interface()

        # Transaction: START -> IMAGE_PREAMBLE -> 9 chunks via interrupt OUT -> FINISH
        self.send_feature(p.start_packet())
        self.send_feature(p.image_preamble_packet())

        debug = p.debug_enabled()

        # Split into 9 chunks of 4123 bytes (padded with 0xFF). Each chunk is
        # sent as 64-byte interrupt packets; the last packet of each chunk is
        # 27 bytes (short packet = chunk boundary delimiter).
        chunks = p.split_image_data(rgb565_data)

        for ci, chunk in enumerate(chunks):
            for off in range(0, len(chunk), p.PACKET_LENGTH):
                pkt = chunk[off:off + p.PACKET_LENGTH]
                try:
                    self.dev.write(DATA_EP_OUT, pkt, TIMEOUT_MS)
                except usb.core.USBError as e:
                    raise DeviceError(
                        f"Interrupt write failed at chunk {ci + 1}/9 ({len(pkt)} bytes): {e}"
                    ) from e
            if debug:
                print(f"  Chunk {ci + 1}/9 sent ({len(chunk)} bytes)", file=sys.stderr)
            # Inter-chunk delay: device needs time to process each chunk
            time.sleep(0.050)

        self.send_feature(p.finish_packet())

        # Only release if we claimed it ourselves (one-off upload)
        if need_release:
            self._release(DATA_INTERFACE)
            self.data_iface_claimed = False

        time.sleep(0.100)

    def set_time(
        self,
        year: int, month: int, day: int,
        hour: int, minute: int, second: int,
    ) -> None:
        """Sync the keyboard's internal clock.

        Protocol: START -> TIME_CONFIGURE -> TIME_DATA -> SAVE
        """
        self.send_feature(p.start_packet())
        self.send_feature(p.time_preamble_packet())
        self.send_feature(p.time_data_packet(year, month, day, hour, minute, second))
        self.send_feature(p.save_packet())
        time.sleep(0.100)

    def set_sleep_time(self, sleep_time: p.SleepTime) -> None:
        self.send_feature(p.start_packet())
        self.send_feature(p.sleep_preamble_packet())
        self.send_feature(p.sleep_data_packet(sleep_time))
        time.sleep(0.100)
