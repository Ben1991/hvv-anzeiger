from __future__ import annotations

from typing import Any

from PIL import Image

from .config import DisplayConfig


class Ili9341Display:
    def __init__(self, config: DisplayConfig) -> None:
        try:
            from luma.core.interface.serial import spi
            from luma.lcd.device import ili9341
        except ImportError as exc:
            raise RuntimeError(
                "Display-Treiber fehlt. Installation gemäß README ausführen."
            ) from exc

        serial = spi(
            port=config.spi_port,
            device=config.spi_device,
            gpio_DC=config.gpio_dc,
            gpio_RST=config.gpio_reset,
            bus_speed_hz=config.bus_speed_hz,
        )
        self._device: Any = ili9341(
            serial_interface=serial,
            width=320,
            height=240,
            rotate=config.rotate,
            bgr=config.bgr,
        )

    def show(self, image: Image.Image) -> None:
        if image.size != self._device.size:
            image = image.resize(self._device.size)
        self._device.display(image.convert("RGB"))
