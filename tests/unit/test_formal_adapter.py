"""The differential adapter must preserve ambiguity or reject unsupported input (#352)."""

import json
from pathlib import Path

import pytest
from platform_image_cases import stage_candidate

from formal.compare import project_images


def test_normalization_preserves_duplicate_variant(tmp_path: Path) -> None:
    raw = stage_candidate(tmp_path, "duplicate-variant").read_text()
    images = project_images(raw, "1.2.0")
    names = [image["name"] for image in images]
    assert len(names) == len(set(names)) + 1


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema":1,"schema":1,"version":"1.2.0","images":{}}',
        '{"schema":true,"version":"1.2.0","images":{}}',
        '{"schema":1.0,"version":"1.2.0","images":{}}',
        '{"schema":1,"version":"other","images":{}}',
        '{"schema":1,"version":"1.2.0","images":[]}',
        '{"schema":1,"version":"1.2.0","images":{},"extra":1}',
        '{"schema":1,"version":"1.2.0","images":{"a":{"version":"v","sha256":"x","base_sha256":null,"extra":1}}}',
        '{"schema":1,"version":"1.2.0","images":{"a":{"version":"v","sha256":"x","sha256":"y","base_sha256":null}}}',
    ],
)
def test_normalization_refuses_out_of_domain(raw: str) -> None:
    with pytest.raises(ValueError):
        project_images(raw, "1.2.0")


def test_record_value_keeps_its_type() -> None:
    raw = {"schema": 1, "version": "1.2.0", "images": {"a": {"version": "v", "sha256": 12, "base_sha256": None}}}
    with pytest.raises(ValueError, match="record types"):
        project_images(json.dumps(raw), "1.2.0")
