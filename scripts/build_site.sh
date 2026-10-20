#! /bin/bash
# Build the web flasher site: the page in web/, the merged bench agent images
# and the ESP Web Tools manifest. GitHub Actions publishes the site to GitHub
# Pages. Refer to docs/web_flasher.md.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
APP_DIR="${REPO_DIR}/firmware/bench_agent"
WEB_DIR="${REPO_DIR}/web"
DEFAULT_OUT_DIR="${REPO_DIR}/site"
DEFAULT_SERVE_PORT="8000"

# One line for each image: the image name, the ESP Web Tools chip family and
# the serial type. "cdc" is the native USB port of the chip, "uart" is a
# USB-to-UART bridge, and "-" matches any port.
IMAGES=(
  "esp32 ESP32 -"
  "esp32s3 ESP32-S3 uart"
  "esp32s3_usb_serial_jtag ESP32-S3 cdc"
  "esp32c3 ESP32-C3 uart"
  "esp32c3_usb_serial_jtag ESP32-C3 cdc"
  "esp32c6 ESP32-C6 uart"
  "esp32c6_usb_serial_jtag ESP32-C6 cdc"
)

usage() {
  cat <<USAGE
Usage: scripts/build_site.sh [OPTIONS]

Build the web flasher site in site/. Each image is bench_agent_<name>.bin,
where <name> is the target and the optional variant, for example
esp32s3_usb_serial_jtag.

Options:
  -i, --images DIR   Take the images from DIR. If you do not give it, the
                     script takes merged-binary.bin from each
                     firmware/bench_agent/build_ci_<name> directory. Run
                     scripts/ci.sh build TARGET [VARIANT] first.
  -o, --out DIR      Write the site to DIR. Default: site/.
  -s, --serve        Serve the site on http://localhost:${DEFAULT_SERVE_PORT} after the build.
  -h, --help         Show this help.
USAGE
}

image_source() {
  local images_dir="$1"
  local name="$2"

  if [[ -n "${images_dir}" ]]; then
    printf '%s\n' "${images_dir}/bench_agent_${name}.bin"
  else
    printf '%s\n' "${APP_DIR}/build_ci_${name}/merged-binary.bin"
  fi
}

firmware_version() {
  git -C "${REPO_DIR}" describe --tags --always --dirty 2>/dev/null || printf 'unknown\n'
}

write_manifest() {
  local manifest="$1"
  local version="$2"
  shift 2
  local -a builds=("$@")
  local index

  {
    printf '{\n'
    printf '  "name": "ESP32 Bench Agent",\n'
    printf '  "version": "%s",\n' "${version}"
    printf '  "new_install_prompt_erase": true,\n'
    printf '  "new_install_improv_wait_time": 0,\n'
    printf '  "builds": [\n'
    for index in "${!builds[@]}"; do
      printf '%s' "${builds[${index}]}"
      if [[ "${index}" -lt $((${#builds[@]} - 1)) ]]; then
        printf ','
      fi
      printf '\n'
    done
    printf '  ]\n'
    printf '}\n'
  } >"${manifest}"
}

main() {
  local images_dir=""
  local out_dir="${DEFAULT_OUT_DIR}"
  local serve="no"
  local entry
  local name
  local chip_family
  local serial_type
  local image_path
  local serial_field
  local -a builds=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -i | --images)
        images_dir="$2"
        shift 2
        ;;
      --images=*)
        images_dir="${1#*=}"
        shift
        ;;
      -o | --out)
        out_dir="$2"
        shift 2
        ;;
      --out=*)
        out_dir="${1#*=}"
        shift
        ;;
      -s | --serve)
        serve="yes"
        shift
        ;;
      -h | --help)
        usage
        return 0
        ;;
      *)
        printf 'error: unknown argument %s. Run scripts/build_site.sh --help.\n' "$1" >&2
        return 1
        ;;
    esac
  done

  rm -rf "${out_dir:?}"
  mkdir -p "${out_dir}/firmware"
  cp -r "${WEB_DIR}/." "${out_dir}/"

  for entry in "${IMAGES[@]}"; do
    read -r name chip_family serial_type <<<"${entry}"
    image_path="$(image_source "${images_dir}" "${name}")"

    if [[ ! -f "${image_path}" ]]; then
      printf 'warning: no image for %s at %s. The site does not include it.\n' "${name}" "${image_path}" >&2
      continue
    fi

    cp "${image_path}" "${out_dir}/firmware/bench_agent_${name}.bin"

    serial_field=""
    if [[ "${serial_type}" != "-" ]]; then
      serial_field="\"serialType\": \"${serial_type}\", "
    fi
    builds+=("    { \"chipFamily\": \"${chip_family}\", ${serial_field}\"parts\": [{ \"path\": \"firmware/bench_agent_${name}.bin\", \"offset\": 0 }] }")
    printf 'Added %s (%s, %s).\n' "${name}" "${chip_family}" "${serial_type}"
  done

  if [[ "${#builds[@]}" -eq 0 ]]; then
    printf 'error: found no firmware images. Run scripts/ci.sh build TARGET [VARIANT] first.\n' >&2
    return 1
  fi

  write_manifest "${out_dir}/manifest.json" "$(firmware_version)" "${builds[@]}"
  printf 'Wrote the site to %s.\n' "${out_dir}"

  if [[ "${serve}" == "yes" ]]; then
    printf 'Open http://localhost:%s in Chrome or Edge. Press Ctrl+C to stop.\n' "${DEFAULT_SERVE_PORT}"
    python3 -m http.server --directory "${out_dir}" --bind 127.0.0.1 "${DEFAULT_SERVE_PORT}"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  main "$@"
fi
