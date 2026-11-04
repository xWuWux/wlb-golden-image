"""Testy analizatora render-smoke bez Pillow (atrapa obrazu, #205)."""

import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

import desktop_render_smoke as smoke  # noqa: E402


class FakeImage:
    """Minimalny obraz RGB zgodny z metodami używanymi przez analizator."""

    current = None

    def __init__(self, pixels, width, height):
        self.pixels = list(pixels)
        self.width = width
        self.height = height
        self.size = (width, height)

    @classmethod
    def open(cls, _path):
        return cls.current

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def convert(self, _mode):
        return self

    def crop(self, box):
        left, top, right, bottom = box
        rows = []
        for y in range(top, bottom):
            rows.extend(self.pixels[y * self.width + left : y * self.width + right])
        return FakeImage(rows, right - left, bottom - top)

    def getdata(self):
        return iter(self.pixels)

    def getcolors(self, maxcolors):
        counts = {}
        for pixel in self.pixels:
            counts[pixel] = counts.get(pixel, 0) + 1
        if len(counts) > maxcolors:
            return None
        return list(counts.items())

    def tobytes(self):
        return bytes(channel for pixel in self.pixels for channel in pixel)


@pytest.fixture
def fake_pil(monkeypatch):
    module = types.SimpleNamespace(Image=FakeImage)
    monkeypatch.setitem(sys.modules, "PIL", module)
    return FakeImage


def image_with_text(fake_pil):
    magenta = (255, 0, 255)
    black = (0, 0, 0)
    pixels = [magenta] * 100
    pixels[0] = black
    pixels[11] = black
    image = fake_pil(pixels, 10, 10)
    fake_pil.current = image
    return image


def test_analiza_liczy_tlo_tekst_i_skrot(fake_pil):
    image_with_text(fake_pil)
    result = smoke.analyze(Path("zrzut.png"), (0, 0, 10, 10), "#ff00ff", "#000000")
    assert result["ok"] is True
    assert result["width"] == 10
    assert result["height"] == 10
    assert result["background_pixels"] == 98
    assert result["foreground_pixels"] == 2
    assert result["background_fraction"] == 0.98
    assert result["window_colors"] == 2
    assert result["screen_colors"] == 2
    assert len(result["crop_sha256"]) == 64


def test_skrot_regionu_zmienia_sie_z_obrazem(fake_pil):
    image = image_with_text(fake_pil)
    first = smoke.analyze(Path("a.png"), (0, 0, 10, 10), "#ff00ff", "#000000")["crop_sha256"]
    image.pixels[50] = (0, 0, 0)
    second = smoke.analyze(Path("a.png"), (0, 0, 10, 10), "#ff00ff", "#000000")["crop_sha256"]
    assert first != second


def test_gradient_bez_dokladnego_tla_nie_ma_pikseli_tla(fake_pil):
    pixels = [(x * 2, x, 255 - x) for x in range(100)]
    image = fake_pil(pixels, 10, 10)
    fake_pil.current = image
    result = smoke.analyze(Path("gradient.png"), (0, 0, 10, 10), "#ff00ff", "#000000")
    assert result["background_pixels"] == 0
    assert result["foreground_pixels"] == 0


def test_okno_poza_zrzutem_jest_bledem(fake_pil):
    image_with_text(fake_pil)
    with pytest.raises(ValueError, match="wykracza"):
        smoke.analyze(Path("a.png"), (9, 9, 2, 2), "#ff00ff", "#000000")


def test_main_zwraca_json_i_kod_bledu(fake_pil, capsys):
    image_with_text(fake_pil)
    code = smoke.main(["analyze", "--image", "a.png", "--window", "0,0,10,10", "--bg", "#ff00ff", "--fg", "#000000"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    code = smoke.main(["analyze", "--image", "a.png", "--window", "zle", "--bg", "#ff00ff", "--fg", "#000000"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "X,Y,W,H" in payload["error"]


def test_parsowanie_kolorow_i_geometrii():
    assert smoke.parse_color("#f0f") == (255, 0, 255)
    assert smoke.parse_color("#FF00FF") == (255, 0, 255)
    assert smoke.parse_window("1,2,30,40") == (1, 2, 30, 40)
    assert smoke.near((254, 1, 255), (255, 0, 255), 4)
    assert not smoke.near((0, 0, 0), (255, 0, 255), 4)
    with pytest.raises(ValueError):
        smoke.parse_color("ff00ff")
    with pytest.raises(ValueError):
        smoke.parse_window("1,2,0,4")
