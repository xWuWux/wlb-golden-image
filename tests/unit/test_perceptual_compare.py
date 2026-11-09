"""Testy jednostkowe porównania perceptualnego PNG (#138).

Obrazy są generowane syntetycznie w ``tmp_path`` przez Pillow, więc testy nie
wymagają sieci ani zewnętrznych plików. Sprawdzamy zarówno przypadki akceptacji
(identyczne, drobny szum, przeskalowany kandydat), jak i odrzucenia (przesunięcie,
puste tło, inny gradient).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

import perceptual_compare  # noqa: E402


def _structured(size: tuple[int, int] = (160, 120)) -> Image.Image:
    """Obraz z mocnymi krawędziami: pasy, prostokąt i elipsa."""
    image = Image.new("L", size, 32)
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 16):
        draw.rectangle((x, 0, x + 7, size[1] - 1), fill=224)
    draw.rectangle((24, 16, 80, 72), fill=128)
    draw.ellipse((96, 32, 144, 96), fill=200)
    return image


def _gradient(size: tuple[int, int] = (160, 120), *, horizontal: bool = True) -> Image.Image:
    """Gładki gradient poziomy albo pionowy."""
    width, height = size
    values = bytearray(width * height)
    span_x = max(width - 1, 1)
    span_y = max(height - 1, 1)
    for y in range(height):
        for x in range(width):
            t = x / span_x if horizontal else y / span_y
            values[y * width + x] = round(255 * t)
    return Image.frombytes("L", size, bytes(values))


def _add_noise(image: Image.Image, amplitude: int = 8) -> Image.Image:
    """Dodaje deterministyczny szum o amplitudzie ±amplitude."""
    values = bytearray(image.tobytes())
    width, _ = image.size
    span = 2 * amplitude + 1
    for index, value in enumerate(values):
        x = index % width
        y = index // width
        delta = ((x * 73 + y * 151 + x * y * 7) % span) - amplitude
        values[index] = max(0, min(255, value + delta))
    return Image.frombytes("L", image.size, bytes(values))


def _save(image: Image.Image, path: Path) -> Path:
    image.save(path)
    return path


def test_identical_images_score_near_one(tmp_path):
    baseline = _structured()
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(baseline.copy(), tmp_path / "candidate.png")

    score, ok = perceptual_compare.compare(baseline_path, candidate_path, 0.99)

    assert score == pytest.approx(1.0)
    assert ok is True


def test_minor_noise_is_tolerated(tmp_path):
    baseline = _gradient()
    candidate = _add_noise(baseline, amplitude=8)
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(candidate, tmp_path / "candidate.png")

    score, ok = perceptual_compare.compare(baseline_path, candidate_path, 0.95)

    assert 0.95 <= score < 1.0
    assert ok is True


def test_shifted_image_is_rejected(tmp_path):
    baseline = _structured()
    candidate = ImageChops.offset(baseline, 7, 0)
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(candidate, tmp_path / "candidate.png")

    score, ok = perceptual_compare.compare(baseline_path, candidate_path, 0.9)

    assert score < 0.5
    assert ok is False


def test_blank_candidate_is_rejected(tmp_path):
    baseline = _structured()
    candidate = Image.new("L", baseline.size, 128)
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(candidate, tmp_path / "candidate.png")

    score, ok = perceptual_compare.compare(baseline_path, candidate_path, 0.5)

    assert score < 0.1
    assert ok is False


def test_different_gradient_is_rejected(tmp_path):
    baseline = _gradient(horizontal=True)
    candidate = _gradient(horizontal=False)
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(candidate, tmp_path / "candidate.png")

    score, ok = perceptual_compare.compare(baseline_path, candidate_path, 0.5)

    assert score < 0.1
    assert ok is False


def test_candidate_size_is_resized_to_baseline(tmp_path):
    baseline = _gradient()
    candidate = baseline.resize((320, 240), Image.Resampling.LANCZOS)
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(candidate, tmp_path / "candidate.png")

    score, ok = perceptual_compare.compare(baseline_path, candidate_path, 0.95)

    assert score >= 0.95
    assert ok is True


def test_threshold_is_inclusive(tmp_path):
    baseline = _structured()
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(baseline.copy(), tmp_path / "candidate.png")

    score, _ = perceptual_compare.compare(baseline_path, candidate_path, 0.0)
    _, ok = perceptual_compare.compare(baseline_path, candidate_path, score)

    assert ok is True


def test_pillow_fallback_matches_numpy(tmp_path, monkeypatch):
    if perceptual_compare.np is None:
        pytest.skip("numpy niedostępny — ścieżka Pillow jest jedyną")

    baseline = _gradient()
    candidate = _add_noise(baseline)
    baseline_path = _save(baseline, tmp_path / "baseline.png")
    candidate_path = _save(candidate, tmp_path / "candidate.png")

    numpy_score, _ = perceptual_compare.compare(baseline_path, candidate_path, 0.0)
    monkeypatch.setattr(perceptual_compare, "np", None)
    pillow_score, _ = perceptual_compare.compare(baseline_path, candidate_path, 0.0)

    assert pillow_score == pytest.approx(numpy_score, abs=1e-6)
