# Air Quality Add-on (Phase 4)

This directory will contain the optional Home Assistant add-on that provides a
web UI for editing `/config/airquality.yaml`.

**Planned stack:** FastAPI + HTMX + Jinja2, served via HA ingress.

**Features (planned):**
- View and edit spaces, slots, and threshold profiles
- Discovery wizard (reads HA area/device/entity registries)
- Diff preview before saving
- Calls `airquality.reload` after successful save

The integration is fully functional without this add-on — YAML can be edited by hand.
