![GitHub stars](https://img.shields.io/github/stars/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub forks](https://img.shields.io/github/forks/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub issues](https://img.shields.io/github/issues/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub pull requests](https://img.shields.io/github/issues-pr/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub license](https://img.shields.io/github/license/ton-blockchain/mytonctrl?style=flat-square&logo=github)

# MyTonCtrl

MyTonCtrl is a console application that is used for launching and managing TON blockchain nodes.

The extended documentation can be found at https://docs.ton.org/v3/documentation/nodes/mytonctrl/overview and https://docs.ton.org/v3/guidelines/nodes/overview.

## Host installation

Native installations use the host installer and systemd services. Docker-specific
initialization checkpoints, dump recovery and validator readiness polling apply
only inside the MyTonCtrl image. Native installations keep their existing
installation, console, backup and upgrade workflows.

### Operating systems

It is recommended to use Ubuntu 22.04 LTS or Ubuntu 24.04 LTS for using MyTonCtrl. However, the full list of tested OS is below:

| Operating System | Status        |
|------------------|---------------|
| Ubuntu 20.04 LTS | OK            |
| Ubuntu 22.04 LTS | OK            |
| Ubuntu 24.04 LTS | OK            |
| Debian 10        | Deprecated    |
| Debian 11        | OK            |
| Debian 12        | OK            |
| Debian 13        | Not supported |

### Modes

MyTonCtrl supports these installation modes:

- `liteserver` - run the node as a liteserver only
- `collator` - run the node as a collator
- `validator` - run a validator node using the validator wallet for staking
- `single-nominator` - run a validator node with single-nominator staking (recommended for validators)
- `nominator-pool-v2` - run a validator node with nominator-pool v2 staking
- `nominator-pool` - run a validator node with nominator-pool v1 staking (**deprecated**, use `nominator-pool-v2`)
- `liquid-staking` - run a validator node with liquid-staking enabled

`single-nominator`, `nominator-pool-v2`, `nominator-pool`, and `liquid-staking` all install a validator node and enable `validator` mode automatically.
You can change enabled modes later after installation.

Learn more about node types: https://docs.ton.org/v3/documentation/nodes/overview

### Install

Host installation uses `scripts/install.sh`, downloaded below as `install-host.sh`.
Installation and upgrades use `sudo` or `su` to install system components. You
may be prompted for the root or sudo user's password.

1. Download installation script:
	```shell
	wget -O install-host.sh https://raw.githubusercontent.com/ton-blockchain/mytonctrl/master/scripts/install.sh
	```

2. Run script with desired options:
	```shell
	sudo bash install-host.sh -m <mode>
	```
	Or for Debian:
	```shell
	su root -c 'bash install-host.sh -m <mode>'
	```

To install a full archive liteserver, use:
```shell
sudo bash install-host.sh -m liteserver --archive
```

To view all available installation options use `bash install-host.sh --help`

### Installation options

Pass these options directly to `sudo bash install-host.sh`. For example:

```sh
sudo bash install-host.sh -m validator -n mainnet -d
```

| Installation option | Description |
| --- | --- |
| `-m`, `--mode MODE` | Select a mode listed above. Omitting both mode and backup opens the interactive installer. |
| `-n`, `--network NETWORK` | Select `mainnet` (default) or `testnet`. For a custom network, supply its configuration with `-c URL`. |
| `-c`, `--config URL` | Use a custom global network configuration URL when installing TON. |
| `-u`, `--user USER` | Select the MyTonCtrl account; defaults to the invoking account. The TON node runs as `validator`. |
| `-t`, `--telemetry` | Disable telemetry. |
| `-i`, `--ignore-reqs` | Skip the minimum CPU and RAM check. |
| `-d`, `--dump` | Download a prepared dump to reduce initial synchronization time. |
| `--archive` | Install a full archive liteserver; requires `-m liteserver`. |
| `-o`, `--only-mtc` | Configure MyTonCtrl for an existing node using a backup; requires `-p`. |
| `-l`, `--only-node` | Configure node operation with a separate controller and export a backup. |
| `-p`, `--backup PATH` | Restore an installation from a backup. |
| `-B`, `--bin-dir PATH` | Select the binary directory (default `/usr/bin` on Linux). |
| `-S`, `--src-dir PATH` | Select the source directory (default `/usr/src` on Linux). |
| `-W`, `--ton-work-dir PATH` | Select the node's work directory (default `/var/ton-work`). |
| `-e`, `--env-file PATH` | Load installation environment variables from a shell environment file. |
| `-a`, `--author AUTHOR` | Select the MyTonCtrl GitHub owner. |
| `-r`, `--repo REPO` | Select the MyTonCtrl repository. |
| `-b`, `--branch BRANCH` | Select the MyTonCtrl branch. |
| `-g`, `--node-repo REPO` | Select the TON repository. |
| `-v`, `--node-version VERSION` | Select the TON commit, branch or tag to build. |
| `--print-env` | Print the interactive installer's chosen settings and command; use without `-m` or `-p`. |
| `-h`, `--help` | Print installation help. |

### Installation configuration

You can also configure some installation parameters using environment variables. For example:

* `VALIDATOR_CONSOLE_PORT` - port for validator console (default: random port in range 2000-65000)
* `LITESERVER_PORT` - port for liteserver (default: random port in range 2000-65000)
* `VALIDATOR_PORT` - port for validator (default: random port in range 2000-64000)

You can provide `env` file with allowed variables to installation script:
```shell
sudo bash install-host.sh -m <mode> --env-file /path/to/installer.env
```

### Interactive CLI installer

To use the interactive CLI installer, run the installation script without a
mode (`-m`) or backup (`-p`):

```shell
sudo bash install-host.sh [args]
```
You will be prompted to choose the installation mode and other options.

To run the interactive installer in `dry-run` mode, which will show you all the options you have selected and command 
that will be executed during installation without actually installing MyTonCtrl, use flag `--print-env`:

```shell
sudo bash install-host.sh --print-env
```

After installation, you can run MyTonCtrl console using the command:
```shell
mytonctrl
```

### Console arguments

Pass console arguments directly to `mytonctrl`:

| Console argument | Description |
| --- | --- |
| `-c`, `--config PATH` | Read a different controller database (`mytoncore.db`). |
| `-w`, `--wallets DIR` | Use a different wallets directory. |
| `-s`, `--no-startup-checks` | Skip console startup checks. |
| `--cmd COMMAND` | Run a console command and exit; also skips startup checks. |
| `-h`, `--help` | Print console help. |

```sh
mytonctrl --cmd "get modes"
```

Installer `-c` selects the network configuration; console `-c` selects the
controller database. Installer `-i` skips hardware checks; console `-s` skips
startup checks.

### Telemetry

By default, MyTonCtrl sends validator statistics to the https://toncenter.com server.
It is necessary to identify network abnormalities, as well as to quickly give feedback to developers.
To disable telemetry during installation, use the `-t` flag:
```sh
sudo bash install-host.sh -m <mode> -t
```

To disable telemetry after installation, do the following:
```sh
MyTonCtrl> set sendTelemetry false
```

## Docker image

MyTonCtrl and TON use separate images. The official TON image supplies binaries
and Fift resources to a shared volume, with its `init.sh` entrypoint bypassed.
The MyTonCtrl image initializes and runs the node using those mounted artifacts.
It requires the artifacts to be mounted before startup. Node state, keys,
wallets and controller settings persist in a separate work volume.

Use the Compose quick setup below, or follow
[the examples without Docker Compose](#use-docker-without-compose).

### Quick setup

With Docker and Compose installed on Linux, prepare an empty deployment directory:

```sh
mkdir mytonctrl-docker
cd mytonctrl-docker
wget -O install.sh https://raw.githubusercontent.com/neodiX42/mytonctrl/master/install.sh
bash install.sh
```

Alternatively, run the installer directly from an empty deployment directory:

```sh
wget -qO- https://raw.githubusercontent.com/neodiX42/mytonctrl/master/install.sh | bash
```

The installer downloads only `.env` and `compose.yml` into the current
directory. It refuses existing environment or Compose files.
It prepares the setup without installing Docker or starting containers. Edit
`.env`, then [start the containers and open the console](#start-and-open-the-console).

The default `--branch master` selects master assets and
`ghcr.io/neodix42/mytonctrl:latest`. For dev assets and the `dev` image, use:

```sh
wget -qO- https://raw.githubusercontent.com/neodiX42/mytonctrl/dev/install.sh | bash -s -- --branch dev
```

Use `--image IMAGE` to select another published controller image and `--help`
to view setup options. The download commands require these installer files on
the selected branch; startup requires its image tag to have been published by
GitHub Actions.

The commands below use the downloaded `compose.yml`. Keep the same `.env`
volume names and Compose project name throughout the setup's lifetime. Compose
uses host networking for Linux nodes. See [Docker setup](docker/README.md) for
standalone Docker commands, existing TON mounts and runtime details.

### Installation arguments in .env

Use the same [installation options](#installation-options) as the host installer,
provided through `MYTONCTRL_ARGS` in the `.env` created by quick setup.
The default settings use a published controller image and install a mainnet
validator using a prepared dump:

```dotenv
TON_IMAGE=ghcr.io/ton-blockchain/ton:latest
MYTONCTRL_IMAGE=ghcr.io/neodix42/mytonctrl:latest
MYTONCTRL_ARGS=-m validator -n mainnet -d
PUBLIC_IP=
```

Leave `PUBLIC_IP` blank to autodetect the public IPv4 address, or set the address
the node should advertise. The entrypoint validates it before initialization.
Choose and pin image tags or digests in `TON_IMAGE` and `MYTONCTRL_IMAGE`.

Installation arguments apply when initializing an empty work volume. Existing
installations keep their configuration; use console commands for later changes.
Keep `-u`, `-B`, `-S` and `-W` fixed when reusing a work volume. The controller user
defaults to `root`; `-u USER` selects the controller service account. The TON node
runs as `validator`.

For example, to install a testnet liteserver with telemetry disabled:

```dotenv
MYTONCTRL_ARGS=-m liteserver -n testnet -t
```

Docker supports these adaptations of the host arguments:

| Option | Docker behavior |
| --- | --- |
| `-c`, `--config` | Accepts a URL or an absolute path to a mounted network configuration file. For a custom network, use `-n custom -c URL` or `-n custom -c /mounted/global.config.json`. |
| `-e`, `--env-file` | Reads a mounted file of `KEY=value` data. Compose already loads `.env`; standalone Docker uses `--env-file .env`. |
| `-a`/`-r`/`-b`, `--author`/`--repo`/`--branch` | Select the checkout when building the controller image, then select `MYTONCTRL_IMAGE`. These source-selection arguments are unavailable at runtime. |
| `-g`/`-v`, `--node-repo`/`--node-version` | Select `TON_IMAGE` to choose prebuilt TON binaries. These source-selection arguments are unavailable at runtime. |
| `--print-env`, `--help` | Print parsed installation settings or help and exit. |
| `-s`, `--no-startup-checks` | Docker extension: add to `MYTONCTRL_ARGS` to skip console startup checks. Installation flags are kept separate from console arguments. |

Mount files referenced by `-c`, `-p` or `-e` into the controller using Compose
volumes or Docker's `--mount` option. `--archive` also requires a mounted
prebuilt `tonutils-storage` executable; see
[Docker environment options](docker/README.md#environment-options).

### Start and open the console

After editing `.env`, pull the selected images and start the setup from
the deployment directory:

```sh
docker compose pull
docker compose up -d --no-build --pull never
docker compose logs -f mytonctrl
```

The one-shot `ton-exporter` service uses the same controller image to copy its
packaged exporter script into a shared script volume. `ton-binaries` then runs
that script in the official TON image and exits after exporting artifacts.
These three services use two images. The `mytonctrl` service keeps the node and
controller running. Allow the configured validator and QUIC UDP ports and
liteserver TCP port through the host firewall; keep the validator console port
private.

Open the console or run a command using the same [console arguments](#console-arguments)
as the host utility:

```sh
docker compose exec mytonctrl mytonctrl
docker compose exec mytonctrl mytonctrl --cmd "get modes"
```

In Docker mode, status displays image references instead of Git commits:

```text
Version mytonctrl: ghcr.io/neodix42/mytonctrl:latest
Version validator: ghcr.io/ton-blockchain/ton:latest
```

The controller reference is embedded when building the image. The TON reference
comes from the exported release copied into the running container; exporting
a newer release leaves this display unchanged until the controller restarts.
Mounted binaries without exported image metadata display an unknown image.

Console defaults can also be set in `.env` using `MYTONCTRL_CONFIG`,
`MYTONCTRL_WALLETS` and `MYTONCTRL_CMD`. Use `-s` in `MYTONCTRL_ARGS` for the startup
check default. Explicit console arguments take precedence for options with values.

The publishing workflows use `dev` for commits to `dev`, `latest` for commits to
`master`, and a required tag input for manual builds.

### Run a benchmark

The controller image includes `uv`, Python 3.14 and TON's Python benchmark
framework with its generated bindings. The benchmark uses the binaries and
Fift resources supplied by the separate TON image; it does not download a
repository, install dependencies or compile TON when invoked.

View the benchmark options without stopping the node:

```sh
docker compose exec mytonctrl mytonctrl --cmd "benchmark --help"
```

The benchmark starts a temporary local TON network and measures its workload.
After node initialization completes, stop the live controller and validator
services before running it. Run these commands in your host shell, outside the
`MyTonCtrl>` prompt (type `exit` to leave the console):

```sh
docker compose exec mytonctrl sudo systemctl stop mytoncore
docker compose exec mytonctrl sudo systemctl stop validator
docker compose exec mytonctrl mytonctrl --cmd "benchmark --nodes 2 --duration 60"
```

Stopping these services keeps the container running. Pass workload options
such as `--tps`, `--shards`, `--spammers` or `--sync-test` to `benchmark`. Use
`--tmp-dir /mounted/path` to select benchmark storage; its default parent is
`/var/ton-work/tmp`. Each run uses a separate temporary directory and removes
its test network afterward. The container manages `--build-dir`, `--source-dir`
and `--work-dir` to keep benchmark cleanup separate from the live node's data.
Its database, keys, wallet and dump cache are retained.

Restart the live services after the benchmark, including if it failed or was
interrupted:

```sh
docker compose exec mytonctrl sudo systemctl start validator
docker compose exec mytonctrl sudo systemctl start mytoncore
```

### Build from a local checkout (optional)

For development, use the repository root's `compose.yaml`, which supports
building the local checkout. The quick setup's `compose.yml` uses published
images only. On the first setup in a checkout, create its `.env`:

```sh
cp .env.example .env
```

Keep `MYTONCTRL_IMAGE=mytonctrl:local` or choose another local image tag, then
run these commands from that checkout's root:

```sh
docker compose -f compose.yaml pull ton-binaries
docker compose -f compose.yaml build mytonctrl
docker compose -f compose.yaml up -d --no-build --pull never
```

Compose embeds `MYTONCTRL_IMAGE` as the controller image reference. For a direct
`docker build`, pass `--build-arg MYTONCTRL_IMAGE_REF=mytonctrl:local` alongside
`-t mytonctrl:local`, replacing both values with your chosen image name and tag.

### Stop and resume

Stop the node and controller while keeping their containers and data:

```sh
docker compose stop mytonctrl
```

Resume the stopped container:

```sh
docker compose restart --no-deps mytonctrl
```

To remove the service containers while keeping the persistent volumes, use:

```sh
docker compose down
```

Start them again with `docker compose up -d --no-build --pull never`.

### Upgrade the TON image

Set `TON_IMAGE` to the desired tag or digest in `.env`, then pull the image and
export its binaries:

```sh
docker compose pull ton-binaries
docker compose run --rm ton-binaries
```

The running controller keeps using its private copy of the previous TON binaries
and resources. Adopt the newly exported TON release when ready:

```sh
docker compose restart --no-deps mytonctrl
```

Every controller start, restart or recreation selects the currently exported
TON release. Updating `TON_IMAGE` in `.env` alone does not export new binaries.

### Upgrade the MyTonCtrl image

For a published image, set `MYTONCTRL_IMAGE` to the desired tag in `.env`, then
pull it and recreate the controller:

```sh
docker compose pull mytonctrl
docker compose run --rm --no-deps ton-exporter
docker compose up -d --no-deps --no-build --pull never mytonctrl
```

For a [local development setup](#build-from-a-local-checkout-optional), update
the checkout and keep its local `MYTONCTRL_IMAGE` tag in `.env`. From that same
checkout's root, build and recreate using its `compose.yaml`:

```sh
docker compose -f compose.yaml build mytonctrl
docker compose -f compose.yaml run --rm --no-deps ton-exporter
docker compose -f compose.yaml up -d --no-deps --no-build --pull never mytonctrl
```

Both methods refresh the packaged exporter script, preserve the work volume and
reuse node keys, wallets, settings and an unfinished dump download. An upgrade
during initialization resumes the original installation using its saved settings;
it does not select a newer dump or discard the existing archive.
Recreation also adopts the currently exported TON release. Use these image
updates for container deployments; the console's `update` and `upgrade` commands
refer to this workflow. A container restart alone does not replace its controller
image or reload `.env` changes.

### Use Docker without Compose

These examples use Docker directly on Linux, with the same two images and
persistent volumes as the Compose setup. Run them from your deployment
directory. Keep the image and volume variables available in your shell; in a
new terminal, set them again to the values used for this installation.

#### Set up and open the console

Prepare an empty directory and download the environment template:

```sh
mkdir mytonctrl-docker &&
  cd mytonctrl-docker &&
  wget -O .env https://raw.githubusercontent.com/neodiX42/mytonctrl/master/.env.example
```

Edit `.env` with the same [installation arguments](#installation-arguments-in-env)
and `PUBLIC_IP` settings described above. For a published controller, set
`MYTONCTRL_IMAGE=ghcr.io/neodix42/mytonctrl:latest` in that file. Then set the
following shell variables to match your chosen image references and volume
names in `.env`:

```sh
TON_IMAGE=ghcr.io/ton-blockchain/ton:latest
MYTONCTRL_IMAGE=ghcr.io/neodix42/mytonctrl:latest
TON_SCRIPTS_VOLUME=mytonctrl-ton-scripts
TON_ARTIFACTS_VOLUME=mytonctrl-ton-artifacts
TON_WORK_VOLUME=mytonctrl-ton-work

docker pull "$MYTONCTRL_IMAGE"
docker pull "$TON_IMAGE"
docker volume create "$TON_SCRIPTS_VOLUME"
docker volume create "$TON_ARTIFACTS_VOLUME"
docker volume create "$TON_WORK_VOLUME"
```

Docker's [`--env-file`](https://docs.docker.com/reference/cli/docker/container/run/#env)
passes settings to the container; it does not choose the image or volume names
in these shell commands. Keep `MYTONCTRL_ARGS` unquoted as in `.env.example`,
and use literal values rather than `${VARIABLE}` substitutions in `.env`.

Copy the exporter bundled in the controller image into the script volume:

```sh
docker run --rm --pull never --network none --entrypoint /bin/sh \
  --mount "type=volume,src=$TON_SCRIPTS_VOLUME,dst=/scripts" \
  "$MYTONCTRL_IMAGE" -eu -c '
    staged_script=$(mktemp /scripts/.export-ton.sh.XXXXXX)
    trap "rm -f \"$staged_script\"" EXIT
    cp /usr/local/lib/mytonctrl/export-ton.sh "$staged_script"
    chmod 444 "$staged_script"
    mv -f "$staged_script" /scripts/export-ton.sh
  '
```

Export TON's binaries and Fift resources using the official image with its
`init.sh` entrypoint replaced. This helper exits after publishing the artifacts:

```sh
docker run --rm --pull never --network none --entrypoint /bin/sh \
  --env "TON_IMAGE_REF=$TON_IMAGE" \
  --mount "type=volume,src=$TON_ARTIFACTS_VOLUME,dst=/ton-artifacts" \
  --mount "type=volume,src=$TON_SCRIPTS_VOLUME,dst=/scripts,readonly" \
  "$TON_IMAGE" /scripts/export-ton.sh
```

Start the controller with the artifact volume read-only and the work volume
persistent. These examples use the default work path `/var/ton-work`; if you
select a different path with `-W`, mount the work volume at that path instead.

```sh
docker run -d --name mytonctrl --pull never --network host \
  --restart unless-stopped --stop-timeout 75 --env-file .env \
  --mount "type=volume,src=$TON_ARTIFACTS_VOLUME,dst=/ton-artifacts,readonly" \
  --mount "type=volume,src=$TON_WORK_VOLUME,dst=/var/ton-work" \
  "$MYTONCTRL_IMAGE"
docker logs -f mytonctrl
```

Open the console in another terminal, or run a single command:

```sh
docker exec -it mytonctrl mytonctrl
docker exec mytonctrl mytonctrl --cmd status
```

#### Stop and resume

Stop the container while retaining its data, then start it again when needed:

```sh
docker stop mytonctrl
docker start mytonctrl
```

Stopping uses the 75-second grace period configured above. Starting or restarting
retains the container's image and environment. Recreate it using the controller
upgrade commands below to load a changed image or `.env` file.

#### Upgrade TON independently

Set `TON_IMAGE` to the desired tag or digest in `.env` and in your shell, then
pull and export it. For example, to refresh the `latest` tag:

```sh
TON_IMAGE=ghcr.io/ton-blockchain/ton:latest
docker pull "$TON_IMAGE"
docker run --rm --pull never --network none --entrypoint /bin/sh \
  --env "TON_IMAGE_REF=$TON_IMAGE" \
  --mount "type=volume,src=$TON_ARTIFACTS_VOLUME,dst=/ton-artifacts" \
  --mount "type=volume,src=$TON_SCRIPTS_VOLUME,dst=/scripts,readonly" \
  "$TON_IMAGE" /scripts/export-ton.sh
```

The running controller continues using its existing TON binaries. Adopt the
newly exported release when ready:

```sh
docker restart mytonctrl
```

This keeps the work volume, keys, wallets and downloaded dump data.

#### Upgrade MyTonCtrl

Set `MYTONCTRL_IMAGE` to the desired tag or digest in `.env` and in your shell.
Pull it and refresh the packaged exporter for future TON exports:

```sh
MYTONCTRL_IMAGE=ghcr.io/neodix42/mytonctrl:latest
docker pull "$MYTONCTRL_IMAGE"
docker run --rm --pull never --network none --entrypoint /bin/sh \
  --mount "type=volume,src=$TON_SCRIPTS_VOLUME,dst=/scripts" \
  "$MYTONCTRL_IMAGE" -eu -c '
    staged_script=$(mktemp /scripts/.export-ton.sh.XXXXXX)
    trap "rm -f \"$staged_script\"" EXIT
    cp /usr/local/lib/mytonctrl/export-ton.sh "$staged_script"
    chmod 444 "$staged_script"
    mv -f "$staged_script" /scripts/export-ton.sh
  '
docker stop mytonctrl
docker rm mytonctrl
docker run -d --name mytonctrl --pull never --network host \
  --restart unless-stopped --stop-timeout 75 --env-file .env \
  --mount "type=volume,src=$TON_ARTIFACTS_VOLUME,dst=/ton-artifacts,readonly" \
  --mount "type=volume,src=$TON_WORK_VOLUME,dst=/var/ton-work" \
  "$MYTONCTRL_IMAGE"
```

Keep the same volume names and installation paths. The recreated container
reuses the node database, keys, wallets and settings; interrupted initialization
resumes with its existing dump cache. It also adopts the currently exported
TON release. There is no need to export TON again for a controller-only update.

#### Remove the standalone setup

**Removing the volumes permanently deletes node keys, wallets, blockchain
data, controller settings and downloaded dumps. Save any required backup
outside these volumes first.**

Remove this setup's container and its three volumes:

```sh
docker stop mytonctrl
docker rm mytonctrl
docker volume rm "$TON_WORK_VOLUME" "$TON_ARTIFACTS_VOLUME" "$TON_SCRIPTS_VOLUME"
```

The helper containers were removed automatically after exporting. To retain
the node data, stop after removing the controller container and keep the
volumes. Optionally, remove the downloaded images when other containers no
longer use them and delete the local environment file:

```sh
docker image rm "$MYTONCTRL_IMAGE" "$TON_IMAGE"
rm -f .env
```

### Recover interrupted initialization

Use a controller image containing the recovery fixes, then follow the image
upgrade commands above with the same `TON_WORK_VOLUME` and installation paths.
The container resumes initialization automatically, including installations
left by an older image with an empty `.initializing` marker. Keep the existing
volumes and marker; `docker compose down -v` deletes the downloaded dump and
node data.

The default `DUMP_CACHE_DIR=/var/ton-work/dump-cache` is inside the persistent
work volume. Mount persistent storage there if you choose a cache outside the
work volume. Partial downloads resume the same pinned archive. Complete
archives are verified and reused locally; older caches without metadata look
up the existing archive's dated metadata rather than downloading today's dump.
If that metadata is unavailable, startup reports the problem and preserves the
archive. An interrupted extraction restarts from the cached archive while
preserving node keys and configuration. The archive is removed only after the
whole installation completes, reclaiming its disk space.

Follow progress with `docker compose logs -f mytonctrl`. In another terminal,
inspect initialization, dump, service and local resource status:

```sh
docker compose exec mytonctrl mytonctrl --cmd status
```

Opening `docker compose exec mytonctrl mytonctrl` also shows overall status.
Unavailable node/chain fields display `n/a` while initialization is in progress;
the controller's background tasks start after its client settings are ready.
Error summaries appear on stdout, while full tracebacks remain in the persistent
controller log at `/var/ton-work/controller/mytoncore/mytoncore.log`.

An extracted dump means the database import is complete. The validator still
needs to start and accept console commands before initialization can finish.
During this stage, console status shows local data and service state without
running validator-dependent startup checks. A service shown as `starting` or
`running (initializing)` has not yet completed initialization.

If the validator keeps restarting, inspect its own log and service exit status:

```sh
docker compose exec mytonctrl tail -n 80 /var/ton-work/log
docker compose exec mytonctrl systemctl show validator --property=SubState,ExecMainStatus
```

Installer failures and their full tracebacks are saved in
`/var/ton-work/controller/mytoninstaller.log`. Keep the data volumes while
diagnosing a failed start; retries reuse the extracted database.

### Diagnose a node that is not catching up

`Initialization status: ready` means installation and client configuration are
complete. Blockchain synchronization continues afterward. Docker status shows
masterchain lag in seconds and shardchain lag in blocks separately; compare
both over time rather than treating the shard block gap as elapsed seconds.

Inspect the engine's own log and process state when it restarts:

```sh
docker compose exec mytonctrl tail -n 160 /var/ton-work/log
docker compose exec mytonctrl systemctl show validator --property=SubState,MainPID,ExecMainStatus
docker compose logs --since 30m --tail 300 mytonctrl
```

For raw progress counters, run this twice about a minute apart. It reads the
saved console settings, including the actual configured port:

```sh
docker compose exec mytonctrl /opt/mytonctrl/venv/bin/python -c '
import json
import subprocess
from pathlib import Path

config = json.loads(Path("/var/ton-work/controller/mytoncore/mytoncore.db").read_text())["validatorConsole"]
subprocess.run([
    config["appPath"], "-k", config["privKeyPath"], "-p", config["pubKeyPath"],
    "-a", config["addr"], "-v", "0", "--cmd", "getstats",
], check=True, timeout=15)
'
```

Compare `masterchainblock`, `masterchainblocktime` and
`shardclientmasterchainseqno`; increasing block numbers establish progress.
A changing `start_time` indicates validator restarts. State serialization
counters describe a separate background task.

Check the saved network addresses and current I/O activity:

```sh
docker compose exec mytonctrl jq '{addrs,fullnode,fullnodeslaves}' /var/ton-work/db/config.json
docker compose exec mytonctrl iostat -xz 1 5
docker compose exec mytonctrl vmstat 1 5
```

Verify the advertised IP and ports in this saved configuration, since changing
installation options in `.env` does not rewrite an initialized node. High disk
activity can delay catch-up; inspect I/O latency and queue sizes. Allocated swap
alone does not show active swapping; check `vmstat`'s `si` and `so` columns.

During initial sync, controller queries can use public liteservers. A public
server's latest block or zerostate banner describes that query, rather than
the local node's progress. Failed queries now report their exit code instead
of treating those banners as valid configuration data. Custom overlay messages
also need to be evaluated separately from the validator engine's own failure.

For a setup without Compose, replace `docker compose exec mytonctrl` with
`docker exec mytonctrl`, and use `docker logs --since 30m --tail 300 mytonctrl`.
Retain the work volume while diagnosing synchronization or engine failures.

### Remove the Docker setup

Remove this Compose setup's containers, named volumes and service images:

```sh
docker compose down --volumes --rmi all --remove-orphans
```

**This deletes node keys, wallets, blockchain data, controller settings and
exported TON artifacts. Save any required backup outside these volumes first.**
The cleanup applies to the services and volumes in this Compose file; see the
[Compose down reference](https://docs.docker.com/reference/cli/docker/compose/down/)
for flag details. To also remove the files downloaded by quick setup after
teardown, run:

```sh
rm -f .env compose.yml install.sh
```
