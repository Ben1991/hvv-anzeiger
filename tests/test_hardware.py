import unittest
from unittest.mock import Mock, patch

from PIL import Image

from hvv_display.config import load_config
from hvv_display.hardware import Ili9341Display


class HardwareTest(unittest.TestCase):
    def test_display_driver_receives_spi_configuration_and_rgb_image(self) -> None:
        config = load_config("config.example.json").display
        serial = object()
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
        )
        ili9341.assert_called_once_with(
            serial_interface=serial,
            width=320,
            height=240,
            rotate=config.rotate,
            bgr=config.bgr,
        )
        rendered = device.display.call_args.args[0]
        self.assertEqual(rendered.size, (320, 240))
        self.assertEqual(rendered.mode, "RGB")
