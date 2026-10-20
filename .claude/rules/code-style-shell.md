---
paths:
  - "**/*.sh"
  - "**/*.bash"
  - "**/*.zsh"
---

# Shell Script Rules

- Shebang: use `#! /bin/bash`. Use `#!/bin/sh` only when the script genuinely needs to run under a POSIX `sh` shell, not bash.

- Start every standalone script with `set -euo pipefail` right after the shebang:

```bash
#! /bin/bash
set -euo pipefail
```

Do not set `set -euo pipefail` in a file that another script **sources** into its own shell. An example is a shared helper or library. The `source` command runs in the caller's shell. `set -e` in a sourced file would also silently change the calling script's own error-handling behaviour.

- Wrap a script's logic in functions in almost every case. Add a guard before the call that runs the script. The guard checks whether the script runs directly, not as a sourced file:

```bash
main() {
  ...
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
```

This keeps every function sourceable and independently testable. A test script can `source` the file without triggering `main`. Another script that wants to reuse one function can also `source` the file without triggering `main`. This removes the need for a separate entry-point file. The guarded block at the bottom is the only code in the file that always runs.

- Variable naming uses two tiers. Split file-level config from working state in this way:
  - Use `UPPER_SNAKE_CASE` for file-level constants and argv-derived config. Read these once near the top of the script. Examples are paths, urls, and flags.
  - Use `lower_snake_case` for working variables inside a function. Always declare these variables with `local`.

```bash
notLikeThis() {
  STAGING_DIR="$(mktemp -d)"
}

ratherLikeThis() {
  local staging_dir
  staging_dir="$(mktemp -d)"
}
```

- Always double-quote variable expansions. Prefer the `${var}` brace form when the expansion sits directly next to other text. This makes clear where the variable name ends. A variable standing alone does not need the braces:

```bash
# notLikeThis
rm -rf $STAGING_DIR/$package_name

# ratherLikeThis
rm -rf "${STAGING_DIR}/${package_name}"

# sometimesLikeThis
rm -f "$package_name"
```

Braces are always required for a parameter expansion operator. This rule applies regardless of adjacency. Examples are a default value and a prefix or suffix strip:

```bash
STABILITY="${STABILITY:-test}"
code="${pair%%:*}"
```

- Function style: use `name() {`. Do not use `function name() {}`. Put the opening brace on the same line as the function name.

- Do not use single-character variable names.

- Prefer a guard clause over a nested branch. Check the failure condition first. Then run `continue`, `return`, or `exit`. Do not wrap the success path in a branch.

```bash
if [[ -f "$dest_path" ]]; then
  echo "File already exists: $filename, skipping."
  continue
fi

if ! wget --spider "$file_url" 2>/dev/null; then
  echo "ERROR: $filename not found at $file_url" >&2
  download_failed=1
  continue
fi

if ! wget -O "$dest_path" "$file_url"; then
  echo "ERROR: Failed to download $filename from $file_url" >&2
  download_failed=1
fi
```

- Keep function formatting consistent within one file. Do not write one function as a single line when the rest of the file's functions are multi-line.

- Do not shadow an existing shell or bash command name with a function or variable name, for example a function or variable named `log`.

- When a script prompts a user for input, show an example of a valid value in the prompt text.

- Use the `install` command instead of `cp` when a copied file needs a specific owner, group, or permission mode.

```bash
install -D -o root -g root -m 0644 "${src_path}" "${dest_path}"
```

- Split a long command's flags across multiple lines, one flag per line, with a trailing backslash, instead of one long line:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "${work_dir}:/work" \
  "${TOOLS_IMAGE}" \
  -i "/work/${input_name}"
```

- Add a blank line between unrelated commands to make a script easier to read.

- Give each piece of state its own, distinctly named variable. Do not reuse one variable for two different values.

- Return with a nonzero status on a failure path.

- Single-quote a literal string that must not undergo shell expansion, such as a password or a string containing `$` or backticks.

- Do not send echoed output from a systemd-managed script to a custom log file. Journalctl already captures it.

- Put real logic in a script, not in a shell alias.

- Do not copy a script to make a near-identical variant, such as a copy operation and a move operation. Parametrize one script with an argument instead.

- Add `-y` to a non-interactive `apt install` command. This stops the script from waiting at a prompt.

- Write an error message that states what is missing and why it matters. Do not write a bare one-line message.

- Extract a hardcoded URL, path, or filename into a named variable at the top of the script. Do not inline the literal value.

- Name a variable for what it does. Do not reuse a near-miss name that could be confused with a different existing variable.

- Prefer a complete `if` block over a `condition && command` or `condition || command` one-liner used for control flow:

```bash
# notLikeThis
[[ -f "${configPath}" ]] && rm "${configPath}"

# ratherLikeThis
if [[ -f "${configPath}" ]]; then
  rm "${configPath}"
fi
```

A one-liner hides the command's own exit status inside the `&&`/`||` chain. Under `set -e` in particular, a failing right-hand command can behave differently than it would inside an `if` block. A reader can easily misread the one-liner as meaning "run this if that." The one-liner actually means "run this, and the whole line's status depends on both commands."

- Indent with two spaces.

- Argument parsing:
  - For a script with one or two fixed, caller-controlled arguments, use plain positional parameters, for example `REPO=$1` and `TAG=$2`.
  - For a script with `--flag`-style options, use a manual `while [[ $# -gt 0 ]]; do case "$1" in ... esac; shift; done` loop. This loop must support both `--flag value` and `--flag=value`. Do not use `getopts`.

```bash
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stability)
      stability="$2"
      shift 2
      ;;
    --stability=*)
      stability="${1#*=}"
      shift
      ;;
    *)
      printf 'error: unknown argument %s\n' "$1" >&2
      exit 1
      ;;
  esac
done
```

- Do not write banner or section comments, for example `# ---- helpers ----`. Let function names and code structure carry that meaning instead. If a script already has these comments, leave them in place when your change does not touch that section. If you actively refactor or improve that file, ask the user before you remove them.

- Use `trap ... EXIT` for cleanup whenever a script creates a temp file or directory. This removes it even on an early `exit` or an error:

```bash
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
```

- To source a sibling script, resolve the current script's own directory first. Do not assume the caller's `cwd`:

```bash
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=SCRIPT_DIR/other.sh
source "${SCRIPT_DIR}/other.sh"
```

A hardcoded absolute path is fine once a script is actually installed to a fixed system location. This case differs from a repo-relative sibling import. In both cases, add a `# shellcheck source=` hint above the `source` line. Run `shellcheck` on every script. CI runs it too.

- Avoid an unnecessary `cd`. Pass the target path directly to the command instead, for example `unzip "${dir}/file.zip" -d "${dir}"` rather than `cd "${dir}" && unzip file.zip`. This also avoids a failure mode. If the `cd` command fails, a script can silently end up in the wrong directory.

- Files end with exactly one trailing newline.
