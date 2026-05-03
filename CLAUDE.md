# CLAUDE.md

This file points Claude Code (and Claude Agent SDK) at the project's working contract.

**See [AGENTS.md](./AGENTS.md) for the full guide.** It covers:

- Architecture invariants (YAML as source of truth, area binding, schema sync, push-based coordinator, etc.)
- Repository layout
- Code conventions (Python, YAML/JSON, translations, add-on imports)
- Testing setup (`pytest-homeassistant-custom-component` quirks, pythonpath)
- CI and release flow
- Common gotchas with concrete fixes (manifest fields, namespace packages, single-quoted placeholders, etc.)

AGENTS.md is the source of truth — keep it updated as the project evolves. This file exists only to point here from clients that look for `CLAUDE.md` specifically.
