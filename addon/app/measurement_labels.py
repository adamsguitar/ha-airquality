"""Measurement display labels — keep in sync with custom_components/airquality/measurement_labels.py."""

from __future__ import annotations

MEASUREMENT_LABELS: dict[str, str] = {
    "temperature": "Temperature",
    "temperature_f": "Temperature",
    "temperature_c": "Temperature",
    "humidity": "Humidity",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "co2": "CO₂",
    "voc": "VOC",
    "no2": "NO₂",
    "o3": "O₃",
    "radon": "Radon",
}
