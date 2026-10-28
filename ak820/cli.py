"""Command line interface: port of src/main.rs (clap) to argparse."""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from typing import List, Optional, Tuple

from . import protocol as p
from .usb_device import DeviceError, UsbDevice


def parse_hex_color(s: str) -> Tuple[int, int, int]:
    s = s.lstrip("#")
    if len(s) != 6:
        raise ValueError("Color must be 6 hex digits (e.g., ff0000)")
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError as e:
        raise ValueError(f"Invalid hex color '{s}': {e}") from e


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ak820-ctl",
        description="Control Ajazz AK820 Pro keyboard on Linux",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("list-modes", help="List available lighting modes")

    light = sub.add_parser("light", help="Set the lighting mode")
    light.add_argument("mode", help="Mode name (use 'list-modes' to see options)")
    light.add_argument("-c", "--color", default="ff0000",
                       help="Color as hex RGB (e.g., ff0000 for red). Ignored if rainbow is set. [default: ff0000]")
    light.add_argument("-r", "--rainbow", action="store_true",
                       help="Use rainbow colors instead of a fixed color")
    light.add_argument("-b", "--brightness", type=int, default=5,
                       help="Brightness (0-5) [default: 5]")
    light.add_argument("-s", "--speed", type=int, default=3,
                       help="Speed (0-5) [default: 3]")
    light.add_argument("-d", "--direction", default=None,
                       help="Direction: left, right, up, down (only for modes that support it)")

    sleep = sub.add_parser("sleep", help="Set the sleep timer")
    sleep.add_argument("time", help="Sleep time: never, 1m, 5m, 30m")

    stats = sub.add_parser(
        "stats", help="Show current system stats (CPU, RAM, time): preview for LCD display")
    stats.add_argument("-i", "--interval", type=int, default=1,
                       help="Refresh interval in seconds [default: 1]")

    lcd = sub.add_parser(
        "lcd",
        help="Display live system stats (CPU/GPU temp, time) on the LCD screen. "
             "Only updates when temps change by >=2C or every max-interval seconds.")
    lcd.add_argument("-i", "--interval", type=int, default=5,
                     help="Poll interval in seconds (how often to check temps) [default: 5]")
    lcd.add_argument("-m", "--max-interval", type=int, default=60,
                     help="Max seconds between forced screen refreshes even if temps unchanged [default: 60]")

    lcd_test = sub.add_parser(
        "lcd-test", help="Upload a solid test color to the LCD screen (for protocol debugging)")
    lcd_test.add_argument("color", nargs="?", default="red",
                          help="Color: red, green, blue, white, black, diag, or hex [default: red]")

    sub.add_parser("sync-time", help="Sync the keyboard's clock to the system time")
    sub.add_parser("probe", help="Probe the keyboard and show device info")
    sub.add_parser("test", help="Test: send lighting changes in one session (red -> green -> blue)")
    return parser


# ---------------------------------------------------------------------- #
# Commands
# ---------------------------------------------------------------------- #

def cmd_list_modes(_args) -> None:
    print("Available lighting modes:")
    for mode in p.LightingMode.all():
        dirs = mode.supported_directions()
        if not dirs:
            print(f"  {int(mode):2} - {mode.label}")
        else:
            names = ", ".join(d.name for d in dirs)
            print(f"  {int(mode):2} - {mode.label} (directions: {names})")
    print("\nBrightness: 0-5, Speed: 0-5")


def cmd_light(args) -> None:
    mode = p.LightingMode.from_name(args.mode)
    if mode is None:
        try:
            mode = p.LightingMode.from_index(int(args.mode))
        except ValueError:
            mode = None
    if mode is None:
        raise ValueError(f"Unknown mode '{args.mode}'. Use 'list-modes' to see options.")

    r, g, b = parse_hex_color(args.color)

    if args.direction is not None:
        direction = p.Direction.from_name(args.direction)
        if direction is None:
            raise ValueError(f"Unknown direction '{args.direction}'. Use: left, right, up, down")
    else:
        direction = p.Direction.Left

    if not 0 <= args.brightness <= p.MAX_BRIGHTNESS:
        raise ValueError(f"Brightness must be 0-{p.MAX_BRIGHTNESS}")
    if not 0 <= args.speed <= p.MAX_SPEED:
        raise ValueError(f"Speed must be 0-{p.MAX_SPEED}")

    with UsbDevice() as dev:
        dev.set_lighting(mode, r, g, b, args.rainbow, args.brightness, args.speed, direction)
    print(
        f"Set mode: {mode.label} | color: #{r:02x}{g:02x}{b:02x} | "
        f"rainbow: {str(args.rainbow).lower()} | brightness: {args.brightness} | "
        f"speed: {args.speed} | direction: {direction.name}"
    )


def cmd_sleep(args) -> None:
    sleep_time = p.SleepTime.from_name(args.time)
    if sleep_time is None:
        raise ValueError(f"Unknown sleep time '{args.time}'. Use: never, 1m, 5m, 30m")
    with UsbDevice() as dev:
        dev.set_sleep_time(sleep_time)
    print(f"Sleep timer set to: {sleep_time.name}")


def cmd_stats(args) -> None:
    from .stats import SystemStats

    sys_stats = SystemStats()
    print("System stats (Ctrl+C to stop):")
    while True:
        stats = sys_stats.refresh()
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"\r{now} | {stats}  ", end="", flush=True)
        time.sleep(args.interval)


def _temp_changed(old: Optional[float], new: Optional[float]) -> bool:
    if old is not None and new is not None:
        return abs(new - old) >= 2.0
    return old is None and new is not None


def cmd_lcd(args) -> None:
    from .lcd import LcdFramebuffer
    from .stats import SystemStats

    interval, max_interval = args.interval, args.max_interval

    with UsbDevice() as dev:
        dev.claim_data_interface()
        sys_stats = SystemStats()
        fb = LcdFramebuffer()
        consecutive_errors = 0
        last_cpu_temp: Optional[float] = None
        last_gpu_temp: Optional[float] = None
        last_upload = time.monotonic() - (max_interval + 1)  # force first upload

        print("LCD stats display (Ctrl+C to stop):")
        print(f"  Poll every {interval}s, refresh screen on >=2C change or every {max_interval}s")
        while True:
            stats = sys_stats.refresh()

            cpu_changed = _temp_changed(last_cpu_temp, stats.cpu_temp_c)
            gpu_changed = _temp_changed(last_gpu_temp, stats.gpu_temp_c)
            forced = int(time.monotonic() - last_upload) >= max_interval

            if cpu_changed or gpu_changed or forced:
                fb.render_stats(stats)
                data = fb.as_rgb565_bytes()
                try:
                    dev.upload_image(data)
                except DeviceError as e:
                    consecutive_errors += 1
                    print(f"\nLCD upload error: {e}", file=sys.stderr)
                    if consecutive_errors >= 3:
                        raise DeviceError("Too many consecutive LCD upload failures") from e
                    time.sleep(2)
                else:
                    consecutive_errors = 0
                    last_cpu_temp = stats.cpu_temp_c
                    last_gpu_temp = stats.gpu_temp_c
                    last_upload = time.monotonic()

            now = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"\r{now} | {stats}  ", end="", flush=True)
            time.sleep(interval)


def cmd_lcd_test(args) -> None:
    color = args.color.lower()
    data = bytearray()

    if color == "diag":
        red = p.rgb565_encode(255, 0, 0)
        green = p.rgb565_encode(0, 255, 0)
        blue = p.rgb565_encode(0, 0, 255)
        white = p.rgb565_encode(255, 255, 255)
        for row in range(p.LCD_HEIGHT):
            for col in range(p.LCD_WIDTH):
                top, left = row < 64, col < 64
                if top and left:
                    pixel = red
                elif top:
                    pixel = green
                elif left:
                    pixel = blue
                else:
                    pixel = white
                data += pixel
        print("Uploading diagnostic pattern (TL=red, TR=green, BL=blue, BR=white)...")
    else:
        named = {
            "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
            "white": (255, 255, 255), "black": (0, 0, 0),
        }
        r, g, b = named[color] if color in named else parse_hex_color(color)
        data = bytearray(p.rgb565_encode(r, g, b) * p.LCD_PIXELS)
        print(f"Uploading solid color ({r}, {g}, {b}) to LCD...")

    with UsbDevice() as dev:
        dev.upload_image(bytes(data))
    print("Done.")


def cmd_sync_time(_args) -> None:
    now = datetime.datetime.now()
    with UsbDevice() as dev:
        dev.set_time(now.year, now.month, now.day, now.hour, now.minute, now.second)
    print(f"Keyboard clock synced to {now.strftime('%Y-%m-%d %H:%M:%S')}")


def cmd_probe(_args) -> None:
    print(f"Probing for AK820 Pro (VID {p.VENDOR_ID:04X}, PID {p.PRODUCT_ID:04X})...")
    with UsbDevice():
        print("Successfully connected to AK820 Pro!")
        print("Device is ready for commands.")


def cmd_test(_args) -> None:
    print("=== Test: two lighting changes in one session ===")
    with UsbDevice() as dev:
        print("\n1) Setting RED breath...")
        dev.set_lighting(p.LightingMode.Breath, 255, 0, 0, False, 5, 3, p.Direction.Left)
        print("   Done. Waiting 5 seconds: look at keyboard...")
        time.sleep(5)

        print("2) Setting GREEN breath...")
        dev.set_lighting(p.LightingMode.Breath, 0, 255, 0, False, 5, 3, p.Direction.Left)
        print("   Done. Waiting 5 seconds: look at keyboard...")
        time.sleep(5)

        print("3) Setting BLUE breath...")
        dev.set_lighting(p.LightingMode.Breath, 0, 0, 255, False, 5, 3, p.Direction.Left)
        print("   Done.")

    print("\n=== Which colors did you see? (red, green, blue) ===")


COMMANDS = {
    "list-modes": cmd_list_modes,
    "light": cmd_light,
    "sleep": cmd_sleep,
    "stats": cmd_stats,
    "lcd": cmd_lcd,
    "lcd-test": cmd_lcd_test,
    "sync-time": cmd_sync_time,
    "probe": cmd_probe,
    "test": cmd_test,
}


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        COMMANDS[args.command](args)
    except KeyboardInterrupt:
        print()
        return 0
    except (DeviceError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
