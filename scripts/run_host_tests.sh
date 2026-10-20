#! /bin/bash
# Build and run the firmware host tests in tests/host on the ESP-IDF linux
# target. Uses idf.py from the shell when ESP-IDF is loaded, or Docker.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
TESTS_DIR="${REPO_DIR}/tests/host"
IDF_DOCKER="${SCRIPT_DIR}/idf_docker.sh"
TEST_BINARY="${TESTS_DIR}/build/host_tests.elf"

main() {
  if command -v idf.py &>/dev/null; then
    idf.py -C "${TESTS_DIR}" build
    "${TEST_BINARY}"
    return
  fi

  if ! command -v docker &>/dev/null; then
    printf 'error: neither idf.py nor docker is installed. Load ESP-IDF or install Docker to run the host tests.\n' >&2
    return 1
  fi

  # The test binary links against the container's libraries, so it runs in the container too.
  "${IDF_DOCKER}" "${TESTS_DIR}" build
  docker run \
    --rm \
    --user "$(id -u):$(id -g)" \
    --volume "${REPO_DIR}:/project" \
    "espressif/idf:$(tr -d '[:space:]' <"${SCRIPT_DIR}/esp_idf_version.txt")" \
    /project/tests/host/build/host_tests.elf
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
