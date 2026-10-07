#!/usr/bin/env bash
# Prepare a standalone Docker deployment using published images.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash install.sh [--branch master|dev] [--image IMAGE]

Download .env and compose.yml into the current directory.
Existing environment or Compose files are never overwritten.

  --branch master|dev  Asset branch and default image tag (default: master/latest)
  --image IMAGE        Override the published MyTonCtrl image
  -h, --help           Show this help

Docker and Compose must be installed separately. This script does not start containers.
EOF
}

fail() {
    printf 'MyTonCtrl Docker setup: %s\n' "$*" >&2
    exit 1
}

branch=master
image=
while (($#)); do
    case "$1" in
        --branch|--image)
            (($# >= 2)) || fail "$1 requires a value"
            if [[ "$1" == --branch ]]; then
                branch=$2
            else
                image=$2
            fi
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *) fail "Unknown option: $1. Use --help for usage." ;;
    esac
done

case "$branch" in
    master) default_tag=latest ;;
    dev) default_tag=dev ;;
    *) fail "--branch must be master or dev" ;;
esac
image=${image:-ghcr.io/neodix42/mytonctrl:$default_tag}
[[ "$image" =~ ^[a-zA-Z0-9][a-zA-Z0-9._:/@-]*$ ]] || fail "Invalid --image value"

check_existing_files() {
    local path
    for path in .env compose.yml compose.yaml docker-compose.yml docker-compose.yaml; do
        if [[ -e "$path" || -L "$path" ]]; then
            fail "$path already exists. Use an empty deployment directory; existing files were preserved."
        fi
    done
}
check_existing_files

if command -v curl >/dev/null 2>&1; then
    downloader=curl
elif command -v wget >/dev/null 2>&1; then
    downloader=wget
else
    fail "Install wget or curl to download the setup files"
fi

stage_dir=$(mktemp -d .mytonctrl-install.XXXXXX)
cleanup() {
    rm -rf -- "$stage_dir"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

download() {
    local url=$1 destination=$2
    if [[ "$downloader" == curl ]]; then
        curl --fail --silent --show-error --location --retry 3 \
            --connect-timeout 10 --max-time 120 --output "$destination" "$url" \
            || fail "Download failed: $url"
    else
        wget --quiet --timeout=30 --tries=3 -O "$destination" "$url" \
            || fail "Download failed: $url"
    fi
    [[ -s "$destination" ]] || fail "Downloaded file is empty: $url"
}

base_url=https://raw.githubusercontent.com/neodiX42/mytonctrl/$branch
download "$base_url/.env.example" "$stage_dir/env.example"
download "$base_url/docker/compose.yml" "$stage_dir/compose.yml"

# Select the published image without sourcing or expanding environment contents.
image_settings=0
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == MYTONCTRL_IMAGE=* ]]; then
        printf 'MYTONCTRL_IMAGE=%s\n' "$image"
        ((image_settings += 1))
    else
        printf '%s\n' "$line"
    fi
done < "$stage_dir/env.example" > "$stage_dir/.env"
((image_settings == 1)) || fail "The environment template must contain one MYTONCTRL_IMAGE setting"
chmod 600 "$stage_dir/.env"
chmod 644 "$stage_dir/compose.yml"

# Finish both downloads before installing either file. Hard links refuse collisions.
check_existing_files
ln "$stage_dir/.env" .env
if ! ln "$stage_dir/compose.yml" compose.yml; then
    # Remove only the environment file created by this attempt.
    [[ .env -ef "$stage_dir/.env" ]] && rm -- .env
    fail "Could not install compose.yml; an existing file was preserved"
fi

printf 'Installed .env and compose.yml in %s\n' "$PWD"
printf 'Controller image: %s\n' "$image"
cat <<'EOF'

Leave TON_WORK_HOST_DIR blank to use the standard TON_WORK_VOLUME Docker volume.
For an external data disk, mount it and set TON_WORK_HOST_DIR to an absolute directory on it.
Edit .env to choose installation arguments and images, then run:
  docker compose pull
  docker compose up -d --no-build --pull never
  docker compose logs -f mytonctrl
Go inside mytonctrl with:
  docker compose exec mytonctrl mytonctrl

The exporter is included in the MyTonCtrl image. No extra script download is needed.
EOF
