import tempfile
import unittest
from pathlib import Path

from hvv_display.network import wifi_connected


class NetworkTest(unittest.TestCase):
    def write_status(self, root: Path, filename: str, value: str) -> None:
        interface = root / "wlan0"
        interface.mkdir(parents=True, exist_ok=True)
        (interface / filename).write_text(value, encoding="ascii")

    def test_connected_carrier_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_status(root, "carrier", "1\n")
            self.assertTrue(wifi_connected(sys_class_net=root))

    def test_disconnected_carrier_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_status(root, "carrier", "0\n")
            self.assertFalse(wifi_connected(sys_class_net=root))

    def test_operstate_is_used_when_carrier_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_status(root, "operstate", "up\n")
            self.assertTrue(wifi_connected(sys_class_net=root))

    def test_missing_or_invalid_interface_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(wifi_connected(sys_class_net=root))
            self.assertIsNone(
                wifi_connected("../wlan0", sys_class_net=root)
            )


if __name__ == "__main__":
    unittest.main()
