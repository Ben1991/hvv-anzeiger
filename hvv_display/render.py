from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
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


@dataclass(frozen=True)
class LineStyle:
    """Allowlisted visual style shared by the display and web renderer."""

    token: str
    shape: str
    background: str
    foreground: str


_LINE_STYLES = {
    "bus": LineStyle("bus", "pointed", RED, WHITE),
    "u1": LineStyle("u1", "rectangle", "#1d75b8", WHITE),
    "u2": LineStyle("u2", "rectangle", RED, WHITE),
    "u3": LineStyle("u3", "rectangle", "#f4c20d", BLACK),
    "u4": LineStyle("u4", "rectangle", "#00a6d6", WHITE),
    "sbahn": LineStyle("sbahn", "circle", "#168447", WHITE),
    "s2": LineStyle("s2", "circle", "#c2188b", WHITE),
    "s3": LineStyle("s3", "circle", "#7b3f98", WHITE),
    "s5": LineStyle("s5", "circle", "#154273", WHITE),
    "s7": LineStyle("s7", "circle", "#e87511", WHITE),
    "akn": LineStyle("akn", "circle", "#e87511", WHITE),
    "regional": LineStyle("regional", "rectangle", "#59636e", WHITE),
    "xpress": LineStyle("xpress", "pointed", "#006a9b", WHITE),
    "night": LineStyle("night", "pointed", "#473b8f", WHITE),
    "ferry": LineStyle("ferry", "pointed", "#007c91", WHITE),
    "neutral": LineStyle("neutral", "rounded", "#59636e", WHITE),
}


def _style_input(value: object) -> str:
    return "".join(
        character for character in str(value or "").upper() if character.isalnum()
    )


def get_line_style(line_name: str, product: str | None = None) -> LineStyle:
    """Return a fixed, safe style for an external line/product value."""
    line = _style_input(line_name)
    mode = _style_input(product)
    if not line:
        return _LINE_STYLES["neutral"]

    exact_lines = {"U1": "u1", "U2": "u2", "U3": "u3", "U4": "u4"}
    if line in exact_lines:
        return _LINE_STYLES[line.lower()]
    if line in {"S2", "S3", "S5", "S7"}:
        return _LINE_STYLES[line.lower()]
    if re.fullmatch(r"U\d+", line) or mode in {"U", "UBAHN", "SUBWAY"}:
        return _LINE_STYLES["u1"]
    if re.fullmatch(r"S\d+", line) or mode in {"S", "SBAHN", "SBAN"}:
        return _LINE_STYLES["sbahn"]
    if re.fullmatch(r"A\d+", line) or mode in {"A", "AKN"}:
        return _LINE_STYLES["akn"]
    if re.fullmatch(r"(?:RE|RB)\d*", line) or mode in {
        "RE",
        "RB",
        "REGIONAL",
        "REGIONALBAHN",
    }:
        return _LINE_STYLES["regional"]
    if mode in {"FAEHRE", "FAHRE", "FERRY", "HAFENFAEHRE"}:
        return _LINE_STYLES["ferry"]
    if mode in {"XPRESS", "XPRESSBUS", "XBUS"} or re.fullmatch(r"X\d+", line):
        return _LINE_STYLES["xpress"]
    if mode in {"NACHT", "NACHTBUS", "NIGHTBUS"} or re.fullmatch(r"N\d+", line):
        return _LINE_STYLES["night"]
    if mode in {"BUS", "METROBUS"} or re.fullmatch(r"M?\d{1,4}[A-Z]?", line):
        return _LINE_STYLES["bus"]
    return _LINE_STYLES["neutral"]


# Keep the issue/API wording available while Python callers use snake_case.
getLineStyle = get_line_style


def line_style_css() -> str:
    """Generate web CSS from the same allowlisted style catalog."""
    shape_css = {
        "pointed": "clip-path:polygon(12% 0,100% 0,88% 100%,0 100%);",
        "circle": "border-radius:999px;",
        "rectangle": "border-radius:3px;",
        "rounded": "border-radius:7px;",
    }
    return "".join(
        f".line-badge-{style.token}{{background:{style.background};"
        f"color:{style.foreground};{shape_css[style.shape]}}}"
        for style in _LINE_STYLES.values()
    )


@lru_cache(maxsize=32)
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
    while (
        shortened and draw.textbbox((0, 0), shortened + "…", font=font)[2] > max_width
    ):
        shortened = shortened[:-1]
    return shortened.rstrip() + "…", font


def _line_badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    line: str,
    product: str | None = None,
) -> None:
    style = get_line_style(line, product)
    bounds = (x, y, x + width, y + height)
    if style.shape == "pointed":
        point = min(8, width // 5)
        draw.polygon(
            [
                (x + point, y),
                (x + width, y),
                (x + width - point, y + height),
                (x, y + height),
            ],
            fill=style.background,
        )
    elif style.shape == "circle":
        draw.ellipse(bounds, fill=style.background)
    elif style.shape == "rectangle":
        draw.rectangle(bounds, fill=style.background)
    else:
        draw.rounded_rectangle(bounds, radius=5, fill=style.background)
    line_text = str(line or "?")[:32]
    text, font = _fit_text(
        draw,
        line_text,
        width - 10,
        start_size=18 if len(line_text) <= 3 else 15,
        min_size=10,
        bold=True,
    )
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (x + (width - (box[2] - box[0])) / 2, y + (height - (box[3] - box[1])) / 2 - 2),
        text,
        font=font,
        fill=style.foreground,
    )


def _station_badge(draw: ImageDraw.ImageDraw, x: int, y: int, label: str) -> None:
    if not label:
        return
    draw.rounded_rectangle((x, y, x + 18, y + 17), radius=3, fill=BLUE)
    font = _font(10, bold=True)
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(
        (
            x + (18 - (box[2] - box[0])) / 2,
            y + (17 - (box[3] - box[1])) / 2 - 1,
        ),
        label,
        font=font,
        fill=WHITE,
    )


def _status_text(
    *,
    wifi_is_connected: bool | None,
    stale: bool,
    last_updated: datetime | None,
    time_is_synchronized: bool | None = True,
) -> str | None:
    if time_is_synchronized is False:
        return "ZEIT NICHT SYNCHRON"
    if wifi_is_connected is False:
        label = "KEIN WLAN"
        if last_updated:
            label += f" · STAND {last_updated.strftime('%H:%M')}"
        return label
    if stale:
        label = "DATEN VERALTET"
        if last_updated:
            label += f" · {last_updated.strftime('%H:%M')}"
        return label
    return None


def board_state_key(
    departures: list[Departure],
    *,
    now: datetime,
    last_updated: datetime | None,
    stale: bool,
    error_message: str | None,
    wifi_is_connected: bool | None,
    max_rows: int,
    time_is_synchronized: bool | None = True,
) -> tuple[object, ...]:
    """Describe only visible state so unchanged frames need not be redrawn."""
    visible_departures = tuple(
        (
            departure.line,
            departure.destination,
            departure.station_label,
            departure.product,
            departure.cancelled,
            (
                "AUS"
                if departure.cancelled
                else max(
                    0,
                    math.ceil((departure.departure_time - now).total_seconds() / 60),
                )
            ),
            departure.departure_time.strftime("%H:%M"),
        )
        for departure in departures[:max_rows]
    )
    return (
        now.strftime("%H:%M"),
        visible_departures,
        bool(error_message) if not visible_departures else False,
        _status_text(
            wifi_is_connected=wifi_is_connected,
            time_is_synchronized=time_is_synchronized,
            stale=stale,
            last_updated=last_updated,
        ),
    )


def render_board(
    departures: list[Departure],
    *,
    now: datetime,
    last_updated: datetime | None = None,
    stale: bool = False,
    error_message: str | None = None,
    wifi_is_connected: bool | None = None,
    max_rows: int = 5,
    time_is_synchronized: bool | None = True,
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
        draw.text(((WIDTH - text_width) / 2, 102), text, font=font, fill=WHITE)
        draw.text(
            (42, 136),
            "Nächster Versuch automatisch",
            font=_font(14),
            fill=MUTED,
        )
    else:
        for index, departure in enumerate(available):
            y = header_height + index * row_height
            draw.line(
                (8, y + row_height - 1, WIDTH - 8, y + row_height - 1),
                fill=ROW_LINE,
            )
            _line_badge(draw, 9, y + 6, 58, 27, departure.line, departure.product)
            _station_badge(draw, 75, y + 10, departure.station_label)

            destination, destination_font = _fit_text(
                draw,
                departure.destination,
                143 if departure.station_label else 164,
                start_size=18,
                min_size=13,
            )
            destination_x = 99 if departure.station_label else 76
            draw.text(
                (destination_x, y + 7),
                destination,
                font=destination_font,
                fill=WHITE,
            )

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

    status_label = _status_text(
        wifi_is_connected=wifi_is_connected,
        time_is_synchronized=time_is_synchronized,
        stale=stale,
        last_updated=last_updated,
    )
    if status_label:
        draw.rectangle((0, HEIGHT - 14, WIDTH, HEIGHT), fill=RED)
        draw.text(
            (7, HEIGHT - 14),
            status_label,
            font=_font(10, bold=True),
            fill=WHITE,
        )
    return image
