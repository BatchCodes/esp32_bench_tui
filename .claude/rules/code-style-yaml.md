---
paths:
  - "**/*.yaml"
  - "**/*.yml"
---

# YAML Rules

## `.github/**` — GitHub Actions workflow YAML

- Use double-quoted strings, for example `default: "main"`.
- Follow the GitHub Actions schema order for keys: `name`, `on`, `permissions`, `jobs`. Key order is not alphabetical.
- Give each workflow the smallest `permissions` block that it needs.
- Pin third-party actions to a major version tag, for example `actions/checkout@v4`.
- Add `if: always()` to a step that must run even when an earlier step in the job fails.
- Name a job ID or an output key in snake_case, for example `build_firmware`.

## Board profiles and project configuration files

- Indent with 2 spaces.
- Use snake_case keys. The keys match the Python dataclass field names in `host/bench/config.py`.
- Name a board profile file after its `name` key, for example `boards/olimex_esp32_poe_iso.yaml`.
- Name the source of each pin fact in a board profile, for example the datasheet or the schematic, in the `sources` list.
- Write GPIO numbers as integers, not strings.
- Keep `docs/board_profiles.md` and `docs/project_config.md` in sync with the loader. Update them in the same change.
- Do not use YAML anchors or aliases.
- End every YAML file with exactly one trailing newline.
