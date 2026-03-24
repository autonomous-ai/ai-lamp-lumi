# Multi-IDE Development

This project is developed with **Cursor** and **Claude Code** (multi-IDE). Changes made in one IDE should work correctly in the other.

## Conventions When Making Changes

1. **Update docs** — When code changes, update the relevant files in `docs/`:
   - `lamp-server_vi.md`, `led-control_vi.md`, `setup-flow_vi.md`, `web-ui_vi.md`, `overview_vi.md`, `bootstrap-server_vi.md`, `mqtt_vi.md`
   - Keep numbers, flows, endpoints, and states accurate

2. **Comment in English** — Per project rule

3. **Wire/DI** — After changing provider signatures, run `make generate` to regenerate `wire_gen.go`

4. **Config/version** — Do not commit binary artifacts; version is injected via ldflags at build time

## IDE-Specific Context

| IDE | Context file |
|-----|--------------|
| **Claude Code** | `CLAUDE.md` — project overview, build, architecture |
| **Cursor** | `.cursor/rules/` — rules including docs-on-code-change, architecture, testing |

## Single Source of Truth

- Code is the source of truth; docs must reflect it
- Both IDEs should read `docs/` for architecture and flow details
- If you add a significant feature, add or update the corresponding `docs/*_vi.md`
