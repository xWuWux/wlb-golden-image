"""Porównanie perceptualne zrzutów PNG (SSIM) dla testów akceptacyjnych (#138).

Metryka to SSIM (structural similarity) liczony na skali szarości w jednym
globalnym oknie obejmującym cały obraz. Wybór globalnego okna jest świadomy:
implementacja jest krótka i deterministyczna, a do wykrywania zmiany układu lub
renderu całego zrzutu w zupełności wystarcza. Wersja okienkowa (np. 11x11)
byłaby czulsza na lokalne różnice, ale wymagałaby mapy SSIM i dodatkowego
strojenia progów.

Drobny szum i antyaliasing są tolerowane dzięki stałym stabilizującym SSIM
(C1, C2). Wynik jest przycinany do [0, 1], ponieważ surowy SSIM może być ujemny
dla obrazów antykorelowanych.

Jeśli kandydat ma inny rozmiar niż baseline, jest skalowany do rozmiaru
baseline algorytmem LANCZOS. Dzięki temu porównanie nie wymaga identycznych
wymiarów, ale maskuje różnice wynikające wyłącznie ze skalowania.

numpy jest używany, gdy jest dostępny w środowisku testowym; w przeciwnym razie
te same momenty są liczone przez Pillow/ImageMath. Obie ścieżki dają ten sam
wynik z dokładnością do zaokrągleń zmiennoprzecinkowych.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageMath, ImageStat

try:
    import numpy as np
except ImportError:  # pragma: no cover - w CI numpy nie jest instalowany
    np = None

# Stałe stabilizujące SSIM dla 8-bitowej skali szarości (Wang i in., 2004).
_L = 255.0
_C1 = (0.01 * _L) ** 2
_C2 = (0.03 * _L) ** 2


def _load_gray(path: str | Path) -> Image.Image:
    """Wczytuje PNG i konwertuje go do 8-bitowej skali szarości."""
    with Image.open(path) as source:
        return source.convert("L")


def _prepare(baseline_png: str | Path, candidate_png: str | Path) -> tuple[Image.Image, Image.Image]:
    """Wczytuje obrazy i dopasowuje rozmiar kandydata do baseline."""
    baseline = _load_gray(baseline_png)
    candidate = _load_gray(candidate_png)
    if candidate.size != baseline.size:
        candidate = candidate.resize(baseline.size, Image.Resampling.LANCZOS)
    return baseline, candidate


def _ssim_from_moments(mu_x: float, mu_y: float, var_x: float, var_y: float, cov: float) -> float:
    """Liczy globalny SSIM z momentów i przycina wynik do [0, 1]."""
    numerator = (2 * mu_x * mu_y + _C1) * (2 * cov + _C2)
    denominator = (mu_x * mu_x + mu_y * mu_y + _C1) * (var_x + var_y + _C2)
    return max(0.0, min(1.0, numerator / denominator))


def _ssim_numpy(baseline: Image.Image, candidate: Image.Image) -> float:
    """Wariant SSIM z numpy (szybszy dla dużych zrzutów)."""
    x = np.asarray(baseline, dtype=np.float64)
    y = np.asarray(candidate, dtype=np.float64)
    mu_x = x.mean()
    mu_y = y.mean()
    var_x = x.var()
    var_y = y.var()
    cov = ((x - mu_x) * (y - mu_y)).mean()
    return _ssim_from_moments(mu_x, mu_y, var_x, var_y, cov)


def _ssim_pillow(baseline: Image.Image, candidate: Image.Image) -> float:
    """Wariant SSIM wyłącznie z Pillow (bez numpy)."""
    stat_x = ImageStat.Stat(baseline)
    stat_y = ImageStat.Stat(candidate)
    # ImageMath liczy iloczyn pikseli dokładnie w trybie I (bez zaokrąglania
    # ImageChops.multiply), a resize do 1x1 z filtrem BOX daje jego średnią.
    # ImageStat nie nadaje się tu, bo dla trybów I/F grupuje piksele w 256 binów.
    product = ImageMath.lambda_eval(lambda args: args["x"] * args["y"], x=baseline, y=candidate)
    mu_x = stat_x.mean[0]
    mu_y = stat_y.mean[0]
    var_x = stat_x.var[0]
    var_y = stat_y.var[0]
    mu_xy = product.convert("F").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    return _ssim_from_moments(mu_x, mu_y, var_x, var_y, mu_xy - mu_x * mu_y)


def compare(baseline_png: str | Path, candidate_png: str | Path, threshold: float) -> tuple[float, bool]:
    """Porównuje dwa PNG i zwraca ``(score, ok)``, gdzie ``ok = score >= threshold``.

    ``score`` jest w przedziale [0, 1]. Kandydat o innym rozmiarze jest
    skalowany do rozmiaru baseline algorytmem LANCZOS.
    """
    baseline, candidate = _prepare(baseline_png, candidate_png)
    score = _ssim_numpy(baseline, candidate) if np is not None else _ssim_pillow(baseline, candidate)
    score = float(score)
    return score, score >= threshold
