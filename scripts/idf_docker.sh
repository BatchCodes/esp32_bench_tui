#! /bin/bash
# Run idf.py inside the official ESP-IDF Docker image, at the version pinned in
# scripts/esp_idf_version.txt. This is an alternative to the native install.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
IDF_VERSION_FILE="${SCRIPT_DIR}/esp_idf_version.txt"
IDF_IMAGE_NAME="espressif/idf"
CONTAINER_REPO_DIR="/project"

usage() {
  cat <<USAGE
Usage: scripts/idf_docker.sh [-p PORT] APP_DIR [IDF_PY_ARGS...]

Run idf.py in the ${IDF_IMAGE_NAME} Docker image for the app in APP_DIR.
APP_DIR must be inside the repository.

Options:
  -p, --port PORT    Pass the serial port into the container and to idf.py.
                     USB pass-through works on Linux only.
  -h, --help         Show this help.

Examples:
  scripts/idf_docker.sh firmware/bench_agent set-target esp32
  scripts/idf_docker.sh firmware/bench_agent build
  scripts/idf_docker.sh -p /dev/ttyUSB0 firmware/bench_agent flash monitor
USAGE
}

require_command() {
  local command_name="$1"
  local reason="$2"

  if ! command -v "${command_name}" &>/dev/null; then
    printf 'error: "%s" is not installed. It is needed to %s.\n' "${command_name}" "${reason}" >&2
    return 1
  fi
}

resolve_app_dir() {
  local app_dir="$1"
  local absolute_app_dir

  if [[ ! -d "${app_dir}" ]]; then
    printf 'error: app directory "%s" does not exist.\n' "${app_dir}" >&2
    return 1
  fi

  absolute_app_dir="$(cd -- "${app_dir}" && pwd)"

  if [[ "${absolute_app_dir}" != "${REPO_DIR}" && "${absolute_app_dir}" != "${REPO_DIR}/"* ]]; then
    printf 'error: "%s" is outside the repository. Only the repository is mounted in the container.\n' \
      "${app_dir}" >&2
    return 1
  fi

  printf '%s\n' "${absolute_app_dir#"${REPO_DIR}"}"
}

main() {
  local serial_port=""
  local app_dir=""
  local relative_app_dir
  local idf_version
  local -a docker_args
  local -a idf_args

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -p | --port)
        serial_port="$2"
        shift 2
        ;;
      --port=*)
        serial_port="${1#*=}"
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      *)
        app_dir="$1"
        shift
        break
        ;;
    esac
  done

  if [[ -z "${app_dir}" ]]; then
    printf 'error: APP_DIR is missing. Give the app directory, for example firmware/bench_agent.\n' >&2
    usage >&2
    return 1
  fi

  require_command docker "run the ESP-IDF container"

  relative_app_dir="$(resolve_app_dir "${app_dir}")"
  idf_version="$(tr -d '[:space:]' <"${IDF_VERSION_FILE}")"

  docker_args=(
    --rm
    --user "$(id -u):$(id -g)"
    --env HOME=/tmp
    --env IDF_GIT_SAFE_DIR="${CONTAINER_REPO_DIR}"
    --volume "${REPO_DIR}:${CONTAINER_REPO_DIR}"
    --workdir "${CONTAINER_REPO_DIR}${relative_app_dir}"
  )

  if [[ -t 0 && -t 1 ]]; then
    docker_args+=(--interactive --tty)
  fi

  idf_args=()

  if [[ -n "${serial_port}" ]]; then
    if [[ ! -e "${serial_port}" ]]; then
      printf 'error: serial port "%s" does not exist. Connect the board and check with: ls /dev/ttyACM* /dev/ttyUSB*\n' \
        "${serial_port}" >&2
      return 1
    fi

    docker_args+=(
      --device "${serial_port}"
      --group-add "$(stat -c '%g' "${serial_port}")"
    )
    idf_args+=(-p "${serial_port}")
  fi

  docker run \
    "${docker_args[@]}" \
    "${IDF_IMAGE_NAME}:${idf_version}" \
    idf.py "${idf_args[@]}" "$@"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
