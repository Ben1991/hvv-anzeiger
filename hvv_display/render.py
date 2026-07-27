from __future__ import annotations

import math
import os
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Departure

WIDTH = 320
HEIGHT = 240
BLUE = "#003c78"
LIGHT_BLUE = "#1d75b8"
RED = "#d52b2f"
WHITE = "#ffffff"
MUTED = "#b9c0c7"
ROW_LINE = "#48515a"
BLACK = "#090b0d"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    mac_filename = "Arial Bold.ttf" if bold else "Arial.ttf"
    candidates = [
        Path(os.environ.get("HVV_FONT_DIR", "")) / filename,
        Path("/usr/share/fonts/truetype/dejavu") / filename,
        Path("/usr/share/fonts/dejavu") / filename,
        Path("/System/Library/Fonts/Supplemental") / mac_filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    try:
        return ImageFont.truetype(filename, size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    *,
    start_size: int,
    min_size: int = 12,
    bold: bool = False,
) -> tuple[str, ImageFont.FreeTypeFont]:
    for size in range(start_size, min_size - 1, -1):
        font = _font(size, bold)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text, font
    font = _font(min_size, bold)
    shortened = text
    while shortened and draw.textbbox(
        (0, 0), shortened + "…", font=font
    )[2] > max_width:
        shortened = shortened[:-1]
    return shortened.rstrip() + "…", font


def _line_badge(
    draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, line: str
) -> None:
    point = min(8, width // 5)
    draw.polygon(
        [
            (x + point, y),
            (x + width, y),
            (x + width - point, y + height),
            (x, y + height),
        ],
        fill=RED,
    )
    font = _font(18 if len(line) <= 3 else 15, bold=True)
    box = draw.textbbox((0, 0), line, font=font)
    draw.text(
        (x + (width - (box[2] - box[0])) / 2, y + (height - (box[3] - box[1])) / 2 - 2),
        line,
        font=font,
        fill=WHITE,
    )


def render_board(
    departures: list[Departure],
    *,
    now: datetime,
    last_updated: datetime | None = None,
    stale: bool = False,
    error_message: str | None = None,
    max_rows: int = 5,
) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)

    header_height = 42
    draw.rectangle((0, 0, WIDTH, header_height), fill=BLUE)
    draw.rectangle((0, header_height - 4, 210, header_height), fill=LIGHT_BLUE)
    draw.text((10, 8), "HVV  ABFAHRT", font=_font(19, bold=True), fill=WHITE)
    clock = now.strftime("%H:%M")
    clock_font = _font(25, bold=True)
    clock_width = draw.textbbox((0, 0), clock, font=clock_font)[2]
    draw.text((WIDTH - clock_width - 9, 5), clock, font=clock_font, fill=WHITE)

    available = departures[:max_rows]
    row_height = 39
    if not available:
        message = "Keine passenden Abfahrten"
        if error_message:
            message = "Keine aktuellen Daten"
        text, font = _fit_text(
            draw, message, WIDTH - 24, start_size=22, min_size=16, bold=True
        )
        text_width = draw.textbbox((0, 0), text, font=font)[2]
        draw.text(
            ((WIDTH - text_width) / 2, 102), text, font=font, fill=WHITE
        )
        draw.text(
            (42, 136),
            "Nächster Versuch automatisch",
            font=_font(14),
            fill=MUTED,
        )
    else:
        for index, departure in enumerate(available):
            y = header_height + index * row_height
            draw.line((8, y + row_height - 1, WIDTH - 8, y + row_height - 1), fill=ROW_LINE)
            _line_badge(draw, 9, y + 6, 58, 27, departure.line)

            destination, destination_font = _fit_text(
                draw,
                departure.destination,
                164,
                start_size=18,
                min_size=13,
            )
            draw.text((76, y + 7), destination, font=destination_font, fill=WHITE)

            if departure.cancelled:
                right_text = "AUS"
                right_font = _font(18, bold=True)
                right_color = RED
            else:
                minutes = max(
                    0, math.ceil((departure.departure_time - now).total_seconds() / 60)
                )
                right_text = "sofort" if minutes == 0 else f"{minutes} min"
                right_font = _font(17, bold=True)
                right_color = WHITE
            right_width = draw.textbbox((0, 0), right_text, font=right_font)[2]
            draw.text(
                (WIDTH - right_width - 8, y + 5),
                right_text,
                font=right_font,
                fill=right_color,
            )
            absolute = departure.departure_time.strftime("%H:%M")
            absolute_font = _font(10)
            absolute_width = draw.textbbox((0, 0), absolute, font=absolute_font)[2]
            draw.text(
                (WIDTH - absolute_width - 8, y + 25),
                absolute,
                font=absolute_font,
                fill=MUTED,
            )

    if stale:
        label = "DATEN VERALTET"
        if last_updated:
            label += f" · {last_updated.strftime('%H:%M')}"
        draw.rectangle((0, HEIGHT - 14, WIDTH, HEIGHT), fill=RED)
        draw.text((7, HEIGHT - 14), label, font=_font(10, bold=True), fill=WHITE)
    return image
