# Changelog

All notable changes to this project are documented here. Versions follow [SemVer](https://semver.org/).

## [0.8.2]

- Air Quality UI add-on: fix **no CSS / no threshold editor** behind Home Assistant ingress. Restored **relative** `static/style.css` and `static/profile-editor.js` URLs; `request.url_for` produced root-absolute `/static/...` paths that resolved outside the ingress prefix (404), so pages were unstyled and the band editor script never ran. Cache-busting `?v=` query is retained.

## [0.8.1]

- Air Quality UI add-on: add version query strings to CSS/JS so ingress/browser caches do not hide UI updates after upgrade; show add-on version in the footer; bake `config.yaml` into the image for reliable version reporting.

## [0.8.0]

- Air Quality UI add-on: full visual overhaul — new design tokens with light/dark theme, stronger contrast, responsive 1280px layout, and an auto-fill room/slot grid that uses wide screens.
- Threshold profile editor: single-line bands per measurement with a colored strip, draggable handles, and inputs that **physically prevent** a more-severe threshold from being set below a less-severe one.

## [0.7.9]

- Air Quality UI add-on: fix Threshold profiles page crash when rendering reference breakpoints (Jinja `dict.values` vs `values` key).

## [0.7.8]

- Air Quality UI add-on: two-column measurement grid; stronger layout hierarchy.
- Threshold profiles editable in UI (numbers + sliders, reference markers); add / duplicate profiles; save validates and materializes `extends`.

## [0.7.7]

- Managed dashboard: no separate **Measurements** title above the per-room tile grid.

## [0.7.6]

- Managed dashboard: household block moved into the sections view **header** and **badges**; measurement tile grid uses **two columns** for wider tiles.

## [0.7.5]

- Managed dashboard: **Household** header with home overall/problem badges and a markdown summary of room measurement issues from `attention_reasons`; per-room measurements use **tile** cards instead of an Entities card.

## [0.7.4]

- Dashboard sync supports Home Assistant **`LovelaceData`** (`hass.data["lovelace"]`) where dashboards live on `.dashboards` rather than `["dashboards"]`, fixing false “storage unavailable” repairs on recent core releases.

## [0.7.3]

- Dashboard **Lovelace unavailable** repairs now include **runtime diagnostics** (HA core version, `frontend`/`lovelace` in loaded components, shape of `hass.data['lovelace']`, and whether YAML load / `async_setup_component` failed).
- Fixes a routing bug where the generic repair template replaced **concrete skip reasons**, so users only saw vague profile/YAML hints even when dashboards worked in the UI.

## [0.7.2]

- Dashboard sync **loads the Lovelace integration** when `hass.data.lovelace` is missing (ordering or partial startup), before creating the managed dashboard
- Expanded repair text for **dashboard_lovelace_not_ready** (profile setting, configuration.yaml, reload)

## [0.7.1]

- Add-on fixes **ingress redirects** so POST actions stay inside the Air Quality UI instead of loading the whole Home Assistant frontend
- **`airquality.reload`** swallows coordinator refresh failures after YAML reload (logged, no supervisor 500 from the UI)
- Dashboard sync **failures**: repair issues + persistent notification once per failing layout revision; clearer logs when Lovelace is not initialized

## [0.7.0]

- Managed **Lovelace** dashboard (`airquality-dashboard`) with Core cards, `airquality.sync_dashboard` service, and visual ordering for rooms that need attention
- Central measurement display labels (integration + add-on); slot sensors use suggested `object_id` `{measurement}_{area_id}`
- Integration **icon.png** for HACS; add-on icon aligned; add-on `panel_icon` set to `mdi:weather-dust`

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
