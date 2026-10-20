#! /bin/bash
# Install the host tool dependencies from Debian packages, or into a virtual
# environment in .venv when apt is not available or --venv is given.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
VENV_DIR="${REPO_DIR}/.venv"
APT_PACKAGES=(python3 python3-serial python3-yaml python3-textual)

usage() {
  cat <<USAGE
Usage: scripts/install.sh [--venv]

Install the host tool dependencies (pyserial, PyYAML, textual).

Options:
  --venv       Install into ${VENV_DIR} with pip, not from Debian packages.
  -h, --help   Show this help.

The script also adds you to the dialout group, so you can open the serial port.
To build the firmware, install Docker, or install ESP-IDF natively at the version
in scripts/esp_idf_version.txt.
USAGE
}

install_apt_packages() {
  sudo apt-get update
  sudo apt-get install -y "${APT_PACKAGES[@]}"
}

install_venv() {
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip
  "${VENV_DIR}/bin/pip" install -e "${REPO_DIR}"
}

add_dialout_group() {
  if id -nG "${USER}" | grep -qw dialout; then
    return 0
  fi

  sudo usermod -aG dialout "${USER}"
  printf 'You are now in the dialout group. Log out and log in again before you open a serial port.\n'
}

main() {
  local use_venv="no"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --venv)
        use_venv="yes"
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      *)
        printf 'error: unknown argument %s\n' "$1" >&2
        usage >&2
        return 1
        ;;
    esac
  done

  if [[ "${use_venv}" == "no" ]] && ! command -v apt-get &>/dev/null; then
    printf 'apt-get not found. Installing into %s instead.\n' "${VENV_DIR}"
    use_venv="yes"
  fi

  if [[ "${use_venv}" == "yes" ]]; then
    install_venv
  else
    install_apt_packages
  fi

  add_dialout_group

  if ! command -v docker &>/dev/null && ! command -v idf.py &>/dev/null; then
    printf 'Note: neither Docker nor ESP-IDF is installed. You need one of them to build the firmware.\n'
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
