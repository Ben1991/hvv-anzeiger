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

    def __init__(self) -> None:
        self.serial: Any = None
        self.initialization: list[tuple[str, tuple[int, ...]]] = []
        self.recording = True
        self._recording_command: tuple[int, ...] = ()

    def command(self, *command: int) -> None:
        if self.recording:
            self._recording_command = command
            self.initialization.append(("command", command))
        else:
            if self.serial is None:
                raise RuntimeError("SPI ist nicht verbunden")
            self.serial.command(*command)

    def data(self, data: Any) -> None:
        if self.recording:
            # luma sends register arguments as DATA, too. Only RAM pixel
            # transfers after Memory Write (0x2C) may be omitted from replay.
            if self._recording_command != (0x2C,):
                self.initialization.append(("data", tuple(data)))
        else:
            if self.serial is None:
                raise RuntimeError("SPI ist nicht verbunden")
            self.serial.data(data)

    def cleanup(self) -> None:
        serial, self.serial = self.serial, None
        if serial is not None:
            serial.cleanup()

    def hardware_reset(self, pin: int) -> None:
        # luma has no public reset method. Reuse its configured GPIO backend
        # instead of constructing another SPI/device with another exit hook.
        gpio = self.serial._gpio
        try:
            gpio.output(pin, gpio.LOW)
            time.sleep(0.1)
        finally:
            gpio.output(pin, gpio.HIGH)
        time.sleep(0.15)


class Ili9341Display:
    def __init__(self, config: DisplayConfig) -> None:
        try:
            from luma.core.error import Error as DriverError
            from luma.core.framebuffer import full_frame
            from luma.core.interface.serial import spi
            from luma.lcd.device import ili9341
        except ImportError as exc:
            raise RuntimeError(
                "Display-Treiber fehlt. Installation gemäß README ausführen."
            ) from exc

        self._config = config
        self._spi_factory = spi
        self._driver_errors = (DriverError, OSError, RuntimeError)
        self._serial = _ReplaySerial()
        self._reset_pin = config.gpio_reset
        self._ready = False
        self._closed = False
        # Capture initialization without touching SPI/GPIO. Failed connection
        # attempts then reuse this device and its single luma exit hook.
        try:
            self._device: Any = ili9341(
                serial_interface=self._serial,
                width=320,
                height=240,
                rotate=config.rotate,
                bgr=config.bgr,
                framebuffer=full_frame(),
                # Documented LED wiring uses 3.3 V, not luma's default GPIO 18.
                backlight=lambda _enabled: None,
            )
        except self._driver_errors as exc:
            raise RuntimeError(
                "Displaytreiber konnte nicht initialisiert werden"
            ) from exc
        self._serial.recording = False
        # Old exit hooks must never send hide/clear commands on reused pins.
        self._device.persist = True
        self._next_recovery_at = 0.0

    @property
    def connected(self) -> bool:
        return self._ready and not self._closed

    def disconnect(self) -> None:
        """Release a failed SPI handle once, preserving the reusable driver."""
        self._ready = False
        self._next_recovery_at = 0.0
        try:
            self._serial.cleanup()
        except self._driver_errors:
            LOG.debug("SPI nach Displayfehler nicht freigegeben")

    def close(self) -> None:
        self._closed = True
        self.disconnect()

    def initialize(self) -> None:
        if self._closed:
            raise RuntimeError("Display ist geschlossen")
        if self.connected:
            return
        config = self._config
        try:
            self._serial.serial = self._spi_factory(
                port=config.spi_port,
                device=config.spi_device,
                gpio_DC=config.gpio_dc,
                gpio_RST=config.gpio_reset,
                bus_speed_hz=config.bus_speed_hz,
                reset_hold_time=0.1,
                reset_release_time=0.15,
            )
            self._replay_initialization()
            self._device.clear()
        except self._driver_errors as exc:
            self.disconnect()
            raise RuntimeError("Displayverbindung fehlgeschlagen") from exc
        self._ready = True

    def recover_if_due(self) -> bool:
        """Reset silent controller corruption even when SPI reports success.

        Reuse the device and transport: repeatedly constructing luma devices
        would register an unbounded number of atexit hooks. A successful SPI
        write does not prove that a disconnected panel received the command.
        """
        if not self.connected:
            self.initialize()
            return True
        if time.monotonic() < self._next_recovery_at:
            return False
        try:
            self._serial.hardware_reset(self._reset_pin)
            self._replay_initialization()
        except self._driver_errors as exc:
            self.disconnect()
            raise RuntimeError("Display-Reset fehlgeschlagen") from exc
        LOG.debug("Displaycontroller vorsorglich neu initialisiert")
        return True

    def _replay_initialization(self) -> None:
        self._serial.command(0x01)  # ILI9341 software reset
        time.sleep(0.15)
        for operation, payload in self._serial.initialization:
            if operation == "command":
                self._serial.command(*payload)
                if payload == (0x11,):  # Sleep out requires 120 ms settling.
                    time.sleep(0.12)
            else:
                self._serial.data(list(payload))
        self._next_recovery_at = time.monotonic() + DISPLAY_RECOVERY_SECONDS

    def show(self, image: Image.Image) -> None:
        if not self.connected:
            self.initialize()
        if image.size != self._device.size:
            image = image.resize(self._device.size)
        try:
            self._device.display(image.convert("RGB"))
        except self._driver_errors as exc:
            self.disconnect()
            raise RuntimeError("Displayübertragung fehlgeschlagen") from exc
