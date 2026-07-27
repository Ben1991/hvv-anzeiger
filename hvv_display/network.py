from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger(__name__)
SYS_CLASS_NET = Path("/sys/class/net")


def wifi_connected(
    interface: str = "wlan0",
    *,
    sys_class_net: Path = SYS_CLASS_NET,
) -> bool | None:
    """Return the Wi-Fi link state, or None when the interface is unavailable."""
    if not interface or Path(interface).name != interface:
        LOG.warning("Ungültiger WLAN-Schnittstellenname: %r", interface)
        return None

    interface_path = sys_class_net / interface
    for status_file, connected_value in (
        (interface_path / "carrier", "1"),
        (interface_path / "operstate", "up"),
    ):
        try:
            value = status_file.read_text(encoding="ascii").strip().lower()
        except (FileNotFoundError, OSError):
            continue
        return value == connected_value

    LOG.warning("WLAN-Schnittstelle %s wurde nicht gefunden", interface)
    return None
