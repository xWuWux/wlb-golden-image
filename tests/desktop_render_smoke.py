#!/usr/bin/env python3
"""Analiza zrzutu pulpitu dla tests/desktop-render-smoke.sh (#205).

Liczy piksele tła i tekstu w regionie kontrolowanego okna oraz liczbę kolorów na ekranie.
Liczba kolorów jest tylko diagnostyką — o PASS decyduje obecność tła, pikseli tekstu
i zmiana regionu po interakcji (to ostatnie porównuje skrypt przez `crop_sha256`).

Wyjście: JSON na stdout. Kod 0 = analiza OK, 2 = błąd obrazu/parametrów.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MAX_COLORS = 1_000_000
BACKGROUND_TOLERANCE = 4
FOREGROUND_TOLERANCE = 60


def parse_color(text: str) -> tuple[int, int, int]:
    """Zamienia #rgb lub #rrggbb na trójkę RGB."""
    value = text.strip()
    if not value.startswith("#"):
        raise ValueError(f"kolor musi zaczynać się od #: {text!r}")
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    if len(digits) != 6:
        raise ValueError(f"kolor musi mieć postać #rgb lub #rrggbb: {text!r}")
    try:
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"niepoprawny kolor: {text!r}") from exc


def parse_window(text: str) -> tuple[int, int, int, int]:
    """Parsuje X,Y,W,H."""
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise ValueError(f"okno musi mieć postać X,Y,W,H: {text!r}")
    try:
        x, y, width, height = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"współrzędne okna muszą być liczbami: {text!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"rozmiar okna musi być dodatni: {width}x{height}")
    return x, y, width, height


def near(pixel: tuple[int, int, int], target: tuple[int, int, int], tolerance: int) -> bool:
    return all(abs(channel - wanted) <= tolerance for channel, wanted in zip(pixel, target, strict=True))


def count_colors(image) -> int:
    colors = image.getcolors(maxcolors=MAX_COLORS)
    return MAX_COLORS + 1 if colors is None else len(colors)


def analyze(image_path: Path, window: tuple[int, int, int, int], bg: str, fg: str) -> dict[str, object]:
    from PIL import Image  # import lokalny: czytelny błąd, gdy brak Pillow

    x, y, width, height = window
    bg_rgb = parse_color(bg)
    fg_rgb = parse_color(fg)

    with Image.open(image_path) as source:
        image = source.convert("RGB")
        screen_width, screen_height = image.size
        if x < 0 or y < 0 or x + width > screen_width or y + height > screen_height:
            raise ValueError(f"okno {width}x{height}+{x}+{y} wykracza poza zrzut {screen_width}x{screen_height}")
        crop = image.crop((x, y, x + width, y + height))
        background_pixels = 0
        foreground_pixels = 0
        for pixel in crop.getdata():
            if near(pixel, bg_rgb, BACKGROUND_TOLERANCE):
                background_pixels += 1
            if near(pixel, fg_rgb, FOREGROUND_TOLERANCE):
                foreground_pixels += 1
        total = width * height
        return {
            "ok": True,
            "image": str(image_path),
            "width": screen_width,
            "height": screen_height,
            "window": {"x": x, "y": y, "width": width, "height": height},
            "screen_colors": count_colors(image),
            "window_colors": count_colors(crop),
            "background_pixels": background_pixels,
            "foreground_pixels": foreground_pixels,
            "background_fraction": round(background_pixels / total, 6),
            "crop_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
        }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze_parser = subparsers.add_parser("analyze", help="analiza regionu okna na zrzucie")
    analyze_parser.add_argument("--image", required=True, type=Path)
    analyze_parser.add_argument("--window", required=True, help="X,Y,W,H")
    analyze_parser.add_argument("--bg", required=True, help="kolor tła okna (#rrggbb)")
    analyze_parser.add_argument("--fg", required=True, help="kolor tekstu (#rrggbb)")
    args = parser.parse_args(argv)

    try:
        result = analyze(args.image, parse_window(args.window), args.bg, args.fg)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
