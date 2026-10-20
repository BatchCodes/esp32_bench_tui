#! /bin/bash
# Run the bench host tool, or its Python tests, in Docker. The image holds
# Python and the dependencies only. The repository and the current directory
# are mounted at the same paths, so configuration paths work as on the host.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
DOCKERFILE="${REPO_DIR}/docker/host/Dockerfile"
PYPROJECT="${REPO_DIR}/pyproject.toml"
IMAGE_NAME="bench-host"
SERIAL_BY_ID_DIR="/dev/serial/by-id"
PYTHON_TESTS_DIR="tests/host_python"
STATE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/bench"

usage() {
  cat <<USAGE
Usage: scripts/bench_docker.sh [--test | --build] [BENCH_ARGS...]

Run the bench host tool in Docker. All BENCH_ARGS go to the tool, for example
--config examples/led_button.yaml or --sim.

Options:
  --test       Run the Python tests instead of the tool.
  --build      Build the image again, then exit.
  -h, --help   Show this help.

The serial port comes from --port, from \$BENCH_PORT, or is the only device in
${SERIAL_BY_ID_DIR}. USB pass-through to a container works on Linux only. On
macOS and Windows, use --sim, or install the host tool natively.

Examples:
  scripts/bench_docker.sh --config examples/pot_servo.yaml --sim
  scripts/bench_docker.sh --config examples/led_button.yaml
  scripts/bench_docker.sh --config examples/led_button.yaml --port /dev/ttyUSB0
  scripts/bench_docker.sh --test
USAGE
}

require_docker() {
  if ! command -v docker &>/dev/null; then
    printf 'error: "docker" is not installed. It is needed to run the host tool without a local Python install.\n' >&2
    return 1
  fi
}

image_tag() {
  # A new tag when the Dockerfile or the dependencies change.
  cat "${DOCKERFILE}" "${PYPROJECT}" | sha256sum | cut -c1-12
}

build_image() {
  local image="$1"

  docker build \
    --tag "${image}" \
    --file "${DOCKERFILE}" \
    "${REPO_DIR}"
}

ensure_image() {
  local image="$1"

  if docker image inspect "${image}" &>/dev/null; then
    return 0
  fi

  printf 'Building the host image %s. This runs one time.\n' "${image}" >&2
  build_image "${image}" >&2
}

# The serial port from the arguments, $BENCH_PORT or /dev/serial/by-id, or
# nothing for --sim, --check and --list-boards.
find_port() {
  local -a candidates
  local argument
  local previous=""

  for argument in "$@"; do
    case "${argument}" in
      --sim | --check | --list-boards | -h | --help)
        return 0
        ;;
      --port=*)
        printf '%s\n' "${argument#*=}"
        return 0
        ;;
    esac
    if [[ "${previous}" == "--port" || "${previous}" == "-p" ]]; then
      printf '%s\n' "${argument}"
      return 0
    fi
    previous="${argument}"
  done

  if [[ -n "${BENCH_PORT:-}" ]]; then
    printf '%s\n' "${BENCH_PORT}"
    return 0
  fi

  if [[ ! -d "${SERIAL_BY_ID_DIR}" ]]; then
    return 0
  fi

  mapfile -t candidates < <(find "${SERIAL_BY_ID_DIR}" -mindepth 1 -maxdepth 1)
  if [[ "${#candidates[@]}" -eq 1 ]]; then
    readlink -f "${candidates[0]}"
  fi
}

# The arguments without --port and its value. The script adds the port again
# by its /dev name, because the container has no /dev/serial/by-id links.
without_port() {
  local skip_next="no"
  local argument

  for argument in "$@"; do
    if [[ "${skip_next}" == "yes" ]]; then
      skip_next="no"
      continue
    fi
    case "${argument}" in
      --port | -p)
        skip_next="yes"
        ;;
      --port=*) ;;
      *)
        printf '%s\0' "${argument}"
        ;;
    esac
  done
}

main() {
  local mode="run"
  local image
  local port
  local device
  local work_dir
  local -a docker_args
  local -a command_args

  case "${1:-}" in
    --test)
      mode="test"
      shift
      ;;
    --build)
      mode="build"
      shift
      ;;
    -h | --help)
      usage
      return 0
      ;;
  esac

  require_docker
  image="${IMAGE_NAME}:$(image_tag)"

  if [[ "${mode}" == "build" ]]; then
    build_image "${image}"
    return
  fi

  ensure_image "${image}"

  work_dir="$(pwd)"
  # The board picker remembers the last board here.
  mkdir -p "${STATE_DIR}"
  docker_args=(
    --rm
    --init
    --user "$(id -u):$(id -g)"
    --env HOME=/tmp
    --env "TERM=${TERM:-xterm-256color}"
    --env "COLORTERM=${COLORTERM:-truecolor}"
    --env "PYTHONPATH=${REPO_DIR}/host"
    --env XDG_CONFIG_HOME=/tmp/.config
    --volume "${STATE_DIR}:/tmp/.config/bench"
    --volume "${REPO_DIR}:${REPO_DIR}"
    --workdir "${work_dir}"
  )

  if [[ "${work_dir}" != "${REPO_DIR}" && "${work_dir}" != "${REPO_DIR}/"* ]]; then
    docker_args+=(--volume "${work_dir}:${work_dir}")
  fi

  if [[ -t 0 && -t 1 ]]; then
    docker_args+=(--interactive --tty)
  fi

  if [[ "${mode}" == "test" ]]; then
    docker run \
      "${docker_args[@]}" \
      --workdir "${REPO_DIR}" \
      "${image}" \
      python -m unittest discover -s "${PYTHON_TESTS_DIR}" -t . "$@"
    return
  fi

  command_args=("$@")
  port="$(find_port "$@")"

  if [[ -n "${port}" ]]; then
    device="$(readlink -f "${port}")"
    if [[ ! -e "${device}" ]]; then
      printf 'error: serial port "%s" does not exist. Connect the board and check with: ls /dev/ttyACM* /dev/ttyUSB*\n' \
        "${port}" >&2
      return 1
    fi

    docker_args+=(
      --device "${device}"
      --group-add "$(stat -c '%g' "${device}")"
    )

    mapfile -d '' -t command_args < <(without_port "$@")
    command_args+=(--port "${device}")
  fi

  docker run \
    "${docker_args[@]}" \
    "${image}" \
    python -m bench "${command_args[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
