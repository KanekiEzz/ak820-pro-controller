"""Check the exact sequence of USB transfers using a fake pyusb (no hardware needed)."""

import io
import os
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ak820 import cli  # noqa: E402
from ak820 import protocol as p  # noqa: E402
from ak820 import usb_device  # noqa: E402


class FakeUSBError(Exception):
    pass


class FakeDev:
    def __init__(self):
        self.ctrl = []     # (bmRequestType, bRequest, wValue, wIndex, payload_or_len)
        self.writes = []   # (endpoint, bytes)
        self.claimed = []
        self.released = []
        self.attached = []

    def is_kernel_driver_active(self, iface):
        return False

    def detach_kernel_driver(self, iface):
        pass

    def attach_kernel_driver(self, iface):
        self.attached.append(iface)

    def ctrl_transfer(self, bm, req, value, index, data, timeout):
        self.ctrl.append((bm, req, value, index, data))
        if bm == 0xA1:
            raise FakeUSBError("stall")  # handshake STALL must be tolerated
        return len(data)

    def write(self, endpoint, data, timeout):
        self.writes.append((endpoint, bytes(data)))
        return len(data)


def make_fake_usb(dev):
    return types.SimpleNamespace(
        core=types.SimpleNamespace(
            USBError=FakeUSBError,
            NoBackendError=type("NoBackendError", (Exception,), {}),
            find=lambda **kw: dev,
        ),
        util=types.SimpleNamespace(
            claim_interface=lambda d, i: dev.claimed.append(i),
            release_interface=lambda d, i: dev.released.append(i),
            dispose_resources=lambda d: None,
        ),
    )


class UsbSequenceTest(unittest.TestCase):
    def setUp(self):
        self.dev = FakeDev()
        patches = [
            mock.patch.object(usb_device, "usb", make_fake_usb(self.dev)),
            mock.patch.object(usb_device.time, "sleep", lambda s: None),
            mock.patch.dict(os.environ, {}, clear=False),
        ]
        for pt in patches:
            pt.start()
            self.addCleanup(pt.stop)
        os.environ.pop("AK820_IFACE", None)
        self.err = redirect_stderr(io.StringIO())
        self.err.__enter__()
        self.addCleanup(self.err.__exit__, None, None, None)

    def sets(self):
        return [c for c in self.dev.ctrl if c[0] == 0x21]

    def gets(self):
        return [c for c in self.dev.ctrl if c[0] == 0xA1]

    def test_claims_control_interface(self):
        with usb_device.UsbDevice():
            pass
        self.assertEqual(self.dev.claimed, [3])
        self.assertEqual(self.dev.released, [3])
        self.assertEqual(self.dev.attached, [3])

    def test_iface_env_override(self):
        os.environ["AK820_IFACE"] = "1"
        with usb_device.UsbDevice():
            pass
        self.assertEqual(self.dev.claimed, [1])

    def test_lighting_sequence(self):
        with usb_device.UsbDevice() as d:
            d.set_lighting(p.LightingMode.Static, 1, 2, 3, False, 5, 3, p.Direction.Left)
        payloads = [bytes(c[4]) for c in self.sets()]
        self.assertEqual(payloads, [
            p.start_packet(),
            p.mode_preamble_packet(),
            p.mode_data_packet(p.LightingMode.Breath, 1, 2, 3, False, 5, 0, p.Direction.Left),
            p.finish_packet(),
        ])
        # wValue = Feature(0x0300) | reportID; wIndex = interface 3
        self.assertEqual([c[2] for c in self.sets()], [0x0304, 0x0304, 0x0307, 0x0304])
        self.assertTrue(all(c[3] == 3 and c[1] == 0x09 for c in self.sets()))
        # GET_REPORT handshake only after report-ID 0x04 packets (3 of them)
        self.assertEqual(len(self.gets()), 3)
        self.assertTrue(all(c[1] == 0x01 and c[4] == 64 for c in self.gets()))

    def test_off_sends_single_on_dark(self):
        with usb_device.UsbDevice() as d:
            d.set_lighting(p.LightingMode.Off, 9, 9, 9, True, 5, 4, p.Direction.Up)
        data = bytes(self.sets()[2][4])
        self.assertEqual(data[0], int(p.LightingMode.SingleOn))
        self.assertEqual((data[9], data[10]), (0, 0))

    def test_sleep_sequence_has_no_finish(self):
        with usb_device.UsbDevice() as d:
            d.set_sleep_time(p.SleepTime.FiveMinutes)
        payloads = [bytes(c[4]) for c in self.sets()]
        self.assertEqual(payloads, [
            p.start_packet(),
            p.sleep_preamble_packet(),
            p.sleep_data_packet(p.SleepTime.FiveMinutes),
        ])
        self.assertEqual(self.sets()[2][2], 0x0300)  # data packet uses report ID 0

    def test_time_sequence(self):
        with usb_device.UsbDevice() as d:
            d.set_time(2026, 10, 27, 10, 34, 56)
        payloads = [bytes(c[4]) for c in self.sets()]
        self.assertEqual(payloads, [
            p.start_packet(),
            p.time_preamble_packet(),
            p.time_data_packet(2026, 10, 27, 10, 34, 56),
            p.save_packet(),
        ])

    def test_image_upload(self):
        data = bytes(range(256)) * (p.LCD_DATA_SIZE // 256)
        with usb_device.UsbDevice() as d:
            d.upload_image(data)
        # control: START, IMAGE_PREAMBLE ... FINISH
        sets = [bytes(c[4]) for c in self.sets()]
        self.assertEqual(sets, [p.start_packet(), p.image_preamble_packet(), p.finish_packet()])
        # 9 chunks x (64 full packets + one 27-byte packet) on EP 0x03
        self.assertEqual(len(self.dev.writes), 9 * 65)
        self.assertTrue(all(ep == 0x03 for ep, _ in self.dev.writes))
        sizes = [len(b) for _, b in self.dev.writes]
        self.assertEqual(sizes, ([64] * 64 + [27]) * 9)
        # the image data is sent in order, then 0xFF padding
        blob = b"".join(b for _, b in self.dev.writes)
        self.assertEqual(len(blob), 9 * p.IMAGE_CHUNK_SIZE)
        self.assertEqual(blob[: p.LCD_DATA_SIZE - 0][:p.IMAGE_CHUNK_SIZE],
                         data[: p.IMAGE_CHUNK_SIZE])
        # interface 2 was claimed for the upload then released again
        self.assertIn(2, self.dev.claimed)
        self.assertIn(2, self.dev.released)

    def test_image_wrong_size(self):
        with usb_device.UsbDevice() as d:
            with self.assertRaises(ValueError):
                d.upload_image(b"\x00" * 10)

    def test_ctrl_failure_becomes_device_error(self):
        def boom(*a, **k):
            raise FakeUSBError("pipe")
        self.dev.ctrl_transfer = boom
        with usb_device.UsbDevice() as d:
            with self.assertRaises(usb_device.DeviceError):
                d.set_sleep_time(p.SleepTime.Never)

    def test_device_not_found(self):
        fake = make_fake_usb(self.dev)
        fake.core.find = lambda **kw: None
        with mock.patch.object(usb_device, "usb", fake):
            with self.assertRaises(usb_device.DeviceError) as cm:
                usb_device.UsbDevice()
        self.assertIn("0c45", str(cm.exception))
        self.assertIn("8009", str(cm.exception))


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_list_modes(self):
        code, out, _ = self.run_cli("list-modes")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "Available lighting modes:")
        self.assertIn("   0 - off", lines)
        self.assertIn("  10 - scrolling (directions: Up, Down)", lines)
        self.assertIn("  11 - rolling (directions: Left, Right)", lines)
        self.assertIn("  19 - shuttle", lines)
        self.assertEqual(lines[-1], "Brightness: 0-5, Speed: 0-5")

    def test_hex_color(self):
        self.assertEqual(cli.parse_hex_color("ff0080"), (255, 0, 128))
        self.assertEqual(cli.parse_hex_color("#00ff00"), (0, 255, 0))
        with self.assertRaises(ValueError):
            cli.parse_hex_color("fff")
        with self.assertRaises(ValueError):
            cli.parse_hex_color("gggggg")

    def test_validation_errors_do_not_touch_usb(self):
        with mock.patch.object(cli, "UsbDevice", side_effect=AssertionError("USB used")):
            for argv, msg in [
                (["light", "bogus"], "Unknown mode"),
                (["light", "static", "-c", "zzz"], "6 hex digits"),
                (["light", "static", "-b", "9"], "Brightness must be 0-5"),
                (["light", "static", "-s", "6"], "Speed must be 0-5"),
                (["light", "scrolling", "-d", "sideways"], "Unknown direction"),
                (["sleep", "2h"], "Unknown sleep time"),
            ]:
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, 1, argv)
                self.assertIn(msg, err, argv)

    def test_light_by_name_and_index(self):
        for mode_arg, expected in [("breath", p.LightingMode.Breath),
                                   ("7", p.LightingMode.Breath),
                                   ("SINGLE-ON", p.LightingMode.SingleOn)]:
            dev = mock.MagicMock()
            dev.__enter__.return_value = dev
            with mock.patch.object(cli, "UsbDevice", return_value=dev):
                code, out, _ = self.run_cli("light", mode_arg, "-c", "00ff00", "-r",
                                            "-b", "4", "-s", "2", "-d", "r")
            self.assertEqual(code, 0)
            dev.set_lighting.assert_called_once_with(
                expected, 0, 255, 0, True, 4, 2, p.Direction.Right)
            self.assertIn("color: #00ff00", out)
            self.assertIn("rainbow: true", out)
            self.assertIn("direction: Right", out)

    def test_sleep_command(self):
        dev = mock.MagicMock()
        dev.__enter__.return_value = dev
        with mock.patch.object(cli, "UsbDevice", return_value=dev):
            code, out, _ = self.run_cli("sleep", "5m")
        self.assertEqual(code, 0)
        dev.set_sleep_time.assert_called_once_with(p.SleepTime.FiveMinutes)
        self.assertIn("Sleep timer set to: FiveMinutes", out)

    def test_lcd_test_solid_and_diag(self):
        dev = mock.MagicMock()
        dev.__enter__.return_value = dev
        with mock.patch.object(cli, "UsbDevice", return_value=dev):
            self.run_cli("lcd-test", "red")
            red = dev.upload_image.call_args[0][0]
            self.run_cli("lcd-test", "diag")
            diag = dev.upload_image.call_args[0][0]
        self.assertEqual(len(red), p.LCD_DATA_SIZE)
        self.assertEqual(red, p.rgb565_encode(255, 0, 0) * p.LCD_PIXELS)
        self.assertEqual(len(diag), p.LCD_DATA_SIZE)

        def px(row, col):
            off = (row * p.LCD_WIDTH + col) * 2
            return diag[off:off + 2]
        self.assertEqual(px(0, 0), p.rgb565_encode(255, 0, 0))      # TL red
        self.assertEqual(px(0, 100), p.rgb565_encode(0, 255, 0))    # TR green
        self.assertEqual(px(100, 0), p.rgb565_encode(0, 0, 255))    # BL blue
        self.assertEqual(px(100, 100), p.rgb565_encode(255, 255, 255))  # BR white


if __name__ == "__main__":
    unittest.main()
