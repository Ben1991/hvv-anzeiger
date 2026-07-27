import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from hvv_display.preview import main


class PreviewTest(unittest.TestCase):
    def test_preview_command_writes_display_sized_png(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "preview.png"
            with patch.object(sys, "argv", ["hvv-preview", str(output)]):
                main()

            with Image.open(output) as image:
                self.assertEqual(image.size, (320, 240))
                self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
