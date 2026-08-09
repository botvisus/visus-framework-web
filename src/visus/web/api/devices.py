"""Named device presets for viewport emulation.

Deliberately small and explicit rather than a vendored descriptor dump: every
entry is a viewport plus a pixel ratio plus the mobile flag, which is exactly
what :meth:`visus.web.Page.set_device_metrics` takes. The user agent is NOT
changed — emulation here is layout-level, and saying so beats implying more.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    """One viewport preset: CSS pixel size, device pixel ratio, and the mobile flag."""

    name: str
    width: int
    height: int
    device_scale_factor: float
    mobile: bool


DEVICES: dict[str, Device] = {
    "iphone 15": Device("iPhone 15", 393, 852, 3.0, True),
    "iphone se": Device("iPhone SE", 375, 667, 2.0, True),
    "pixel 7": Device("Pixel 7", 412, 915, 2.625, True),
    "galaxy s21": Device("Galaxy S21", 360, 800, 3.0, True),
    "ipad mini": Device("iPad Mini", 768, 1024, 2.0, True),
    "desktop": Device("Desktop", 1280, 800, 1.0, False),
}

DEFAULT_MOBILE = "iphone 15"


def get_device(name: str) -> Device:
    """Look up a device preset by name (case- and space-insensitive)."""
    device = DEVICES.get(name.strip().lower())
    if device is None:
        known = ", ".join(sorted(d.name for d in DEVICES.values()))
        raise ValueError(f"unknown device {name!r} — known devices: {known}")
    return device
