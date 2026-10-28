# ak820-ctl (Python)

Linux control software for the Ajazz AK820 Pro keyboard, with a CLI and a Tk GUI.

This is a Python port of [gohv/EPOMAKER-Ajazz-AK820-Pro](https://github.com/gohv/EPOMAKER-Ajazz-AK820-Pro)
(originally written in Rust, MIT licensed). The USB protocol was reverse-engineered by the
original authors; see the credits at the bottom.

The official software only supports Windows. This project talks to the keyboard over USB HID to
control lighting, the sleep timer, the built-in clock, and the TFT screen.

## Features

- 20 lighting modes with RGB color, rainbow, brightness, speed and direction
- Sleep timer (never, 1 min, 5 min, 30 min)
- Clock sync (pushes system time to the keyboard)
- Live CPU/GPU temperature + clock on the 128x128 LCD
- GUI control panel (tkinter)

## Requirements

- Linux
- Python 3.9+
- `libusb-1.0` (`sudo apt install libusb-1.0-0` on Debian/Ubuntu)
- `pyusb` (installed automatically)
- `Pillow` for the LCD commands (`pip install ".[lcd]"`)
- `tkinter` for the GUI (`sudo apt install python3-tk` on Debian/Ubuntu)

## Install

```bash
pip install ".[lcd]"        # installs ak820-ctl and ak820-gui
# or run without installing:
pip install pyusb Pillow
python -m ak820 list-modes
```

## macOS

There is no `apt` or udev on macOS. Use Homebrew instead:

```bash
brew install libusb python-tk
pip install ".[lcd]"
sudo ak820-ctl probe        # macOS usually needs sudo to claim the USB interface
```

Skip the "USB permissions" section below. macOS support is untested: libusb cannot detach
Apple's HID driver, so if `probe` fails with "Access denied" the interface is held by macOS.

## USB permissions (Linux only)

By default the USB device requires root. To use it as a normal user, install the udev rule:

```bash
sudo cp 99-ak820.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and replug the keyboard. Without this step you can still run everything with `sudo`.

## Usage

### GUI

```bash
ak820-gui        # or: python -m ak820.gui
```

### CLI

```bash
ak820-ctl list-modes

ak820-ctl light static --color ff0000 --brightness 5 --speed 3
ak820-ctl light breath --color 00ff00 --rainbow
ak820-ctl light spectrum --brightness 4 --speed 2
ak820-ctl light scrolling --direction up --color 0000ff

ak820-ctl sleep never        # never | 1m | 5m | 30m
ak820-ctl sync-time
ak820-ctl probe
```

Available modes: off, static, single-on, single-off, glittering, falling, colourful, breath,
spectrum, outward, scrolling, rolling, rotating, explode, launch, ripples, flowing, pulsating,
tilt, shuttle.

Options for `light`:

- `--color` / `-c`: hex RGB color (default `ff0000`)
- `--rainbow` / `-r`: use rainbow colors instead of a single color
- `--brightness` / `-b`: 0 to 5 (default 5)
- `--speed` / `-s`: 0 to 5 (default 3)
- `--direction` / `-d`: left, right, up, down (only for modes that support it:
  scrolling = up/down; rolling, flowing, tilt = left/right)

### LCD

```bash
ak820-ctl lcd --interval 5 --max-interval 60   # live time + CPU/GPU temp
ak820-ctl lcd-test red                          # red | green | blue | white | black | diag | hex
ak820-ctl stats                                 # preview the stats in the terminal
```

To run the LCD display at boot, edit the `ExecStart` path in `ak820-lcd.service`, then:

```bash
sudo cp ak820-lcd.service /etc/systemd/system/
sudo systemctl enable --now ak820-lcd
```

### Debugging

- `AK820_DEBUG=1` hex-dumps every packet sent to the keyboard.
- `AK820_IFACE=<n>` overrides the USB interface (default 3, the vendor control interface).

## Project layout

| File | Port of | Purpose |
| --- | --- | --- |
| `ak820/protocol.py` | `protocol.rs` | Packet builders, enums, RGB565 encoding |
| `ak820/usb_device.py` | `usb.rs` | libusb backend (used by the CLI and GUI) |
| `ak820/hidraw.py` | `hidraw.rs` | `/dev/hidraw*` ioctl backend (alternative) |
| `ak820/device.py` | `device.rs` | `hidapi` backend (alternative) |
| `ak820/lcd.py` | `lcd.rs` | 128x128 framebuffer renderer (Pillow) |
| `ak820/stats.py` | `stats.rs` | CPU/GPU temperature and memory stats |
| `ak820/cli.py` | `main.rs` | `ak820-ctl` command |
| `ak820/gui.py` | `gui/*` | `ak820-gui` window (tkinter instead of egui) |

Run the tests with `python -m unittest discover -s tests`.

## How it works

The keyboard uses a Sonix SN32F299 MCU with 4 USB HID interfaces. Interface 3 handles control
commands (lighting, sleep, clock) via HID feature reports; interface 2 receives LCD image data
over an interrupt endpoint.

## Credits & license

MIT, like the original project. Protocol work by the
[TaxMachine C++ reference](https://github.com/TaxMachine/ajazz-keyboard-software-linux) and
[KyleBoyer/TFTTimeSync-node](https://github.com/KyleBoyer/TFTTimeSync-node) (clock sync), as
credited in the original repository.
