from __future__ import annotations

import logging
import time
from typing import Any

from PIL import Image

from .config import DisplayConfig

LOG = logging.getLogger(__name__)
DISPLAY_RECOVERY_SECONDS = 60


class _ReplaySerial:
    """Retain the driver's initialization commands, not its pixel transfers."""

    def __init__(self, serial: Any) -> None:
        self.serial = serial
        self.initialization: list[tuple[int, ...]] = []
        self.recording = True

    def command(self, *command: int) -> None:
        self.serial.command(*command)
        if self.recording:
            self.initialization.append(command)

    def data(self, data: Any) -> None:
        self.serial.data(data)

    def cleanup(self) -> None:
        self.serial.cleanup()


class Ili9341Display:
    def __init__(self, config: DisplayConfig) -> None:
        try:
            from luma.core.framebuffer import full_frame
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
        self._serial = _ReplaySerial(serial)
        self._device: Any = ili9341(
            serial_interface=self._serial,
            width=320,
            height=240,
            rotate=config.rotate,
            bgr=config.bgr,
            framebuffer=full_frame(),
        )
        self._serial.recording = False
        self._next_recovery_at = time.monotonic() + DISPLAY_RECOVERY_SECONDS

    def recover_if_due(self) -> bool:
        """Reset silent controller corruption even when SPI reports success.

        Reuse the device and transport: repeatedly constructing luma devices
        would register an unbounded number of atexit hooks. A successful SPI
        write does not prove that a disconnected panel received the command.
        """
        if time.monotonic() < self._next_recovery_at:
            return False
        self._serial.command(0x01)  # ILI9341 software reset
        time.sleep(0.15)
        for command in self._serial.initialization:
            self._serial.command(*command)
            if command == (0x11,):  # Sleep out: wait before subsequent commands.
                time.sleep(0.12)
        self._next_recovery_at = time.monotonic() + DISPLAY_RECOVERY_SECONDS
        LOG.debug("Displaycontroller vorsorglich neu initialisiert")
        return True

    def show(self, image: Image.Image) -> None:
        if image.size != self._device.size:
            image = image.resize(self._device.size)
        self._device.display(image.convert("RGB"))
