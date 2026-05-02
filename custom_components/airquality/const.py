"""Constants for the Air Quality integration."""
from __future__ import annotations

DOMAIN = "airquality"
YAML_FILENAME = "airquality.yaml"

# Services
SERVICE_RELOAD = "reload"
SERVICE_RECOMPUTE = "recompute"
SERVICE_SET_THRESHOLD_PROFILE = "set_threshold_profile"

# Config defaults (used if 'defaults' block is absent from YAML)
DEFAULT_STALENESS_MINUTES = 15
DEFAULT_DEBOUNCE_SECONDS = 30
DEFAULT_THRESHOLD_PROFILE = "default"

# Aggregation strategy names
AGGREGATION_SINGLE = "single"
AGGREGATION_AVERAGE = "average"
AGGREGATION_MEDIAN = "median"
AGGREGATION_MIN = "min"
AGGREGATION_MAX = "max"
AGGREGATION_WEIGHTED_AVERAGE = "weighted_average"
AGGREGATION_PRIMARY_WITH_FALLBACK = "primary_with_fallback"

# Supported measurement types
MEASUREMENT_TEMPERATURE = "temperature"
MEASUREMENT_TEMPERATURE_F = "temperature_f"
MEASUREMENT_TEMPERATURE_C = "temperature_c"
MEASUREMENT_HUMIDITY = "humidity"
MEASUREMENT_PM25 = "pm25"
MEASUREMENT_PM10 = "pm10"
MEASUREMENT_CO2 = "co2"
MEASUREMENT_VOC = "voc"
MEASUREMENT_NO2 = "no2"
MEASUREMENT_O3 = "o3"
MEASUREMENT_RADON = "radon"

# Measurement type → (device_class, unit) — populated in sensor.py to avoid
# importing HA constants here (keeps const.py importable outside HA context).
MEASUREMENT_TYPES = {
    MEASUREMENT_TEMPERATURE,
    MEASUREMENT_TEMPERATURE_F,
    MEASUREMENT_TEMPERATURE_C,
    MEASUREMENT_HUMIDITY,
    MEASUREMENT_PM25,
    MEASUREMENT_PM10,
    MEASUREMENT_CO2,
    MEASUREMENT_VOC,
    MEASUREMENT_NO2,
    MEASUREMENT_O3,
    MEASUREMENT_RADON,
}

# Health state strings
HEALTH_GOOD = "good"
HEALTH_FAIR = "fair"
HEALTH_POOR = "poor"
HEALTH_UNHEALTHY = "unhealthy"
HEALTH_HAZARDOUS = "hazardous"
HEALTH_STALE = "stale"
HEALTH_UNAVAILABLE = "unavailable"

HEALTH_STATES = [
    HEALTH_GOOD,
    HEALTH_FAIR,
    HEALTH_POOR,
    HEALTH_UNHEALTHY,
    HEALTH_HAZARDOUS,
    HEALTH_STALE,
    HEALTH_UNAVAILABLE,
]

# Coordinator data key for storage in hass.data
COORDINATOR_KEY = "coordinator"
