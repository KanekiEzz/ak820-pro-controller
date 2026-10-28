"""GUI control panel: port of src/gui/* (egui) to tkinter (standard library).

Run with:  ak820-gui   or   python -m ak820.gui
"""

from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import colorchooser, ttk
from typing import Callable, List, Optional, Tuple

from . import protocol as p
from .usb_device import DeviceError, UsbDevice

# ---------------------------------------------------------------------------
# Dracula colour palette  https://draculatheme.com
# ---------------------------------------------------------------------------
BG          = "#282a36"   # Dracula Background
CARD        = "#383a59"   # slightly lighter surface
CARD_BORDER = "#44475a"   # Dracula Current Line / border
ACCENT      = "#ff79c6"   # Dracula Pink  — primary action colour
ACCENT_DARK = "#e05fa8"   # pressed / hover
ACCENT2     = "#bd93f9"   # Dracula Purple — slider value, focus ring
FG          = "#f8f8f2"   # Dracula Foreground
FG_MUTED    = "#6272a4"   # Dracula Comment — muted labels
FG_LABEL    = "#f1fa8c"   # Dracula Yellow  — row labels
HEADING_COL = "#8be9fd"   # Dracula Cyan    — section headings
SUCCESS     = "#50fa7b"   # Dracula Green
ERROR       = "#ff5555"   # Dracula Red
SLIDER_TRK  = "#44475a"   # trough background
ENTRY_BG    = "#21222c"   # darker input background

# Legacy aliases kept for _set_status
GREEN = SUCCESS
RED   = ERROR

SLEEP_OPTIONS: List[Tuple[str, p.SleepTime]] = [
    ("Never",       p.SleepTime.Never),
    ("1 minute",    p.SleepTime.OneMinute),
    ("5 minutes",   p.SleepTime.FiveMinutes),
    ("30 minutes",  p.SleepTime.ThirtyMinutes),
]

Result = Tuple[bool, str]  # (ok, message)


# ---------------------------------------------------------------------- #
# Actions (port of gui/actions.rs) — UNCHANGED
# ---------------------------------------------------------------------- #

def format_usb_error(e: Exception) -> str:
    msg = str(e)
    errno = getattr(getattr(e, "__cause__", None), "errno", None)
    if (
        errno == 13
        or "Access denied" in msg
        or "Permission denied" in msg
        or "insufficient permissions" in msg
    ):
        return (
            "Permission denied. Install udev rule:\n"
            "sudo cp 99-ak820.rules /etc/udev/rules.d/\n"
            "sudo udevadm control --reload-rules && sudo udevadm trigger\n"
            "Then replug the keyboard."
        )
    return msg


def _run(fn: Callable[[UsbDevice], str]) -> Result:
    try:
        with UsbDevice() as dev:
            return True, fn(dev)
    except DeviceError as e:
        return False, format_usb_error(e)


def apply_lighting(mode, r, g, b, rainbow, brightness, speed, direction) -> Result:
    def go(dev: UsbDevice) -> str:
        dev.set_lighting(mode, r, g, b, rainbow, brightness, speed, direction)
        return (f"Lighting: {mode.label} | #{r:02x}{g:02x}{b:02x} | "
                f"bright={brightness} speed={speed}")
    return _run(go)


def apply_sleep(sleep_time: p.SleepTime) -> Result:
    def go(dev: UsbDevice) -> str:
        dev.set_sleep_time(sleep_time)
        return f"Sleep timer: {sleep_time.name}"
    return _run(go)


def sync_time() -> Result:
    now = datetime.datetime.now()

    def go(dev: UsbDevice) -> str:
        dev.set_time(now.year, now.month, now.day,
                     now.hour, now.minute, now.second)
        return f"Clock synced to {now.strftime('%Y-%m-%d %H:%M:%S')}"
    return _run(go)


def probe_device() -> Result:
    return _run(lambda _dev: "AK820 Pro connected")


# ---------------------------------------------------------------------- #
# Style bootstrap
# ---------------------------------------------------------------------- #

def _make_style() -> ttk.Style:
    """Configure a Dracula clam-based dark ttk style and return it."""
    s = ttk.Style()
    s.theme_use("clam")

    # ---- root defaults ------------------------------------------------
    s.configure(".",
                 background=BG,
                 foreground=FG,
                 font=("Helvetica Neue", 13),
                 borderwidth=0,
                 relief="flat")

    # ---- frames -------------------------------------------------------
    s.configure("TFrame",      background=BG)
    s.configure("Card.TFrame", background=CARD)

    # ---- labels -------------------------------------------------------
    s.configure("TLabel",
                 background=BG, foreground=FG,
                 font=("Helvetica Neue", 13))
    s.configure("Card.TLabel",
                 background=CARD, foreground=FG,
                 font=("Helvetica Neue", 13))
    s.configure("RowLabel.TLabel",
                 background=CARD, foreground=FG_LABEL,
                 font=("Helvetica Neue", 12))
    s.configure("Heading.TLabel",
                 background=CARD, foreground=HEADING_COL,
                 font=("Helvetica Neue", 11, "bold"))
    s.configure("AppTitle.TLabel",
                 background=BG, foreground=FG,
                 font=("Helvetica Neue", 20, "bold"))
    s.configure("AppSub.TLabel",
                 background=BG, foreground=FG_MUTED,
                 font=("Helvetica Neue", 12))
    s.configure("Msg.TLabel",
                 background=BG, foreground=FG,
                 font=("Helvetica Neue", 12))

    # ---- checkbutton --------------------------------------------------
    s.configure("TCheckbutton",
                 background=CARD, foreground=FG,
                 font=("Helvetica Neue", 13),
                 indicatorcolor=ENTRY_BG,
                 indicatorbackground=ENTRY_BG,
                 focuscolor=ACCENT2)
    s.map("TCheckbutton",
          background=[("active", CARD)],
          foreground=[("active", FG)],
          indicatorcolor=[("selected", ACCENT2), ("pressed", ACCENT_DARK)])

    # ---- combobox -----------------------------------------------------
    s.configure("TCombobox",
                 fieldbackground=ENTRY_BG,
                 background=ENTRY_BG,
                 foreground=FG,
                 selectbackground=ACCENT2,
                 selectforeground=BG,
                 arrowcolor=FG_MUTED,
                 bordercolor=CARD_BORDER,
                 lightcolor=CARD_BORDER,
                 darkcolor=CARD_BORDER,
                 relief="flat",
                 padding=(10, 8),
                 font=("Helvetica Neue", 13))
    s.map("TCombobox",
          fieldbackground=[("readonly", ENTRY_BG)],
          background=[("readonly",     ENTRY_BG)],
          foreground=[("readonly",     FG)],
          selectbackground=[("readonly", ACCENT2)],
          bordercolor=[("focus", ACCENT2), ("!focus", CARD_BORDER)])

    # ---- separator ----------------------------------------------------
    s.configure("TSeparator", background=CARD_BORDER)

    return s


def _card(parent: tk.Misc) -> tuple:
    """Return (outer_frame, inner_frame) — a bordered Dracula card."""
    outer = tk.Frame(parent, background=CARD_BORDER, padx=1, pady=1)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=(18, 16))
    inner.pack(fill="both", expand=True)
    return outer, inner


# ---------------------------------------------------------------------- #
# Application
# ---------------------------------------------------------------------- #

class Ak820App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AK820 Pro Control Panel")
        self.geometry("500x720")
        self.minsize(440, 620)
        self.configure(bg=BG)

        self._style = _make_style()

        # Dracula-style Combobox dropdown listbox
        self.option_add("*TCombobox*Listbox.background",       ENTRY_BG)
        self.option_add("*TCombobox*Listbox.foreground",       FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT2)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.option_add("*TCombobox*Listbox.relief",           "flat")
        self.option_add("*TCombobox*Listbox.font",
                        ("Helvetica Neue", 13))

        self.modes = p.LightingMode.all()
        self.color = [255, 0, 0]

        self.mode_var       = tk.StringVar(value=p.LightingMode.Static.label)
        self.rainbow_var    = tk.BooleanVar(value=False)
        self.brightness_var = tk.IntVar(value=5)
        self.speed_var      = tk.IntVar(value=3)
        self.direction_var  = tk.StringVar()
        self.sleep_var      = tk.StringVar(value=SLEEP_OPTIONS[0][0])

        self._build_ui()
        self._on_mode_change()
        self._set_status(probe_device(), show_message=False)

    # -- Widget helpers ------------------------------------------------- #

    def _accent_button(self, parent: tk.Misc, text: str,
                       command: Callable, width: int = 18) -> tk.Label:
        """Pink Dracula accent button — tk.Label based (macOS-safe)."""
        btn = tk.Label(
            parent, text=text,
            bg=ACCENT, fg=BG,
            font=("Helvetica Neue", 13, "bold"),
            padx=18, pady=10,
            cursor="hand2",
            anchor="center",
            width=width,
        )
        btn.bind("<ButtonPress-1>",
                 lambda _e: btn.configure(bg=ACCENT_DARK))
        btn.bind("<ButtonRelease-1>",
                 lambda _e: (btn.configure(bg=ACCENT), command()))
        btn.bind("<Leave>",
                 lambda _e: btn.configure(bg=ACCENT))
        return btn

    def _ghost_button(self, parent: tk.Misc, text: str,
                      command: Callable) -> tk.Label:
        """Subtle ghost button for secondary actions."""
        btn = tk.Label(
            parent, text=text,
            bg=CARD_BORDER, fg=FG_MUTED,
            font=("Helvetica Neue", 12),
            padx=12, pady=7,
            cursor="hand2",
            anchor="center",
        )
        btn.bind("<ButtonPress-1>",
                 lambda _e: btn.configure(bg=ENTRY_BG, fg=FG))
        btn.bind("<ButtonRelease-1>",
                 lambda _e: (btn.configure(bg=CARD_BORDER, fg=FG_MUTED),
                              command()))
        btn.bind("<Leave>",
                 lambda _e: btn.configure(bg=CARD_BORDER, fg=FG_MUTED))
        return btn

    def _slider_row(self, parent: tk.Misc, label: str,
                    var: tk.IntVar, maximum: int) -> None:
        """Labelled slider row with live purple numeric readout."""
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 2))

        ttk.Label(row, text=label, style="RowLabel.TLabel",
                  width=11).pack(side="left")

        # Numeric readout
        tk.Label(row, textvariable=var,
                 bg=CARD, fg=ACCENT2,
                 font=("Helvetica Neue", 13, "bold"),
                 width=3, anchor="e").pack(side="right")

        tk.Scale(
            row,
            from_=0, to=maximum, resolution=1,
            orient="horizontal", variable=var,
            showvalue=False,
            bg=CARD, fg=FG,
            troughcolor=SLIDER_TRK,
            activebackground=ACCENT2,
            highlightthickness=0, bd=0,
            sliderlength=20,
        ).pack(side="left", fill="x", expand=True, padx=(6, 10))

    def _section_heading(self, parent: tk.Misc, text: str) -> None:
        """Cyan Dracula section heading inside a card."""
        ttk.Label(parent, text=text.upper(),
                  style="Heading.TLabel").pack(anchor="w", pady=(0, 12))

    # -- Main UI construction ------------------------------------------- #

    def _build_ui(self) -> None:
        # Outer scroll-free container
        root = tk.Frame(self, bg=BG, padx=20, pady=18)
        root.pack(fill="both", expand=True)

        # ---- Header ---------------------------------------------------
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", pady=(0, 6))

        title_block = tk.Frame(header, bg=BG)
        title_block.pack(side="left")
        ttk.Label(title_block, text="AK820 Pro",
                  style="AppTitle.TLabel").pack(anchor="w")
        ttk.Label(title_block, text="Keyboard Control Panel",
                  style="AppSub.TLabel").pack(anchor="w")

        # Connection pill on the right
        self._pill_canvas = tk.Canvas(
            header, height=30, width=168,
            bg=BG, highlightthickness=0)
        self._pill_canvas.pack(side="right", pady=(6, 0))
        self._draw_pill(ok=None)

        # Divider line under header
        tk.Frame(root, bg=CARD_BORDER, height=1).pack(fill="x", pady=(8, 14))

        # ---- Last action message bar ----------------------------------
        self.msg_label = tk.Label(
            root, text="",
            anchor="w", justify="left", wraplength=450,
            bg=BG, font=("Helvetica Neue", 12))
        self.msg_label.pack(fill="x", pady=(0, 12))

        # ==== LIGHTING CARD ============================================
        lo, lc = _card(root)
        lo.pack(fill="x", pady=(0, 12))

        self._section_heading(lc, "\u2726  Lighting")

        # Mode
        mrow = ttk.Frame(lc, style="Card.TFrame")
        mrow.pack(fill="x", pady=(0, 8))
        ttk.Label(mrow, text="Mode", style="RowLabel.TLabel",
                  width=11).pack(side="left")
        self.mode_box = ttk.Combobox(
            mrow, textvariable=self.mode_var, state="readonly",
            values=[m.label for m in self.modes])
        self.mode_box.pack(side="left", fill="x", expand=True)
        self.mode_box.bind("<<ComboboxSelected>>",
                           lambda _e: self._on_mode_change())

        # Color swatch
        crow = ttk.Frame(lc, style="Card.TFrame")
        crow.pack(fill="x", pady=(0, 8))
        ttk.Label(crow, text="Color", style="RowLabel.TLabel",
                  width=11).pack(side="left")

        self.swatch = tk.Canvas(
            crow, width=36, height=24,
            highlightthickness=2, highlightbackground=CARD_BORDER,
            cursor="hand2")
        self.swatch.pack(side="left")
        self.swatch.bind("<ButtonRelease-1>",
                         lambda _e: self._pick_color())

        self.color_text = ttk.Label(crow, text="",
                                    style="RowLabel.TLabel",
                                    padding=(12, 0))
        self.color_text.pack(side="left")
        self._refresh_color()

        # Horizontal separator before checkbutton
        tk.Frame(lc, bg=CARD_BORDER, height=1).pack(fill="x", pady=(4, 8))

        # Rainbow checkbox
        ttk.Checkbutton(lc, text="Rainbow mode",
                        variable=self.rainbow_var).pack(
            anchor="w", pady=(0, 6))

        # Sliders
        self._slider_row(lc, "Brightness",
                         self.brightness_var, p.MAX_BRIGHTNESS)
        self._slider_row(lc, "Speed",
                         self.speed_var,      p.MAX_SPEED)

        # Direction row (shown/hidden by mode)
        self.dir_holder = ttk.Frame(lc, style="Card.TFrame")
        self.dir_holder.pack(fill="x")
        self.dir_row = ttk.Frame(self.dir_holder, style="Card.TFrame")
        ttk.Label(self.dir_row, text="Direction",
                  style="RowLabel.TLabel", width=11).pack(side="left")
        self.dir_box = ttk.Combobox(
            self.dir_row, textvariable=self.direction_var,
            state="readonly")
        self.dir_box.pack(side="left", fill="x", expand=True)

        # Apply button
        tk.Frame(lc, bg=CARD_BORDER, height=1).pack(fill="x", pady=(12, 10))
        self._accent_button(lc, "\u2713  Apply Lighting",
                            self._apply_lighting, width=20).pack(
            anchor="w")

        # ==== SLEEP TIMER CARD =========================================
        so, sc = _card(root)
        so.pack(fill="x", pady=(0, 12))
        self._section_heading(sc, "\U0001f319  Sleep Timer")

        srow = ttk.Frame(sc, style="Card.TFrame")
        srow.pack(fill="x", pady=(0, 8))
        ttk.Label(srow, text="Sleep after",
                  style="RowLabel.TLabel", width=11).pack(side="left")
        ttk.Combobox(srow, textvariable=self.sleep_var, state="readonly",
                     values=[label for label, _ in SLEEP_OPTIONS]
                     ).pack(side="left", fill="x", expand=True)

        tk.Frame(sc, bg=CARD_BORDER, height=1).pack(fill="x", pady=(8, 10))
        self._accent_button(sc, "\u2713  Apply Sleep Timer",
                            self._apply_sleep, width=20).pack(anchor="w")

        # ==== CLOCK CARD ===============================================
        co, cc = _card(root)
        co.pack(fill="x", pady=(0, 12))
        self._section_heading(cc, "\U0001f552  Clock")

        self._accent_button(cc, "\u21bb  Sync Time Now",
                            self._sync_time, width=20).pack(
            anchor="w", pady=(0, 8))
        self.sync_label = ttk.Label(cc, text="", style="RowLabel.TLabel")
        self.sync_label.pack(anchor="w")

        # ---- Footer ---------------------------------------------------
        footer = tk.Frame(root, bg=BG)
        footer.pack(fill="x", pady=(4, 0))
        self._ghost_button(
            footer, "\u21ba  Reconnect Device",
            lambda: self._set_status(probe_device(), show_message=False)
        ).pack(side="right")

    # -- Pill drawing --------------------------------------------------- #

    def _draw_pill(self, ok: Optional[bool]) -> None:
        """Draw / redraw the Dracula rounded-rect connection pill."""
        c = self._pill_canvas
        c.delete("all")
        w, h, r = 168, 30, 14

        if ok is True:
            pill_bg = "#1e3a2b"
            dot_col = SUCCESS
            label   = "Connected"
            txt_col = SUCCESS
        elif ok is False:
            pill_bg = "#3a1e22"
            dot_col = ERROR
            label   = "Disconnected"
            txt_col = ERROR
        else:
            pill_bg = "#2e3050"
            dot_col = FG_MUTED
            label   = "Checking\u2026"
            txt_col = FG_MUTED

        # Rounded rect via arc+rect trick
        c.create_arc(0, 0, r*2, h,   start=90,  extent=180,
                     fill=pill_bg, outline=pill_bg)
        c.create_arc(w-r*2, 0, w, h, start=-90, extent=180,
                     fill=pill_bg, outline=pill_bg)
        c.create_rectangle(r, 0, w-r, h,
                           fill=pill_bg, outline=pill_bg)

        dot_r = 5
        cx, cy = 16, h // 2
        c.create_oval(cx-dot_r, cy-dot_r, cx+dot_r, cy+dot_r,
                      fill=dot_col, outline="")
        c.create_text(cx + dot_r + 9, cy,
                      text=label, fill=txt_col,
                      font=("Helvetica Neue", 12), anchor="w")

    # -- State helpers -------------------------------------------------- #

    def _current_mode(self) -> p.LightingMode:
        return p.LightingMode.from_name(self.mode_var.get()) or p.LightingMode.Static

    def _current_direction(self) -> p.Direction:
        dirs = self._current_mode().supported_directions()
        if not dirs:
            return p.Direction.Left
        name = self.direction_var.get()
        for d in dirs:
            if d.name == name:
                return d
        return dirs[0]

    def _current_sleep(self) -> p.SleepTime:
        for label, value in SLEEP_OPTIONS:
            if label == self.sleep_var.get():
                return value
        return p.SleepTime.Never

    def _refresh_color(self) -> None:
        hex_color = "#{:02x}{:02x}{:02x}".format(*self.color)
        self.swatch.configure(bg=hex_color)
        self.swatch.delete("all")
        self.swatch.create_rectangle(0, 0, 36, 24,
                                     fill=hex_color, outline="")
        self.color_text.configure(text=hex_color.upper())

    def _pick_color(self) -> None:
        rgb, _hex = colorchooser.askcolor(
            color="#{:02x}{:02x}{:02x}".format(*self.color),
            parent=self, title="Pick lighting color")
        if rgb is not None:
            self.color = [int(round(c)) for c in rgb]
            self._refresh_color()

    def _on_mode_change(self) -> None:
        """Show the direction selector only for modes that support directions."""
        dirs = self._current_mode().supported_directions()
        if dirs:
            names = [d.name for d in dirs]
            self.dir_box.configure(values=names)
            if self.direction_var.get() not in names:
                self.direction_var.set(names[0])
            self.dir_row.pack(fill="x", pady=(6, 0))
        else:
            self.dir_row.pack_forget()

    def _set_status(self, result: Result, show_message: bool = True) -> None:
        ok, msg = result
        self._draw_pill(ok=ok)
        if show_message:
            self.msg_label.configure(
                text=msg, fg=GREEN if ok else ERROR)
        else:
            self.msg_label.configure(text="")

    # -- Button handlers ------------------------------------------------ #

    def _apply_lighting(self) -> None:
        self._set_status(apply_lighting(
            self._current_mode(),
            self.color[0], self.color[1], self.color[2],
            self.rainbow_var.get(),
            self.brightness_var.get(),
            self.speed_var.get(),
            self._current_direction()))

    def _apply_sleep(self) -> None:
        self._set_status(apply_sleep(self._current_sleep()))

    def _sync_time(self) -> None:
        result = sync_time()
        if result[0]:
            self.sync_label.configure(text=result[1])
        self._set_status(result)


def main() -> None:
    Ak820App().mainloop()


if __name__ == "__main__":
    main()
