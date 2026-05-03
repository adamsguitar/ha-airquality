# Changelog

All notable changes to this project are documented here. Versions follow [SemVer](https://semver.org/).

## [0.5.0] — Phase 5: polish

- Added `diagnostics.py` — full JSON snapshot (config + coordinator state + source entity states) downloadable from the integration's overflow menu
- Added `system_health.py` — summary on Settings → System → System Information
- Coordinator now syncs the issue registry on every update with three repair issues: `slot_unavailable`, `slot_stale`, `missing_profile`. Issues are created when detected and deleted when resolved
- Translation keys added for all repair issue titles and descriptions
- README expanded with a full configuration reference, automation examples, and troubleshooting section

## [0.4.0] — Phase 4: add-on

- New `addon/` directory containing the Air Quality UI add-on (FastAPI + HTMX + Jinja2)
- Add-on features: configuration overview, raw YAML editor with validation, discovery wizard with unified diff preview, "Apply proposal & reload" action
- ruamel.yaml round-tripping preserves comments and formatting
- `repository.yaml` enables installation from the same GitHub repo URL via the Add-on Store
- `scripts/sync_schema.py` now syncs the schema to both `custom_components/airquality/schema/` and `addon/schema/`

## [0.3.0] — Phase 3: discovery

- New `discovery.py` module: classifies sensor entities by `device_class` and unit, resolves area via entity → device fallback, filters disabled/hidden/stale
- New `airquality.discover` service with `SupportsResponse.ONLY`, returns proposed YAML and a summary including skipped entities with reasons
- Optional `write_to_file: true` writes proposal to `/config/airquality.yaml.proposed`
- VOC handling: accepts ppb (`volatile_organic_compounds_parts`), explicitly skips µg/m³ with a clear reason
- Tests cover all classification paths, area resolution, stale filtering

## [0.2.0] — Phase 2: health and rollups

- All aggregation strategies wired (`single`, `average`, `median`, `min`, `max`, `weighted_average`, `primary_with_fallback`)
- Threshold profile inheritance via `extends:` (single inheritance, resolved at load)
- Per-slot health evaluation: simple-threshold (pollutants) vs range-threshold (comfort) routing
- Worst-state rollup at slot → space → floor → home using HA's area registry `floor_id`
- Stale/unavailable inputs excluded from rollup unless all inputs share that state
- New entity types: per-slot health (enum), per-space composite, per-floor composite, whole-home composite
- Binary sensor platform: per-slot (opt-in), per-space, per-floor, home (`device_class: problem`)

## [0.1.0] — Phase 1: scaffold

- HACS-compatible repository structure with `manifest.json`, `hacs.json`, brand assets
- YAML loader with JSON Schema validation against `shared/schema/`
- Single-instance config flow with fixed YAML path at `/config/airquality.yaml`
- DataUpdateCoordinator subscribes to source entity state changes (push-based, debounced)
- Per-slot value sensor with correct `device_class`, `unit_of_measurement`, `state_class`
- Services: `reload`, `recompute`, `set_threshold_profile`
- CI workflows: hassfest, HACS validation, schema-sync check, unit tests
- Devcontainer using `ghcr.io/ludeeus/devcontainer/integration:stable`
