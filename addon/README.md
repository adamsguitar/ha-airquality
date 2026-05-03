# Air Quality UI

A web UI for editing the `/config/airquality.yaml` configuration file consumed by the [Air Quality integration](https://github.com/adamsguitar/ha-airquality).

## What it does

- **Overview** — see all configured spaces and slots at a glance
- **Discover** — scan HA's registries for air-quality sensors and propose a configuration
- **Diff preview** — see exactly what's changing before you save
- **Edit YAML** — raw editor with schema validation
- **Reload** — automatically calls `airquality.reload` after every save

The integration is fully usable without this add-on — the YAML can be hand-edited via SSH, the file editor, or Studio Code Server. This add-on is just a friendlier path for the same work.

## Requirements

- The [Air Quality integration](https://github.com/adamsguitar/ha-airquality) installed and configured
- Home Assistant 2025.1 or newer

## Installation

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add `https://github.com/adamsguitar/ha-airquality`
3. Find **Air Quality UI** in the store and click **Install**
4. Start the add-on and click **Open Web UI**

## Configuration

No add-on configuration is required. The add-on reads and writes `/config/airquality.yaml` directly.

## Permissions

This add-on requests:
- `homeassistant_api: true` — to call `airquality.discover` and `airquality.reload`
- `map: config:rw` — to read and write `/config/airquality.yaml`
- `ingress: true` — to be served behind HA's authenticated ingress

## Development

The add-on is a FastAPI app served via Uvicorn. Templates use Jinja2 + HTMX. YAML round-tripping uses ruamel.yaml to preserve comments and formatting.

To build locally:

```bash
cd addon
docker build -t airquality_ui --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 .
```
