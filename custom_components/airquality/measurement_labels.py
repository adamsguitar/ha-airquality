"""Human-readable labels for measurement type keys (YAML / UI / Lovelace)."""
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


def measurement_label(measurement: str) -> str:
    """Friendly name for a measurement key; falls back to the raw key."""
    return MEASUREMENT_LABELS.get(measurement, measurement)
