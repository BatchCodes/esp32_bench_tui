#! /bin/bash
# Build the Python bundle of the web TUI pages (/tui/ and /simulator/): the
# host package, the board profiles and the examples in one zip file, the
# pinned wheels from web/requirements.txt and bundle.json, which lists them.
# web/app/bench.js loads the bundle. scripts/build_site.sh calls this script,
# and so do the Node tests in tests/web. Refer to docs/web_tui.md.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
REQUIREMENTS="${REPO_DIR}/web/requirements.txt"
VENV_PYTHON="${REPO_DIR}/.venv/bin/python"
HOST_ARCHIVE="bench_host.zip"
WHEELS_DIR_NAME="wheels"
# The Python version of the Pyodide release in web/app/bench.js.
PYODIDE_PYTHON_VERSION="3.14"
BUNDLE_PATHS=(host/bench boards examples)

usage() {
  cat <<USAGE
Usage: scripts/build_web_bundle.sh OUT_DIR

Write ${HOST_ARCHIVE}, ${WHEELS_DIR_NAME}/ and bundle.json to OUT_DIR, for example site/app.
USAGE
}

python_command() {
  if [[ -x "${VENV_PYTHON}" ]]; then
    printf '%s\n' "${VENV_PYTHON}"
    return 0
  fi

  printf 'python3\n'
}

bundle_version() {
  git -C "${REPO_DIR}" describe --tags --always --dirty 2>/dev/null || printf 'unknown\n'
}

write_host_archive() {
  local python="$1"
  local archive="$2"

  # Tracked files and new files that git does not ignore, so that a local
  # build includes work that is not committed yet.
  git -C "${REPO_DIR}" ls-files --cached --others --exclude-standard -- "${BUNDLE_PATHS[@]}" |
    "${python}" -c '
import sys
import zipfile
from pathlib import Path

repo, archive = Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for name in sorted(line.strip() for line in sys.stdin):
        path = repo / name
        if name and "__pycache__" not in name and path.is_file():
            bundle.write(path, name)
' "${REPO_DIR}" "${archive}"
}

download_wheels() {
  local python="$1"
  local wheels_dir="$2"

  if ! "${python}" -m pip --version &>/dev/null; then
    printf 'error: %s has no pip. pip downloads the wheels in %s. Create the virtual environment from CONTRIBUTING.md.\n' \
      "${python}" "${REQUIREMENTS}" >&2
    return 1
  fi

  "${python}" -m pip download \
    --quiet \
    --no-deps \
    --only-binary=:all: \
    --python-version "${PYODIDE_PYTHON_VERSION}" \
    --implementation py \
    --abi none \
    --platform any \
    --requirement "${REQUIREMENTS}" \
    --dest "${wheels_dir}"
}

write_bundle_json() {
  local out_dir="$1"
  local python="$2"

  # Only the wheels that the requirements name, so that a wheel left over
  # from an older build is not installed too.
  "${python}" -c '
import json
import re
import sys
from pathlib import Path

out_dir, version, archive, wheels, requirements = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5])
files = {path.name for path in (out_dir / wheels).glob("*.whl")}
packages = []
for line in requirements.read_text().splitlines():
    line = line.split("#")[0].strip()
    if not line:
        continue
    name, wanted = line.split("==")
    prefix = re.sub(r"[-_.]+", "_", name.strip()).lower() + "-" + wanted.strip() + "-"
    found = [file_name for file_name in files if file_name.lower().startswith(prefix)]
    if len(found) != 1:
        sys.exit(f"error: found {len(found)} wheels for {line} in {out_dir / wheels}")
    packages.append(f"{wheels}/{found[0]}")
bundle = {"version": version, "host_archive": archive, "packages": sorted(packages)}
(out_dir / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")
' "${out_dir}" "$(bundle_version)" "${HOST_ARCHIVE}" "${WHEELS_DIR_NAME}" "${REQUIREMENTS}"
}

main() {
  local out_dir="${1:-}"
  local python

  if [[ -z "${out_dir}" || "${out_dir}" == "-h" || "${out_dir}" == "--help" ]]; then
    usage
    if [[ -z "${out_dir}" ]]; then
      return 1
    fi
    return 0
  fi

  python="$(python_command)"
  mkdir -p "${out_dir}/${WHEELS_DIR_NAME}"

  write_host_archive "${python}" "${out_dir}/${HOST_ARCHIVE}"
  download_wheels "${python}" "${out_dir}/${WHEELS_DIR_NAME}"
  write_bundle_json "${out_dir}" "${python}"

  printf 'Wrote the web TUI bundle to %s (%s wheels).\n' \
    "${out_dir}" "$(find "${out_dir}/${WHEELS_DIR_NAME}" -name '*.whl' | wc -l)"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
