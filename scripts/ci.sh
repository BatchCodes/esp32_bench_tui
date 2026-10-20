#! /bin/bash
# The CI commands. GitHub Actions runs the firmware commands in the espressif/idf
# image. Locally, the firmware commands use idf.py from the shell, or Docker.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
APP_DIR="${REPO_DIR}/firmware/bench_agent"
PYTHON_TESTS_DIR="${REPO_DIR}/tests/host_python"
VENV_PYTHON="${REPO_DIR}/.venv/bin/python"
FIRMWARE_TARGETS=(esp32 esp32s3 esp32c3 esp32c6)

usage() {
  cat <<USAGE
Usage: scripts/ci.sh COMMAND

Commands:
  python-tests     Run the Python unit tests for the host tool.
  host-tests       Build and run the firmware host tests.
  build TARGET [VARIANT]
                   Build the bench agent for TARGET (${FIRMWARE_TARGETS[*]}).
                   VARIANT adds firmware/bench_agent/sdkconfig.ci.VARIANT.
  lint             Run shellcheck on the scripts, if shellcheck is installed.
  all              Run every command above, for every target.
USAGE
}

python_command() {
  if [[ -x "${VENV_PYTHON}" ]]; then
    printf '%s\n' "${VENV_PYTHON}"
    return 0
  fi

  printf 'python3\n'
}

run_python_tests() {
  local python
  python="$(python_command)"

  if ! "${python}" -c "import serial, textual, yaml" &>/dev/null && command -v docker &>/dev/null; then
    printf 'Python packages are missing. Running the Python tests in Docker.\n'
    "${SCRIPT_DIR}/bench_docker.sh" --test
    return
  fi

  "${python}" -m unittest discover -s "${PYTHON_TESTS_DIR}" -t "${REPO_DIR}"
}

run_host_tests() {
  "${SCRIPT_DIR}/run_host_tests.sh"
}

build_target() {
  local target="$1"
  local variant="${2:-}"
  local build_dir="build_ci_${target}"
  local defaults="sdkconfig.defaults"

  if [[ -n "${variant}" ]]; then
    if [[ ! -f "${APP_DIR}/sdkconfig.ci.${variant}" ]]; then
      printf 'error: firmware/bench_agent/sdkconfig.ci.%s does not exist.\n' "${variant}" >&2
      return 1
    fi
    build_dir="${build_dir}_${variant}"
    defaults="sdkconfig.defaults;sdkconfig.ci.${variant}"
  fi

  printf '\n=== Building firmware/bench_agent for %s %s ===\n' "${target}" "${variant:-(default)}"

  if command -v idf.py &>/dev/null; then
    idf.py \
      -C "${APP_DIR}" \
      -B "${APP_DIR}/${build_dir}" \
      -D "SDKCONFIG=${APP_DIR}/${build_dir}/sdkconfig" \
      -D "SDKCONFIG_DEFAULTS=${defaults}" \
      -D "IDF_TARGET=${target}" \
      build
    return
  fi

  "${SCRIPT_DIR}/idf_docker.sh" \
    "${APP_DIR}" \
    -B "${build_dir}" \
    -D "SDKCONFIG=${build_dir}/sdkconfig" \
    -D "SDKCONFIG_DEFAULTS=${defaults}" \
    -D "IDF_TARGET=${target}" \
    build
}

run_lint() {
  if ! command -v shellcheck &>/dev/null; then
    printf 'shellcheck is not installed. Skipping the shell lint.\n'
    return 0
  fi

  shellcheck "${SCRIPT_DIR}"/*.sh "${REPO_DIR}/bench"
}

run_all() {
  local target

  run_lint
  run_python_tests
  run_host_tests

  for target in "${FIRMWARE_TARGETS[@]}"; do
    build_target "${target}"
  done

  build_target esp32s3 usb_serial_jtag
}

main() {
  local command="${1:-all}"

  case "${command}" in
    python-tests)
      run_python_tests
      ;;
    host-tests)
      run_host_tests
      ;;
    build)
      if [[ $# -lt 2 ]]; then
        usage >&2
        return 1
      fi
      build_target "$2" "${3:-}"
      ;;
    lint)
      run_lint
      ;;
    all)
      run_all
      ;;
    -h | --help)
      usage
      ;;
    *)
      usage >&2
      return 1
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
