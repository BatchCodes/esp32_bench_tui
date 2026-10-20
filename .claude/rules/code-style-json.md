---
paths:
  - "**/*.json"
---

# JSON Rules

Most JSON files in this repo are configuration files, for example `cspell.json`, `.prettierrc.json` and `.devcontainer/devcontainer.json`. Prettier controls their layout.

- Add a new word to the `words` list in `cspell.json` in alphabetical order. Add only words that are spelled correctly, such as product names and technical terms.
- Use snake_case for keys in the wire protocol messages, to match the Python field names. Refer to `docs/protocol.md`.
- Use camelCase for keys in a hand-authored JSON configuration file, unless the tool that reads the file sets the key names.
- End every JSON file with exactly one trailing newline.
