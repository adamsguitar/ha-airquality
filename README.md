# ha-airquality

[![HACS Custom][hacs-badge]][hacs-url]
[![GitHub Release][release-badge]][release-url]
[![hassfest][hassfest-badge]][hassfest-url]

A sensor-agnostic air quality monitoring and management framework for Home Assistant.

## Features

- **Sensor-agnostic** — works with any HA sensor entity regardless of manufacturer
- **Room-oriented** — every space is bound to a HA area; no floating spaces
- **Aggregation** — combine multiple sensors per measurement (average, median, min/max, weighted, primary-with-fallback)
- **Health bands** — good / fair / poor / unhealthy / hazardous per slot, space, floor, and home (Phase 2)
- **YAML-first** — declarative config, version-control friendly, optional web UI (Phase 4)
- **HACS-installable** — add as a custom repository and install in one click

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations** → ⋮ menu → **Custom repositories**
2. Add `https://github.com/adamsguitar/ha-airquality` as an **Integration**
3. Search for "Air Quality" and install
4. Restart Home Assistant

### Manual

Copy `custom_components/airquality/` into your HA `config/custom_components/` directory and restart.

## Configuration

After installation, go to **Settings → Devices & Services → Add Integration → Air Quality**.

The integration reads `/config/airquality.yaml`. An example file is created automatically on first run.

### Example `airquality.yaml`

```yaml
airquality:
  defaults:
    staleness_minutes: 15
    debounce_seconds: 30
    threshold_profile: default

  threshold_profiles:
    default:
      pm25:          { good: 12,  fair: 35,   poor: 55,   unhealthy: 150 }
      co2:           { good: 800, fair: 1000,  poor: 1500, unhealthy: 2500 }
      humidity:      { good_min: 30, good_max: 60, fair_min: 25, fair_max: 65 }
      temperature_f: { good_min: 68, good_max: 76, fair_min: 65, fair_max: 80 }

    kids_room:
      extends: default
      pm25: { good: 9, fair: 25, poor: 45, unhealthy: 100 }

  spaces:
    - area: living_room
      slots:
        - measurement: co2
          aggregation: single
          entities:
            - sensor.living_room_co2
        - measurement: pm25
          aggregation: average
          entities:
            - sensor.living_room_pm25_a
            - sensor.living_room_pm25_b

    - area: kids_bedroom
      threshold_profile: kids_room
      slots:
        - measurement: co2
          aggregation: single
          entities:
            - sensor.kids_co2
```

### Applying changes

Call `airquality.reload` from **Developer Tools → Services** or an automation — no HA restart needed.

## Services

| Service | Description |
|---|---|
| `airquality.reload` | Reload `/config/airquality.yaml` |
| `airquality.recompute` | Force recomputation of all slot values |
| `airquality.set_threshold_profile` | Temporarily override a space's threshold profile (runtime only) |
| `airquality.discover` | Scan HA registries and propose a YAML configuration (returns response data; does not modify the active config). Use `write_to_file: true` to also write to `/config/airquality.yaml.proposed`. |

## Supported measurements

| Key | Device class | Unit |
|---|---|---|
| `temperature` / `temperature_f` | `temperature` | °F |
| `temperature_c` | `temperature` | °C |
| `humidity` | `humidity` | % |
| `pm25` | `pm25` | µg/m³ |
| `pm10` | `pm10` | µg/m³ |
| `co2` | `carbon_dioxide` | ppm |
| `voc` | `volatile_organic_compounds_parts` | ppb |
| `no2` | `nitrogen_dioxide` | µg/m³ |
| `o3` | `ozone` | µg/m³ |
| `radon` | — | Bq/m³ |

## Aggregation strategies

| Strategy | Behaviour |
|---|---|
| `single` | First entity in the list |
| `average` | Arithmetic mean |
| `median` | Median value |
| `min` / `max` | Minimum / maximum |
| `weighted_average` | Weighted mean (provide `weights:` map) |
| `primary_with_fallback` | First non-stale, non-unavailable entity (list order = priority) |

Stale and unavailable entities are excluded from aggregation before the strategy is applied.

## Roadmap

- **Phase 1** ✅ — Repo scaffold, YAML loading, single-strategy slot sensors, HACS/CI
- **Phase 2** ✅ — All aggregation strategies, threshold profiles with inheritance, health rollup (slot/space/floor/home), composite entities, problem binary sensors
- **Phase 3** ✅ — Auto-discovery wizard via `airquality.discover` service (reads HA area/device/entity registries, classifies sensors, generates YAML)
- **Phase 4** — Optional web UI add-on (FastAPI + HTMX, ingress, discovery wizard)
- **Phase 5** — Diagnostics, repairs, system health card, full docs

## Development

```bash
# Open in VS Code with the devcontainer
code .
# F1 → "Dev Containers: Reopen in Container"
# Home Assistant starts at http://localhost:8123
```

The devcontainer mounts this repo as a custom component and boots a real HA instance.

## License

MIT

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://hacs.xyz
[release-badge]: https://img.shields.io/github/release/adamsguitar/ha-airquality.svg
[release-url]: https://github.com/adamsguitar/ha-airquality/releases
[hassfest-badge]: https://github.com/adamsguitar/ha-airquality/actions/workflows/validate.yml/badge.svg
[hassfest-url]: https://github.com/adamsguitar/ha-airquality/actions/workflows/validate.yml
