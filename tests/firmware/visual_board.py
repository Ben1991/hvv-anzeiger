"""Render real Board::draw operations on the host; no physical LCD emulation.

Uses integer glyph advances, as ESPHome does (no kerning), and bundled fonts.
Requires Pillow and the project's Python dependencies. Pass an ArduinoJson src
path; all generated comparison images and measurements go into --output.
"""

import argparse

# Test assertions and fixed compiler invocation are intentional.
# ruff: noqa: S101, S603, S607
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hvv_display.config import load_config  # noqa: E402
from hvv_display.geofox import HAMBURG_TZ  # noqa: E402
from hvv_display.models import Departure  # noqa: E402
from hvv_display.render import render_board  # noqa: E402
from hvv_display.smart_home import smart_home_payload  # noqa: E402
from hvv_display.web import _departure_payload  # noqa: E402


def font(size, bold):
    return ImageFont.truetype(
        str(ROOT / "esphome/fonts" / f"DejaVuSans{'-Bold' if bold else ''}.ttf"),
        size,
        layout_engine=ImageFont.Layout.BASIC,
    )


def raster(operations):
    image = Image.new("RGB", (320, 240))
    clip = None
    for op in operations:
        kind = op["kind"]
        color = tuple(op["color"])
        if kind == "clip":
            clip = op["box"]
            continue
        if kind == "unclip":
            clip = None
            continue
        layer = image.copy()
        draw = ImageDraw.Draw(layer)
        x, y = op.get("x", 0), op.get("y", 0)
        if kind == "fill":
            draw.rectangle((0, 0, 319, 239), fill=color)
        elif kind == "rectangle":
            draw.rectangle((x, y, x + op["w"] - 1, y + op["h"] - 1), fill=color)
        elif kind == "triangle":
            p = op["points"]
            draw.polygon(list(zip(p[::2], p[1::2], strict=True)), fill=color)
        elif kind == "circle":
            r = op["radius"]
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
        elif kind == "text":
            f = font(op["size"], op["bold"])
            for char in op["text"]:
                draw.text((x, y), char, font=f, fill=color)
                x += int(f.getlength(char))
        else:
            raise AssertionError(kind)
        if clip:
            image.paste(layer.crop(tuple(clip)), tuple(clip[:2]))
        else:
            image = layer
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arduinojson", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-esphome-fonts", action="store_true")
    args = parser.parse_args()
    if args.check_esphome_fonts:
        # Optional in a normal Python environment, mandatory in firmware CI.
        import yaml
        from esphome.components.font import glyph_to_glyphinfo
        from freetype import Face

        core = (ROOT / "esphome/packages/core.yaml").read_text()
        specs = yaml.safe_load(core.split("\nfont:\n")[1].split("\nglobals:\n")[0])
        checked = bitmap_bytes = 0
        for spec in specs:
            face = Face(str(ROOT / "esphome" / spec["file"]))
            pillow = font(spec["size"], "Bold" in spec["file"])
            for char in spec["glyphs"]:
                glyph = glyph_to_glyphinfo(char, face, spec["size"], spec["bpp"])
                assert glyph.advance == int(pillow.getlength(char))
                assert glyph.offset_y == pillow.getbbox(char)[1]
                checked += 1
                bitmap_bytes += len(glyph.bitmap_data)
        print(
            f"ESPHome font metrics: {checked} glyphs match; {bitmap_bytes} bitmap bytes"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    executable = args.output / "render-board"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ROOT / "tests/firmware"),
            "-I",
            str(args.arduinojson),
            str(ROOT / "tests/firmware/render_board.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    glyphs = "".join(chr(i) for i in range(32, 127)) + "ÄÖÜäöüß–…"
    metrics = {
        f"{int(b)}:{s}": {c: int(font(s, b).getlength(c)) for c in glyphs}
        for b in (False, True)
        for s in range(8, 26)
    }
    now = datetime(2026, 10, 15, 12, 8, tzinfo=HAMBURG_TZ)
    config = load_config(ROOT / "config.example.json")
    baseline = [
        Departure(line, "Hauptbahnhof", now + timedelta(minutes=m), station_label="J")
        for line, m in [("U1", 2), ("S1", 5), ("4", 8), ("U4", 12), ("5", 17)]
    ]
    cases = {
        "mockup": baseline,
        "delay-cancel": [
            Departure("U3", "Barmbek", now, delay_seconds=120, station_label="W"),
            Departure("S3", "Altona", now + timedelta(minutes=5), cancelled=True),
        ],
        "long-text": [
            Departure(
                "123456",
                "Überseequartier – Universität Hamburg",
                now + timedelta(minutes=123),
                station_label="Ö",
            )
        ],
        "empty": [],
        "absolute": baseline,
        "stale": baseline,
        "expired": baseline,
        "no-clock": baseline,
        "disabled": baseline,
        "night": [],
    }
    report = {}
    for name, rows in cases.items():
        view = {"data_age_seconds": 0, "departures": _departure_payload(rows, now)}
        payload = json.loads(smart_home_payload(view, config, now)["display_payload"])
        payload["time_mode"] = "departure_time" if name == "absolute" else "countdown"
        if name in ("stale", "night"):
            payload["state"] = name
        data = {
            "metrics": metrics,
            "payload": payload,
            "clock": "12:08",
            "no_clock": name == "no-clock",
            "disabled": name == "disabled",
            "elapsed": 300000 if name == "expired" else 0,
        }
        source = args.output / f"{name}.json"
        source.write_text(json.dumps(data))
        ops = json.loads(
            subprocess.check_output([str(executable), str(source)], text=True)
        )
        image = raster(ops)
        image.save(args.output / f"{name}-esp32.png")
        texts = [o for o in ops if o["kind"] == "text"]
        if name in ("night", "disabled"):
            assert not texts and image.getbbox() is None
        else:
            assert any(
                o["text"] == ("--:--" if name == "no-clock" else "12:08")
                and o["y"] == 5
                for o in texts
            )
        if name == "delay-cancel":
            assert "sofort" in [o["text"] for o in texts]
            assert "AUS" in [o["text"] for o in texts]
            assert not any("+2" in o["text"] for o in texts)
        if name == "absolute":
            assert not any(o["text"].endswith(" min") for o in texts)
        if name in ("expired", "no-clock"):
            assert not any(o["text"] == "Hauptbahnhof" for o in texts)
        if name == "stale":
            assert any("Veraltete Daten" in o["text"] for o in texts)
            assert image.getpixel((0, 239)) == (213, 43, 47)
        if name == "long-text":
            assert any(o["text"].endswith("…") for o in texts)
        if name in ("mockup", "delay-cancel", "absolute", "empty"):
            pi = render_board(
                rows,
                now=now,
                last_updated=now,
                wifi_is_connected=True,
                time_mode=payload["time_mode"],
            )
            pi.save(args.output / f"{name}-pi.png")
            difference = ImageChops.difference(pi, image)
            difference.save(args.output / f"{name}-diff.png")
            mae = sum(ImageStat.Stat(difference).mean) / 3
            report[name] = {"mean_absolute_rgb_error": round(mae, 3)}
            # Allows font kerning/raster differences, rejects the old 25px header,
            # stretched rows, absent clock, or displaced detail/time column.
            assert mae < 12, (name, mae)
        if name == "mockup":
            reference = Image.open(ROOT / "docs/hvv-anzeiger-preview.png").convert(
                "RGB"
            )
            report["checked-in-mockup"] = {
                "mean_absolute_rgb_error": round(
                    sum(ImageStat.Stat(ImageChops.difference(reference, image)).mean)
                    / 3,
                    3,
                )
            }
            assert report["checked-in-mockup"]["mean_absolute_rgb_error"] < 1.0
            comparison = Image.new("RGB", (960, 260), "white")
            d = ImageDraw.Draw(comparison)
            for x, title, panel in [
                (0, "Mockup", reference),
                (320, "Pi (Linux)", pi),
                (640, "ESP32 (Host-Simulation)", image),
            ]:
                d.text((x + 8, 3), title, fill="black")
                comparison.paste(panel, (x, 20))
            comparison.save(args.output / "comparison.png")
            for y in (80, 119, 158, 197, 236):
                assert image.getpixel((8, y)) == (72, 81, 90)
    (args.output / "measurements.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
