"""Tests for measurement label helper."""
from __future__ import annotations

from custom_components.airquality.measurement_labels import MEASUREMENT_LABELS, measurement_label


def test_measurement_label_known():
    assert measurement_label("temperature_f") == "Temperature"
    assert measurement_label("pm25") == "PM2.5"


def test_measurement_label_unknown_fallback():
    assert measurement_label("custom_thing") == "custom_thing"


def test_dict_covers_schema_keys():
    from custom_components.airquality.const import MEASUREMENT_TYPES

    assert MEASUREMENT_TYPES <= set(MEASUREMENT_LABELS)
