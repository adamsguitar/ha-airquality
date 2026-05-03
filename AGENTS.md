# AGENTS.md

Guidelines for AI agents (Claude Code, Cursor, Aider, etc.) working in this repo. Human contributors should also read this — it's the project's working contract.

## Project overview

`ha-airquality` is two coupled components in one repo:

- **Custom HA integration** at `custom_components/airquality/` — the runtime workhorse. Reads `/config/airquality.yaml`, creates one device per configured room (bound to its HA area), exposes a value sensor per measurement (with the per-measurement health as an attribute), one composite "Overall" sensor per room with an `unhealthy_reasons` attribute, one problem binary sensor per device, and rolls up to floor/home.
- **Optional HA add-on** at `addon/` — FastAPI web UI organised around HA areas. Add/remove measurement slots and sensors per room from drop-downs; every action persists to YAML and reloads the integration. There is no raw YAML editor in the UI — power users edit `/config/airquality.yaml` directly on disk.

They communicate only through the YAML file and HA services (`airquality.discover`, `airquality.reload`). The add-on is genuinely optional.

The repo doubles as a HACS custom-repository (for the integration) and a HA add-on store (for the add-on). Both are installed by adding the same GitHub URL.

## Architecture invariants

These are load-bearing. Don't break them without explicit user approval.

1. **YAML is the single source of truth.** Fixed path: `/config/airquality.yaml`. No dual UI/YAML config storage. The add-on edits the YAML file directly.
2. **Every space binds to an HA `area_id`.** Validated at config load against the HA area registry. Bad area_id → `ConfigEntryError`. No floating spaces. Each room's device is also explicitly bound to that area_id via the device registry after platform setup, so the binding survives upgrades that may have lost the link.
3. **JSON Schema is the single source of truth for config shape.** Lives at `shared/schema/airquality.schema.json`. Synced into the integration and add-on by `scripts/sync_schema.py`. CI checks they're in sync.
4. **Push-based coordinator, not polling.** Subscribes to source-entity state changes via `async_track_state_change_event` and debounces via `homeassistant.helpers.debounce.Debouncer`. No `update_interval` on the `DataUpdateCoordinator`.
5. **Aggregation is a closed enum.** `single`, `average`, `median`, `min`, `max`, `weighted_average`, `primary_with_fallback`. No expression eval, no Jinja templates.
6. **Worst-state rollup excludes stale/unavailable inputs unless all share that state.** A dead sensor must not cascade to home health.
7. **Threshold profile inheritance is single, eager.** Resolved at config load into flat profiles. No multi-level chains.
8. **Single-instance config flow.** One config entry per HA install (`async_set_unique_id(DOMAIN)`).
9. **VOC discovery only accepts `volatile_organic_compounds_parts` (ppb).** µg/m³ is skipped with a clear reason. The integration's `voc` measurement is ppb.
10. **Versions march in lockstep.** `custom_components/airquality/manifest.json` `version` must equal `addon/config.yaml` `version`.

## Repository layout

```
ha-airquality/
├── custom_components/airquality/   # The integration (no __init__.py at custom_components/)
│   ├── __init__.py                 # async_setup_entry, services
│   ├── manifest.json
│   ├── config_flow.py              # single-instance, fixed YAML path
│   ├── coordinator.py              # AirQualityCoordinator (DataUpdateCoordinator)
│   ├── yaml_loader.py              # load + JSON-schema validate + area binding
│   ├── aggregation.py              # named strategies
│   ├── health.py                   # threshold evaluation + rollup
│   ├── models.py                   # typed dataclasses
│   ├── sensor.py                   # slot, slot-health, space, floor, home sensors
│   ├── binary_sensor.py            # problem sensors (per-slot opt-in, per-space/floor/home)
│   ├── discovery.py                # registry scanning + YAML proposal
│   ├── ui_state.py                 # collects areas + candidate sensors + config for the add-on UI
│   ├── diagnostics.py              # JSON snapshot for download
│   ├── system_health.py            # System Information card
│   ├── services.yaml
│   ├── strings.json + translations/en.json (kept in sync; linter touches en.json)
│   ├── schema/airquality.schema.json   # synced from shared/, do not hand-edit
│   └── brand/icon.png              # placeholder; real brands go to home-assistant/brands
├── addon/                          # The optional add-on
│   ├── config.yaml                 # slug airquality_ui, ingress 8099, hassio_api, homeassistant_api, map config:rw
│   ├── build.yaml                  # HA python base images per arch
│   ├── Dockerfile, run.sh, icon.png
│   ├── app/                        # FastAPI app — runs as `main:app`, NOT a package
│   │   ├── main.py
│   │   ├── ha_client.py            # SUPERVISOR_TOKEN-based REST client
│   │   ├── yaml_io.py              # ruamel.yaml round-trip
│   │   ├── config_ops.py           # high-level YAML mutations (add slot/entity, etc.)
│   │   ├── schema_validator.py
│   │   └── templates/, static/
│   └── schema/                     # synced from shared/, baked into image at build
├── shared/schema/                  # SOURCE OF TRUTH for config schema
├── scripts/sync_schema.py          # copy shared/ → integration & addon
├── tests/                          # no __init__.py; uses MagicMock + patch.multiple
│   ├── conftest.py                 # tries to import PHCC fixtures, no-op if missing
│   ├── test_aggregation.py, test_health.py, test_discovery.py, test_yaml_loader.py
│   └── fixtures/
├── docs/release-notes/vX.Y.Z.md    # version-controlled release notes (used by release.yml)
├── .devcontainer/                  # ghcr.io/ludeeus/devcontainer/integration:stable
├── .github/workflows/
│   ├── validate.yml                # hassfest, HACS, schema-sync, tests
│   └── release.yml                 # tag → GitHub Release with body from docs/release-notes/
├── pyproject.toml                  # pytest config (pythonpath, asyncio_mode)
├── requirements_test.txt           # PHCC + jsonschema + PyYAML; do NOT pin pytest
├── hacs.json                       # HACS metadata (min HA version goes HERE)
├── repository.yaml                 # add-on store metadata
├── info.md, README.md, CHANGELOG.md
└── AGENTS.md, CLAUDE.md
```

## Code conventions

### Python (integration and add-on)

- Default to **no comments**. Add one only when the *why* is non-obvious — a hidden invariant, a workaround for a specific bug, behaviour that would surprise a reader. Self-explanatory code with good names doesn't need narration.
- No backwards-compatibility shims. No half-finished implementations. Delete unused code rather than commenting it out.
- Don't add error handling for scenarios that can't happen. Trust framework guarantees. Validate at boundaries (YAML load, service calls, HTTP) and not deeper.
- Type hints throughout. `from __future__ import annotations` at the top of new files.
- Dataclasses for typed config / state. See `models.py`.
- Don't use `homeassistant.exceptions.ConfigEntryError` in unit-testable modules without considering test-time HA availability.

### YAML / JSON

- Schema is in `shared/schema/airquality.schema.json`. After editing, run `python scripts/sync_schema.py` and commit all three copies. CI fails if they diverge.
- `manifest.json` field order: `domain`, `name`, then **alphabetical** (codeowners, config_flow, dependencies, documentation, integration_type, iot_class, issue_tracker, requirements, version).
- Min HA version goes in `hacs.json`, **not** `manifest.json` — `homeassistant` is not a valid manifest key and hassfest will reject it.

### Translations

- `strings.json` and `translations/en.json` must stay byte-for-byte identical for keys present in both.
- **Never put a placeholder inside single quotes** (e.g. `'{profile}'`). ICU MessageFormat reserves single quotes for escape semantics; hassfest fails translation validation for placeholders inside single quotes. Use bare `{profile}` or different punctuation.

### Add-on imports

- `addon/app/main.py` is launched as `main:app` (uvicorn) — it is **not** a Python package. Use absolute imports (`import yaml_io`, `from schema_validator import validate`), never relative (`from . import yaml_io`).

## Testing

### Running tests

```bash
pip install -r requirements_test.txt
pytest tests/ -v
```

### Conventions

- Tests use `unittest.mock.MagicMock` and `unittest.mock.patch.multiple` to stub HA registries. They do not require a running HA instance for collection.
- `pytest-homeassistant-custom-component` is installed for the `homeassistant.*` import chain (which `custom_components/airquality/__init__.py` triggers transitively). It is **not** required for individual tests to use HA fixtures; the `enable_custom_integrations` autouse fixture in `conftest.py` is wrapped in a `try/except ImportError`.
- **Do NOT add `__init__.py` to `custom_components/` or `tests/`.** `custom_components` must be a namespace package for HA's loader to discover it. `pyproject.toml` sets `pythonpath = ["."]` so `from custom_components.airquality.X` resolves.
- **Do NOT pin `pytest`** in `requirements_test.txt`. PHCC pins `pytest==8.3.x` strictly; any explicit `pytest>=8.4` causes `ResolutionImpossible`. Let PHCC pull pytest in transitively.
- `pytest-homeassistant-custom-component` uses `0.13.x` versioning, not calendar-style. Do not write `>=2025.1`.

### Test layout

- `test_aggregation.py` — pure-Python, tests strategy dispatch
- `test_health.py` — pure-Python, tests threshold evaluation and rollup including stale-cascade prevention
- `test_discovery.py` — uses `MagicMock` for entity/device/area registries
- `test_yaml_loader.py` — uses temp dirs, mocked area registry, mocked HA. Patches `custom_components.airquality.yaml_loader.ar.async_get`.

## CI

`.github/workflows/validate.yml` runs four jobs:

1. **hassfest** — `home-assistant/actions/hassfest@master`. Note: pinned to `@master`, so HA core changes upstream can break us without warning. If hassfest goes red on a previously-passing commit, suspect upstream rule changes.
2. **HACS validation** — `hacs/action@main` with `category: integration`. Also requires the **GitHub repo itself to have a description and topics set** (cannot be set in code; only via repo settings or `repos` API).
3. **Schema in-sync check** — runs `python scripts/sync_schema.py --check`. Fails if `shared/`, `custom_components/.../schema/`, and `addon/schema/` diverge.
4. **Unit tests** — `pytest tests/ -v`.

## Releases

`.github/workflows/release.yml` triggers on tags matching `v*.*.*`:

1. Verifies `manifest.json` `version` equals the tag (without the `v`).
2. Verifies `docs/release-notes/vX.Y.Z.md` exists.
3. Creates a GitHub Release using that file as the body.

To cut a release:

1. Bump `custom_components/airquality/manifest.json` `version` and `addon/config.yaml` `version` together.
2. Add `docs/release-notes/vX.Y.Z.md` describing what's in the release.
3. Commit those changes.
4. `git tag vX.Y.Z && git push origin vX.Y.Z`.

## Working with CI logs

When CI fails, read the actual log before changing anything. Never guess from job names or step names alone — the same step can fail for very different reasons. If logs aren't readable, ask whoever opened the PR to paste them.

## Common gotchas (lessons learned, do not repeat)

- `manifest.json` cannot contain `homeassistant` — only `hacs.json` can.
- `custom_components/__init__.py` must NOT exist — namespace package only.
- Don't pin `pytest` — PHCC owns the version.
- `pytest-homeassistant-custom-component` versions are `0.13.x`, not `2025.x`.
- Single-quoted placeholders in translations break hassfest.
- HACS repo-metadata checks (description, topics) live on GitHub, not in code.
- Hassfest at `@master` can change underneath us.
- The example YAML created on first install has empty `spaces`; the schema must permit `minItems: 0` (no `minItems` constraint) or first-install loads fail validation.
- Don't bump versions without also adding the matching `docs/release-notes/vX.Y.Z.md` — the release workflow refuses to ship without it.

## When making changes

1. **Read this file first.** If you're about to violate an architecture invariant, stop and ask the user.
2. **Run the relevant test file locally** before pushing where possible (the codespace can syntax-check via `python3 -c "import ast; ast.parse(open('foo.py').read())"` even without HA installed).
3. **If you change `shared/schema/`**, run `python scripts/sync_schema.py` before committing or CI's schema-sync job will fail.
4. **If you bump versions**, add the matching `docs/release-notes/` file in the same commit.
5. **Don't open a PR unless explicitly asked.** Branch pushes are sufficient.
