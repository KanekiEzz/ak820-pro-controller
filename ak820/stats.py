"""System stats collection for LCD display.

Port of src/stats.rs. Uses /proc and /sys directly (no psutil needed).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

HWMON_DIR = "/sys/class/hwmon"


@dataclass
class Stats:
    cpu_usage: float
    cpu_temp_c: Optional[float]
    gpu_temp_c: Optional[float]
    memory_used_gb: float
    memory_total_gb: float
    memory_percent: float

    def __str__(self) -> str:
        s = f"CPU: {self.cpu_usage:.0f}%"
        if self.cpu_temp_c is not None:
            s += f" {self.cpu_temp_c:.0f}°C"
        if self.gpu_temp_c is not None:
            s += f" | GPU: {self.gpu_temp_c:.0f}°C"
        s += (
            f" | RAM: {self.memory_used_gb:.1f}/{self.memory_total_gb:.1f} GB "
            f"({self.memory_percent:.0f}%)"
        )
        return s


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return None


def _read_millideg(path: str) -> Optional[float]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return float(text.strip()) / 1000.0
    except ValueError:
        return None


def _hwmon_entries():
    try:
        names = sorted(os.listdir(HWMON_DIR))
    except OSError:
        return
    for entry in names:
        base = os.path.join(HWMON_DIR, entry)
        name = _read_text(os.path.join(base, "name"))
        if name is not None:
            yield base, name.strip()


def find_coretemp_path() -> Optional[str]:
    """Find the CPU hwmon device and return the path to temp1_input."""
    for base, name in _hwmon_entries():
        if name == "coretemp":
            temp_path = os.path.join(base, "temp1_input")
            if os.path.exists(temp_path):
                print(f"Found CPU temp sensor: {temp_path}", file=sys.stderr)
                return temp_path

    # Fallback: try k10temp (AMD) or other common names
    for fallback in ("k10temp", "zenpower", "acpitz"):
        for base, name in _hwmon_entries():
            if name == fallback:
                temp_path = os.path.join(base, "temp1_input")
                if os.path.exists(temp_path):
                    print(f"Found CPU temp sensor ({fallback}): {temp_path}", file=sys.stderr)
                    return temp_path

    print("Warning: no CPU temperature sensor found", file=sys.stderr)
    return None


def _nvidia_smi_temp() -> Optional[float]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    lines = out.stdout.strip().splitlines()
    if not lines:
        return None
    try:
        return float(lines[0].strip())
    except ValueError:
        return None


def find_gpu_temp_reader() -> Optional[Callable[[], Optional[float]]]:
    """Find the best method for reading GPU temperature."""
    # nvidia-smi first (works for NVIDIA GPUs)
    if _nvidia_smi_temp() is not None:
        print("Found GPU temp sensor: nvidia-smi", file=sys.stderr)
        return _nvidia_smi_temp

    # hwmon for amdgpu, i915, nouveau
    for base, name in _hwmon_entries():
        if name in ("amdgpu", "i915", "nouveau"):
            temp_path = os.path.join(base, "temp1_input")
            if os.path.exists(temp_path):
                print(f"Found GPU temp sensor ({name}): {temp_path}", file=sys.stderr)
                return lambda path=temp_path: _read_millideg(path)

    print("Warning: no GPU temperature sensor found", file=sys.stderr)
    return None


def _read_cpu_times() -> Optional[Tuple[int, int]]:
    """Return (idle_total, all_total) jiffies from the aggregate /proc/stat line."""
    text = _read_text("/proc/stat")
    if not text:
        return None
    first = text.splitlines()[0].split()
    if not first or first[0] != "cpu":
        return None
    try:
        vals = [int(v) for v in first[1:]]
    except ValueError:
        return None
    if len(vals) < 4:
        return None
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
    # guest time is already included in user/nice: don't double count
    total = sum(vals[:8])
    return idle, total


def _read_meminfo() -> Tuple[int, int]:
    """Return (used_bytes, total_bytes). Used = MemTotal - MemAvailable."""
    text = _read_text("/proc/meminfo") or ""
    info = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                info[parts[0][:-1]] = int(parts[1]) * 1024  # kB -> bytes
            except ValueError:
                pass
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    return max(total - available, 0), total


class SystemStats:
    def __init__(self) -> None:
        self._prev = _read_cpu_times()
        self.cpu_temp_path = find_coretemp_path()
        self.gpu_temp_reader = find_gpu_temp_reader()

    def _cpu_usage(self) -> float:
        cur = _read_cpu_times()
        prev, self._prev = self._prev, cur
        if cur is None or prev is None:
            return 0.0
        d_idle = cur[0] - prev[0]
        d_total = cur[1] - prev[1]
        if d_total <= 0:
            return 0.0
        return max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))

    def refresh(self) -> Stats:
        cpu_usage = self._cpu_usage()

        used, total = _read_meminfo()
        gib = 1_073_741_824.0
        mem_used = used / gib
        mem_total = total / gib
        mem_pct = (mem_used / mem_total * 100.0) if mem_total > 0 else 0.0

        cpu_temp = _read_millideg(self.cpu_temp_path) if self.cpu_temp_path else None
        gpu_temp = self.gpu_temp_reader() if self.gpu_temp_reader else None

        return Stats(
            cpu_usage=cpu_usage,
            cpu_temp_c=cpu_temp,
            gpu_temp_c=gpu_temp,
            memory_used_gb=mem_used,
            memory_total_gb=mem_total,
            memory_percent=mem_pct,
        )
