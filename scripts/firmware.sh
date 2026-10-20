#! /bin/bash
# Build, flash and monitor the bench agent firmware for one chip target.
# Runs idf.py natively when ESP-IDF is loaded in the shell, or in Docker
# through scripts/idf_docker.sh.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
APP_DIR="${REPO_DIR}/firmware/bench_agent"
IDF_DOCKER="${SCRIPT_DIR}/idf_docker.sh"
SERIAL_BY_ID_DIR="/dev/serial/by-id"
SUPPORTED_TARGETS=(esp32 esp32s3 esp32c3 esp32c6)
DEFAULT_TARGET="esp32"

usage() {
  cat <<USAGE
Usage: scripts/firmware.sh [OPTIONS] COMMAND [PORT]

Build, flash and monitor firmware/bench_agent for one chip target.
Each target has its own build directory, firmware/bench_agent/build_<target>.

Commands:
  build      Build the firmware.
  flash      Build and flash the firmware.
  monitor    Show the serial output of the board. Press Ctrl+] to stop.
  test       Build and run the firmware host tests.
  clean      Remove the build directory of the target.

Options:
  -t, --target TARGET   Chip target: ${SUPPORTED_TARGETS[*]}. Default: ${DEFAULT_TARGET}.
  -n, --native          Use idf.py from the shell. Load ESP-IDF first.
  -d, --docker          Use Docker even if idf.py is in the shell.
  -h, --help            Show this help.

PORT is used by flash and monitor. If you do not give it, the script uses
\$BENCH_PORT, or the only device in ${SERIAL_BY_ID_DIR}.

Examples:
  scripts/firmware.sh build
  scripts/firmware.sh --target esp32s3 flash
  scripts/firmware.sh monitor /dev/ttyUSB0
USAGE
}

is_supported_target() {
  local target="$1"
  local supported

  for supported in "${SUPPORTED_TARGETS[@]}"; do
    if [[ "${supported}" == "${target}" ]]; then
      return 0
    fi
  done

  return 1
}

resolve_port() {
  local requested_port="$1"
  local -a candidates

  if [[ -n "${requested_port}" ]]; then
    printf '%s\n' "${requested_port}"
    return 0
  fi

  if [[ -n "${BENCH_PORT:-}" ]]; then
    printf '%s\n' "${BENCH_PORT}"
    return 0
  fi

  if [[ ! -d "${SERIAL_BY_ID_DIR}" ]]; then
    printf 'error: no serial device found in %s. Connect the board, or pass the port, for example /dev/ttyUSB0.\n' \
      "${SERIAL_BY_ID_DIR}" >&2
    return 1
  fi

  mapfile -t candidates < <(find "${SERIAL_BY_ID_DIR}" -mindepth 1 -maxdepth 1)

  if [[ "${#candidates[@]}" -ne 1 ]]; then
    printf 'error: found %s serial devices in %s. Pass the port, or set BENCH_PORT.\n' \
      "${#candidates[@]}" "${SERIAL_BY_ID_DIR}" >&2
    return 1
  fi

  readlink -f "${candidates[0]}"
}

run_idf() {
  local use_docker="$1"
  local port="$2"
  shift 2

  if [[ "${use_docker}" == "yes" ]]; then
    if [[ -n "${port}" ]]; then
      "${IDF_DOCKER}" -p "${port}" "${APP_DIR}" "$@"
    else
      "${IDF_DOCKER}" "${APP_DIR}" "$@"
    fi
    return
  fi

  if [[ -n "${port}" ]]; then
    idf.py -C "${APP_DIR}" -p "${port}" "$@"
  else
    idf.py -C "${APP_DIR}" "$@"
  fi
}

main() {
  local target="${DEFAULT_TARGET}"
  local use_docker=""
  local command=""
  local requested_port=""
  local port=""
  local build_dir
  local -a idf_args

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -t | --target)
        target="$2"
        shift 2
        ;;
      --target=*)
        target="${1#*=}"
        shift
        ;;
      -n | --native)
        use_docker="no"
        shift
        ;;
      -d | --docker)
        use_docker="yes"
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      *)
        if [[ -z "${command}" ]]; then
          command="$1"
        else
          requested_port="$1"
        fi
        shift
        ;;
    esac
  done

  if [[ -z "${command}" ]]; then
    usage >&2
    return 1
  fi

  if ! is_supported_target "${target}"; then
    printf 'error: target "%s" is not supported. Use one of: %s.\n' "${target}" "${SUPPORTED_TARGETS[*]}" >&2
    return 1
  fi

  if [[ -z "${use_docker}" ]]; then
    if command -v idf.py &>/dev/null; then
      use_docker="no"
    else
      use_docker="yes"
    fi
  fi

  if [[ "${use_docker}" == "no" ]] && ! command -v idf.py &>/dev/null; then
    printf 'error: idf.py not found. Load ESP-IDF first with: . ~/esp/esp-idf/export.sh, or use --docker.\n' >&2
    return 1
  fi

  # Paths are relative to the app directory, so they work in Docker and natively.
  build_dir="build_${target}"
  idf_args=(
    -B "${build_dir}"
    -D "SDKCONFIG=${build_dir}/sdkconfig"
    -D "IDF_TARGET=${target}"
  )

  case "${command}" in
    build)
      run_idf "${use_docker}" "" "${idf_args[@]}" build
      ;;
    flash)
      port="$(resolve_port "${requested_port}")"
      run_idf "${use_docker}" "${port}" "${idf_args[@]}" flash
      ;;
    monitor)
      port="$(resolve_port "${requested_port}")"
      run_idf "${use_docker}" "${port}" "${idf_args[@]}" monitor
      ;;
    test)
      "${SCRIPT_DIR}/run_host_tests.sh"
      ;;
    clean)
      rm -rf "${APP_DIR:?}/${build_dir}"
      ;;
    *)
      printf 'error: unknown command "%s".\n' "${command}" >&2
      usage >&2
      return 1
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
