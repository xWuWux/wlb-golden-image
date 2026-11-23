"""Wspólna konfiguracja testów: profile Hypothesis dla etapu 4 (#351)."""

import os

from hypothesis import settings

settings.register_profile("ci", max_examples=50, deadline=None)
settings.register_profile("dev", max_examples=15, deadline=5000)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "ci" if os.getenv("CI") else "dev"))
