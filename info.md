# Air Quality

A sensor-agnostic air quality monitoring framework for Home Assistant.

## What it does

- Binds existing HA sensor entities to **spaces** (rooms/areas)
- Aggregates multiple sensors per measurement (average, median, min/max, weighted, etc.)
- Exposes clean per-slot sensor entities with correct `device_class` and units
- Reports slot, space, floor, and whole-home health (Phase 2)
- Fully configurable via `/config/airquality.yaml` — no UI required

## Supported measurements

Temperature · Humidity · PM2.5 · PM10 · CO₂ · VOC · NO₂ · O₃ · Radon

## Quick start

1. Install via HACS (custom repository: `https://github.com/adamsguitar/ha-airquality`)
2. Add the integration in **Settings → Devices & Services**
3. Edit `/config/airquality.yaml` (an example is created automatically)
4. Call `airquality.reload` to apply changes

See the [README](https://github.com/adamsguitar/ha-airquality) for the full configuration reference.
