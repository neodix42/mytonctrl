# MyTonCtrl with a separate TON image

The root `Dockerfile` packages this checkout's MyTonCtrl Python utility. It does
not contain TON binaries, a compiler, or TON/MyTonCtrl source repositories. TON executables
run in the controller container; the separate official image supplies their
artifacts. Only the global network configuration is downloaded during normal
first initialization. Optional dump/archive downloads remain explicit settings.

The [official TON image](https://github.com/ton-blockchain/ton/blob/master/Dockerfile)
contains executables in `/usr/local/bin`, Fift libraries in `/usr/lib/fift`, and
wallet/contract scripts in `/usr/share/ton/smartcont`. All three are required.
`docker/export-ton.sh` runs in that unchanged image with `init.sh` bypassed. It
publishes immutable releases to a shared volume and atomically selects `current`.
MyTonCtrl mounts that volume read-only, checks its contents and binary architecture,
then copies one release to a private `/run/ton-active` snapshot before starting.
It refuses startup if artifacts are missing or their runtime dependencies cannot
be loaded. The controller image uses Ubuntu 22.04, matching the current official
TON runtime, with runtime libraries and diagnostic tools only.

## Start with Compose

```sh
cp .env.example .env
# Edit .env: choose installation options in MYTONCTRL_ARGS.
# PUBLIC_IP is optional: leave blank to autodetect, or set the advertised IPv4.
# Pin TON_IMAGE and select your tagged MYTONCTRL_IMAGE.
docker compose build mytonctrl
docker compose up -d
docker compose logs -f mytonctrl
docker compose exec mytonctrl mytonctrl
```

For build metadata set `MYTONCTRL_BUILD_COMMIT` and `MYTONCTRL_BUILD_VERSION` in
`.env`, or pass `--build-arg MYTONCTRL_COMMIT=... --build-arg MYTONCTRL_VERSION=...`
to `docker build`. Every build packages the current local checkout; no controller
code or Python environment is stored in a data volume.

Compose uses host networking, intended for Linux TON nodes. Allow the selected
validator UDP port, QUIC UDP port and liteserver TCP port through the host firewall.
Keep the validator console port private. Installation defaults in `.env.example`
select fixed ports, while empty values let the original installer choose them.
Startup defaults retain the original CPU/memory requirement check;
add `-i` to `MYTONCTRL_ARGS` to bypass it for testing.

`ton-binaries` exits after publishing; MyTonCtrl supervises the node and controller
services without systemd, privileged mode or a Docker socket. All node state,
keys, wallets, controller databases, network configurations and service settings
live in the TON work volume. The entrypoint locks that volume to prevent two
controllers from opening the same node state.

## Start without Compose

```sh
docker build -t mytonctrl:local .
docker volume create mytonctrl-ton-artifacts
docker volume create mytonctrl-ton-work
docker run --rm --entrypoint /bin/sh \
  --mount type=volume,src=mytonctrl-ton-artifacts,dst=/ton-artifacts \
  --mount type=bind,src="$PWD/docker/export-ton.sh",dst=/scripts/export-ton.sh,readonly \
  ghcr.io/ton-blockchain/ton:latest /scripts/export-ton.sh
docker run -d --name mytonctrl --network host --stop-timeout 75 \
  --env-file .env \
  --mount type=volume,src=mytonctrl-ton-artifacts,dst=/ton-artifacts,readonly \
  --mount type=volume,src=mytonctrl-ton-work,dst=/var/ton-work \
  mytonctrl:local
docker exec -it mytonctrl mytonctrl
```

Check mounts and binary dependencies without initializing node state:

```sh
docker run --rm \
  --mount type=volume,src=mytonctrl-ton-artifacts,dst=/ton-artifacts,readonly \
  mytonctrl:local check
```

## Use an existing TON container's volumes

The controller also accepts the official image's native directories, without
an export script or metadata. For example, start a binary-provider container:

```sh
docker run -d --name ton-provider --entrypoint /bin/sleep \
  -v ton-native-bin:/usr/local/bin \
  -v ton-native-fift:/usr/lib/fift \
  -v ton-native-smartcont:/usr/share/ton/smartcont \
  ghcr.io/ton-blockchain/ton:latest infinity
docker run -d --name mytonctrl --network host --stop-timeout 75 --env-file .env \
  -v ton-native-bin:/ton-source/bin:ro \
  -v ton-native-fift:/ton-source/fift:ro \
  -v ton-native-smartcont:/ton-source/smartcont:ro \
  -v mytonctrl-ton-work:/var/ton-work \
  mytonctrl:local
```

Docker populates new empty named volumes from the official image directories.
Reuse the existing provider's actual volume names if it is already running.
Bind mounts containing exported files also work. Override `TON_BINARIES_DIR`,
`FIFT_LIB_DIR` and `TON_SMARTCONT_DIR` when mounting at other paths. Docker does
not expose another container's unmounted filesystem automatically; its directories
must be available as shared volumes or bind mounts.

Reusing populated native volumes with a newer TON image does **not** refresh
their contents. Use fresh volume names for each TON release, or use the exporter
above, which handles this explicitly. Do not modify native files while a new
controller is taking its startup snapshot.

## Update independently

To publish a newer TON image, change `TON_IMAGE` in `.env`, then:

```sh
docker compose pull ton-binaries
docker compose run --rm --no-deps ton-binaries
```

The running controller keeps its private binaries and Fift resources. Its node
process and later console commands continue using the old release. To adopt the
new TON binaries, explicitly restart it:

```sh
docker compose restart mytonctrl
```

To update MyTonCtrl, build the new checkout with a new controller image tag, or
pull a published controller image, then recreate only the controller:

```sh
docker compose build mytonctrl
docker compose up -d --no-deps mytonctrl
```

Persisted node and controller data are reused. Console `update` and `upgrade`
explain this image-based workflow. No in-container TON or MyTonCtrl upgrade
downloads, cloning or binary compilation take place. Old exported TON releases are retained; clean them up
only when they are no longer needed.

Git is available for MyTonCtrl's existing optional contract downloads (legacy
nominator pools and liquid staking). It is never used to install or upgrade
TON or MyTonCtrl in this image.

## Published controller images

GitHub Actions publishes `ghcr.io/<lowercase-repository-owner>/mytonctrl` for
both `linux/amd64` and `linux/arm64`:

| Trigger | Image tag |
| --- | --- |
| A commit pushed to `dev` | `dev` |
| A commit pushed to `master` | `latest` |
| Manually run **Publish tagged Docker image** | The required `tag` input |

The automatic workflow is [Publish Docker image](../.github/workflows/docker-publish.yml).
For a release, open Actions, select
[Publish tagged Docker image](../.github/workflows/docker-publish-tag.yml),
choose the branch or tag to build, and supply the image tag (for example,
`v1.0.0`). These workflows build the selected checkout and publish using the
repository's `GITHUB_TOKEN`.

Set `MYTONCTRL_IMAGE=ghcr.io/<lowercase-repository-owner>/mytonctrl:<tag>` in
`.env` to use a published image. Pull and recreate only the controller:

```sh
docker compose pull mytonctrl
docker compose up -d --no-deps --no-build mytonctrl
```

## Environment options

Compose reads `.env` and passes it to the controller. Standalone Docker uses
`--env-file .env`. Values are parsed as data; the entrypoint never sources or
evaluates the file. Put the original installation flags in `MYTONCTRL_ARGS`,
with shell-style quoting for values containing spaces. See the
[installation option table](../README.md#installation-options) for all host
options and their Docker equivalents.

The default installs a mainnet validator using a prepared dump:

```dotenv
MYTONCTRL_ARGS=-m validator -n mainnet -d
PUBLIC_IP=
```

Blank or omitted `PUBLIC_IP` autodetects the public IPv4 address, matching the
original installer's default behavior. Set it explicitly when the node should
advertise a different address, such as behind NAT. The entrypoint validates the
address before installation starts; autodetection failures produce an error
asking you to set `PUBLIC_IP`.

For a custom network, use `-n custom -c https://example.com/global.config.json`
or `-n custom -c /config/global.config.json` in `MYTONCTRL_ARGS`. Mount a local
configuration file at the supplied absolute path. Add `-t` to disable telemetry,
`-i` to skip the installer CPU/RAM check, or `-s` to disable console startup
checks. The last option is a Docker extension; `-i` retains its original
installation meaning.

To load additional native installation parameters from a mounted file, add
`-e /config/installer.env` to `MYTONCTRL_ARGS`. The container reads `KEY=value`
data without executing shell code. `MYTONCTRL_ARGS=--help` and
`MYTONCTRL_ARGS=--print-env` print help or parsed installation settings and exit
without requiring TON binary mounts.

Repository-selection variables (`AUTHOR`, `REPO`, `BRANCH`, `NODE_REPO`,
`NODE_VERSION`, `MYTONCTRL_VERSION`) are rejected at runtime: select images
instead. `MYTONCTRL_BUILD_VERSION` supplies build metadata without changing code.

The original native settings pass through unchanged: `VALIDATOR_PORT`,
`VALIDATOR_CONSOLE_PORT`, `LITESERVER_PORT`, `QUIC_PORT`, `PUBLIC_IP`, `ARCHIVE_TTL`,
`STATE_TTL`, `ADD_SHARD`, `ARCHIVE_BLOCKS`, `DUMP_CACHE_DIR`, `DUMP_EXTRACT_THREADS`,
and `DUMP_VALIDATE_BEFORE_EXTRACT`. `VERBOSITY` and `CUSTOM_PARAMETERS` append
node arguments on first initialization. Custom parameters cannot replace the
controller-managed binary, state/config/log paths, or foreground service behavior.

Installation flags apply once. Subsequent starts keep the persisted service
configuration and wallet settings. Use normal console commands to change mode,
telemetry and node arguments after installation. Keep the `-u`, `-B`, `-S` and
`-W` values fixed for a data volume; the entrypoint rejects changes. Defaults
are `root`, `/usr/bin`, `/usr/src` and `/var/ton-work`, respectively. Compose
aliases a custom `-W` path to its mounted `/var/ton-work` volume, preserving
persistent storage. Standalone Docker can mount persistent data directly at the
selected `-W` path instead.
When initialization fails, data are preserved and a pending marker prevents
reuse of partial configuration. See [Troubleshooting](#troubleshooting) before
retrying or restoring a backup.

All original console arguments work with `docker exec ... mytonctrl`. They can
also be supplied through `.env`:

| Console argument | Environment setting |
| --- | --- |
| `-c`, `--config` | `MYTONCTRL_CONFIG` |
| `-w`, `--wallets` | `MYTONCTRL_WALLETS` |
| `-s`, `--no-startup-checks` | Add `-s` to `MYTONCTRL_ARGS` |
| `--cmd` | `MYTONCTRL_CMD` |

For example, set `MYTONCTRL_CMD=status` to make the console run `status` by
default. Explicit CLI arguments follow these defaults and take precedence for
options with a value. `MYTONCTRL_ARGS` configures installation and the optional
`-s` console default; installation flags are never forwarded to the console.
Installer `-c` selects global network configuration; console `-c` selects the
controller database. The default container command runs services;
`image console --cmd ...` initializes them and runs a foreground console command.

`--archive` in `MYTONCTRL_ARGS` and `ARCHIVE_BLOCKS` use MyTonCtrl's existing
archive downloader,
which requires **tonutils-storage**, a different program/API from the official
TON `storage-daemon`. Supply its prebuilt executable as `tonutils-storage` in the
mounted flat binaries directory. Startup fails early with an actionable message
when it is absent. The image never compiles this optional tool. `enable TS` uses
the same executable. Optional `enable THA` and `enable LSP` install other projects
on a host; in container deployments run those tools in separate images instead.

## Troubleshooting

Inspect the first installation error with `docker compose logs mytonctrl`.
"Previous initialization was interrupted" means an earlier installation left
partial configuration; the pending marker guards that data. Removing the marker
does not complete or repair the installation.

An older image could pass `--ip :30303` to the validator when `PUBLIC_IP` was
empty, leaving a failed installation. Current images autodetect and validate
blank or missing `PUBLIC_IP` before installation begins.

For a failed first installation, correct `.env` and rebuild the image, then reset
the volumes and retry. **This deletes the node's keys and all stored data:**

```sh
docker compose down -v
docker compose up -d --build
```

For a node with existing keys or data to retain, restore a valid backup instead
of resetting its volumes.

## Development checks

```sh
python3 -m unittest discover -s tests/docker -v
python3 -m pytest tests/unit
MYTONCTRL_ENV_FILE=.env.example docker compose --env-file .env.example config
```

Supervisor lifecycle tests run when the `supervisor` Python package is available;
pure unit tests and exporter tests run with Python's standard library.
