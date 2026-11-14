import builtins
import os
import unittest
from dataclasses import replace
from unittest.mock import ANY, Mock, call, patch

from PIL import Image

from hvv_display.config import load_config
from hvv_display.hardware import DISPLAY_RECOVERY_SECONDS, Ili9341Display


class HardwareTest(unittest.TestCase):
    def test_display_driver_receives_spi_configuration_and_rgb_image(self) -> None:
        config = load_config("config.example.json").display
        serial = Mock()
        device = Mock()
        device.size = (320, 240)

        with (
            patch("luma.core.interface.serial.spi", return_value=serial) as spi,
            patch("luma.lcd.device.ili9341", return_value=device) as ili9341,
        ):
            display = Ili9341Display(config)
            display.show(Image.new("RGBA", (160, 120), "red"))

        spi.assert_called_once_with(
            port=config.spi_port,
            device=config.spi_device,
            gpio_DC=config.gpio_dc,
            gpio_RST=config.gpio_reset,
            bus_speed_hz=config.bus_speed_hz,
            reset_hold_time=0.1,
            reset_release_time=0.15,
        )
        ili9341.assert_called_once_with(
            serial_interface=ANY,
            width=320,
            height=240,
            rotate=config.rotate,
            bgr=config.bgr,
            framebuffer=ANY,
            backlight=ANY,
        )
        self.assertIs(ili9341.call_args.kwargs["serial_interface"].serial, serial)
        rendered = device.display.call_args.args[0]
        self.assertEqual(rendered.size, (320, 240))
        self.assertEqual(rendered.mode, "RGB")

    def test_missing_display_driver_has_installation_hint(self) -> None:
        config = load_config("config.example.json").display
        real_import = builtins.__import__

        def reject_luma(name, *args, **kwargs):
            if name.startswith("luma."):
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=reject_luma),
            self.assertRaisesRegex(RuntimeError, "README"),
        ):
            Ili9341Display(config)

    def test_unusable_driver_configuration_is_a_reportable_error(self):
        with (
            patch("luma.lcd.device.ili9341", side_effect=RuntimeError("bad driver")),
            self.assertRaisesRegex(RuntimeError, "nicht initialisiert"),
        ):
            Ili9341Display(load_config("config.example.json").display)

    def test_driver_specific_startup_errors_are_reportable_and_release_spi(self):
        from luma.core.error import DeviceNotFoundError

        config = load_config("config.example.json").display
        with (
            patch("luma.core.interface.serial.spi", side_effect=DeviceNotFoundError()),
            self.assertRaisesRegex(RuntimeError, "Displayverbindung"),
        ):
            Ili9341Display(config).initialize()
        for cleanup_error in (None, OSError("cleanup failed")):
            serial = Mock()
            serial.command.side_effect = OSError("write failed")
            serial.cleanup.side_effect = cleanup_error
            with (
                patch("luma.core.interface.serial.spi", return_value=serial),
                patch("luma.lcd.device.ili9341"),
                self.assertRaisesRegex(RuntimeError, "Displayverbindung"),
            ):
                Ili9341Display(config).initialize()
            serial.cleanup.assert_called_once()

    def test_display_keeps_an_image_that_already_has_device_dimensions(self) -> None:
        config = load_config("config.example.json").display
        device = Mock()
        device.size = (320, 240)
        image = Image.new("RGB", device.size, "blue")
        with (
            patch("luma.core.interface.serial.spi"),
            patch("luma.lcd.device.ili9341", return_value=device),
        ):
            display = Ili9341Display(config)
            display.show(image)
        rendered = device.display.call_args.args[0]
        self.assertEqual(rendered.tobytes(), image.tobytes())

    def test_real_driver_replays_initialization_and_full_frame_after_silent_loss(self):
        """Use real luma rendering; only the physical SPI/GPIO are simulated."""
        config = load_config("config.example.json").display
        serial = Mock()
        image = Image.new("RGB", (320, 240), "red")
        panel = {
            "pixels": b"",
            "accepts_pixels": False,
            "stuck": False,
            "command": None,
            "pixel_format": None,
        }

        def command(*values):
            if panel["stuck"]:
                return  # Simulated controller ignores even SPI software reset.
            panel["command"] = values[0]
            if values == (0x01,):
                panel["accepts_pixels"] = False
                panel["pixel_format"] = None
            elif values == (0x29,):  # Display On completes initialization.
                panel["accepts_pixels"] = panel["pixel_format"] == [0x46]

        def pixels(data):
            if panel["stuck"]:
                return
            if panel["command"] == 0x3A:
                panel["pixel_format"] = list(data)
            elif panel["command"] == 0x2C and panel["accepts_pixels"]:
                panel["pixels"] = bytes(data)

        serial.command.side_effect = command
        serial.data.side_effect = pixels

        def gpio_output(pin, level):
            if pin == config.gpio_reset and level == serial._gpio.HIGH:
                panel["stuck"] = False

        serial._gpio.output.side_effect = gpio_output
        with (
            patch("luma.core.interface.serial.spi", return_value=serial) as spi,
            patch("luma.lcd.device.backlit_device.__rpi_gpio__", return_value=Mock()),
            patch("atexit.register") as register,
            patch("hvv_display.hardware.time.monotonic", return_value=100) as clock,
            patch("hvv_display.hardware.time.sleep") as sleep,
        ):
            display = Ili9341Display(config)
            initialization = display._serial.initialization.copy()
            self.assertIn(("data", (0x46,)), initialization)
            self.assertIn(("data", (0x00, 0xC1, 0x30)), initialization)
            display.show(image)
            sleep.reset_mock()
            frame = serial.data.call_args.args[0]
            self.assertEqual(len(frame), 320 * 240 * 3)
            self.assertEqual(panel["pixels"], bytes(frame))

            # Losing power or DC can silently discard controller state while
            # the host continues to accept every SPI write without an error.
            panel["pixels"] = b"\xff" * len(frame)
            panel["accepts_pixels"] = False
            panel["stuck"] = True
            serial.command(0x01)
            self.assertTrue(panel["stuck"])
            serial.reset_mock()
            display.show(image)
            self.assertEqual(set(panel["pixels"]), {255})
            self.assertNotIn(call(0x01), serial.command.call_args_list)
            clock.return_value = 100 + DISPLAY_RECOVERY_SECONDS - 0.001
            self.assertFalse(display.recover_if_due())
            serial.reset_mock()

            clock.return_value = 100 + DISPLAY_RECOVERY_SECONDS
            self.assertTrue(display.recover_if_due())
            self.assertFalse(panel["stuck"])
            self.assertEqual(
                [
                    entry
                    for entry in serial.method_calls
                    if entry[0] in {"command", "data"}
                ],
                [
                    call.command(0x01),
                    *[
                        call.command(*data)
                        if op == "command"
                        else call.data(list(data))
                        for op, data in initialization
                    ],
                ],
            )
            self.assertEqual(
                sleep.call_args_list,
                [call(0.1), call(0.15), call(0.15), call(0.12)],
            )
            serial._gpio.output.assert_has_calls(
                [
                    call(config.gpio_reset, serial._gpio.LOW),
                    call(config.gpio_reset, serial._gpio.HIGH),
                ]
            )
            self.assertEqual(
                serial.data.call_args_list,
                [call(list(data)) for op, data in initialization if op == "data"],
            )
            display.show(image)
            self.assertEqual(serial.data.call_args.args[0], frame)
            self.assertEqual(panel["pixels"], bytes(frame))
            self.assertFalse(display.recover_if_due())

            # Multiple silent outages reuse the same driver, SPI and exit hook.
            clock.return_value += DISPLAY_RECOVERY_SECONDS
            self.assertTrue(display.recover_if_due())
            display.show(Image.new("RGB", image.size, "black"))
            self.assertEqual(set(serial.data.call_args.args[0]), {0})
            spi.assert_called_once()
            register.assert_called_once()
            display._serial.cleanup()
            serial.cleanup.assert_called_once()

    def test_reset_failure_propagates_and_does_not_postpone_next_attempt(self):
        config = load_config("config.example.json").display
        serial = Mock()
        with (
            patch("luma.core.interface.serial.spi", return_value=serial),
            patch("luma.lcd.device.ili9341"),
            patch("hvv_display.hardware.time.monotonic", return_value=0) as clock,
            patch("hvv_display.hardware.time.sleep"),
        ):
            display = Ili9341Display(config)
            display.initialize()
            clock.return_value = DISPLAY_RECOVERY_SECONDS
            serial.command.side_effect = OSError("SPI disconnected")
            with self.assertRaisesRegex(RuntimeError, "Display-Reset"):
                display.recover_if_due()
            self.assertFalse(display.connected)
            serial.cleanup.assert_called_once()
            serial.command.side_effect = None
            self.assertTrue(display.recover_if_due())

    def test_interrupted_reset_releases_reset_pin_and_can_be_retried(self):
        config = load_config("config.example.json").display
        serial = Mock()
        with (
            patch("luma.core.interface.serial.spi", return_value=serial),
            patch("luma.lcd.device.ili9341"),
            patch("hvv_display.hardware.time.monotonic", return_value=0) as clock,
            patch("hvv_display.hardware.time.sleep") as sleep,
        ):
            display = Ili9341Display(config)
            display.initialize()
            sleep.side_effect = RuntimeError("abort")
            clock.return_value = DISPLAY_RECOVERY_SECONDS
            with self.assertRaisesRegex(RuntimeError, "Display-Reset"):
                display.recover_if_due()
        self.assertEqual(
            serial._gpio.output.call_args_list,
            [
                call(config.gpio_reset, serial._gpio.LOW),
                call(config.gpio_reset, serial._gpio.HIGH),
            ],
        )

    def test_hardware_reset_uses_real_luma_spi_backend_and_configured_gpio(self):
        config = replace(load_config("config.example.json").display, gpio_reset=27)
        gpio = Mock(LOW=0, HIGH=1)
        bus = Mock()
        events = []
        gpio.output.side_effect = lambda pin, level: events.append((pin, level))
        bus.writebytes.side_effect = lambda data: events.append(("spi", list(data)))
        with (
            patch("luma.core.interface.serial.bitbang.__rpi_gpio__", return_value=gpio),
            patch("luma.core.interface.serial.spi.__spidev__", return_value=bus),
            patch("luma.lcd.device.backlit_device.__rpi_gpio__", return_value=gpio),
            patch("atexit.register"),
            patch("hvv_display.hardware.time.monotonic", return_value=0) as clock,
            patch("hvv_display.hardware.time.sleep"),
        ):
            display = Ili9341Display(config)
            display.initialize()
            events.clear()
            clock.return_value = DISPLAY_RECOVERY_SECONDS
            self.assertTrue(display.recover_if_due())
        self.assertEqual(events[:2], [(27, 0), (27, 1)])
        self.assertLess(events.index((27, 1)), events.index(("spi", [0x01])))
        bus.open.assert_called_once_with(config.spi_port, config.spi_device)

    def test_thousand_failed_connections_keep_one_driver_and_no_open_handles(self):
        active = set()
        state = {"init_error": True, "data_error": False, "frame": b""}
        gpio = Mock(LOW=0, HIGH=1)
        test = self

        class Serial:
            def __init__(self, **_kwargs):
                self._gpio = gpio
                self.fd = os.open(os.devnull, os.O_RDONLY)
                active.add(self.fd)
                test.assertEqual(len(active), 1)

            def command(self, *_values):
                if state["init_error"]:
                    raise OSError("controller disconnected")

            def data(self, values):
                if state["data_error"] and len(values) > 64:
                    raise OSError("partial frame lost")
                state["frame"] = bytes(values)

            def cleanup(self):
                os.close(self.fd)
                active.remove(self.fd)

        with (
            patch("luma.core.interface.serial.spi", side_effect=Serial) as factory,
            patch("luma.lcd.device.backlit_device.__rpi_gpio__") as backlight_gpio,
            patch("atexit.register") as register,
            patch("hvv_display.hardware.time.monotonic", return_value=0) as clock,
            patch("hvv_display.hardware.time.sleep"),
        ):
            display = Ili9341Display(load_config("config.example.json").display)
            device = display._device
            initialization = display._serial.initialization.copy()
            try:
                for _ in range(1000):
                    with self.assertRaisesRegex(RuntimeError, "Displayverbindung"):
                        display.initialize()
                    self.assertFalse(display.connected)
                    self.assertFalse(active)
                state["init_error"] = False
                display.initialize()
                display.initialize()  # Already connected: do not reopen the bus.
                image = Image.new("RGB", (320, 240), "red")
                display.show(image)
                self.assertEqual(len(state["frame"]), 230400)
                state["data_error"] = True
                with self.assertRaisesRegex(RuntimeError, "Displayübertragung"):
                    display.show(image)
                self.assertFalse(active)
                state["data_error"] = False
                self.assertTrue(display.recover_if_due())
                display.show(image)
                self.assertEqual(state["frame"], image.tobytes())
                for _ in range(1000):
                    clock.return_value += DISPLAY_RECOVERY_SECONDS
                    self.assertTrue(display.recover_if_due())
                display.show(image)
                self.assertEqual(state["frame"], image.tobytes())
                self.assertIs(display._device, device)
                self.assertEqual(display._serial.initialization, initialization)
                self.assertEqual(factory.call_count, 1002)
                register.assert_called_once()
                backlight_gpio.assert_not_called()
                display.close()
                display.close()
                self.assertFalse(active)
                device.cleanup()  # Old luma hook cannot write to released pins.
                with self.assertRaisesRegex(RuntimeError, "geschlossen"):
                    display.show(image)
                with self.assertRaisesRegex(RuntimeError, "SPI ist nicht verbunden"):
                    display._serial.command(0x01)
                with self.assertRaisesRegex(RuntimeError, "SPI ist nicht verbunden"):
                    display._serial.data([0])
            finally:
                display.close()
                for fd in active.copy():
                    os.close(fd)
                    active.remove(fd)
