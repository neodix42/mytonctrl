# Docker image

MyTonCtrl and TON use separate images. The official TON image supplies binaries
and Fift resources to a shared volume, with its `init.sh` entrypoint bypassed.
The MyTonCtrl image initializes and runs the node using those mounted artifacts.
It requires the artifacts to be mounted before startup. Node state, keys,
wallets, downloaded dumps and controller settings persist in a standard Docker
volume or an optional host data directory, mounted at `/var/ton-work` inside the container.

Use the Compose quick setup below, or follow
[the examples without Docker Compose](#use-docker-without-compose).

## Quick setup

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
`.env`, choose the [data storage](#store-ton-data-on-a-separate-disk),
then [start the containers and open the console](#start-and-open-the-console).

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
volume names, optional host data directory and Compose project name throughout
the setup's lifetime. Compose uses host networking for Linux nodes. See
[Docker setup](docker/README.md) for
standalone Docker commands, existing TON mounts and runtime details.

## Store TON data on a separate disk

Both Compose files use the original Docker-managed named volume when
`TON_WORK_HOST_DIR` is empty or unset. Existing installations keep using the
same volume, including custom names selected by `TON_WORK_VOLUME`:

```dotenv
TON_WORK_VOLUME=mytonctrl-ton-work
TON_WORK_HOST_DIR=
```

To place the node database, keys, wallets, controller state, logs and dump cache
on a separate disk, set `TON_WORK_HOST_DIR` to an absolute directory on the Docker
host. For example, after mounting your data disk at `/mnt/ton`:

```sh
findmnt --mountpoint /mnt/ton &&
  sudo mkdir -p /mnt/ton/ton-work
df -h /mnt/ton/ton-work
```

Set this in `.env`:

```dotenv
TON_WORK_HOST_DIR=/mnt/ton/ton-work
```

Compose bind-mounts that directory at `/var/ton-work`; keep `-W` and
`DUMP_CACHE_DIR` as container paths. With a nonempty host path, `TON_WORK_VOLUME`
is unused and the small script and binary artifact volumes remain Docker-managed.
Compose's short mount syntax creates a missing host directory automatically,
so prepare it explicitly and verify the storage device before starting. See Docker's
[bind mount options](https://docs.docker.com/reference/compose-file/services/#volumes).

Mount the disk before starting the container, including after a host reboot.
Check that `df` shows the intended data filesystem. Directory existence does
not establish that the intended disk is mounted. Use a dedicated child directory
on that disk and keep the same path during image upgrades and recovery.

### Move an existing named-volume installation

Changing the mount does not move existing data. With the old Compose setup,
stop the controller first; this also stops its validator and background service:

```sh
docker compose stop mytonctrl
```

Prepare an empty directory on the mounted data disk as above. Copy the old
volume while the node is stopped, using its actual volume name and an already
available controller image:

```sh
OLD_TON_WORK_VOLUME=mytonctrl-ton-work
TON_WORK_HOST_DIR=/mnt/ton/ton-work
MYTONCTRL_IMAGE=ghcr.io/neodix42/mytonctrl:latest

docker volume inspect "$OLD_TON_WORK_VOLUME" >/dev/null &&
  docker run --rm --pull never --network none --user 0 --entrypoint /bin/sh \
    --mount "type=volume,src=$OLD_TON_WORK_VOLUME,dst=/old,readonly" \
    --mount "type=bind,src=$TON_WORK_HOST_DIR,dst=/new" \
    "$MYTONCTRL_IMAGE" -eu -c 'test -z "$(ls -A /new)"; cp -a /old/. /new/'
```

This copies the database, keys, configuration and cached dumps with ownership
and permissions preserved. The destination must be empty. Install the updated
Compose file, set `TON_WORK_HOST_DIR` in `.env` to the destination, and
keep the other image, port and installer settings. Then start the setup:

```sh
docker compose up -d --no-build --pull never
docker compose exec mytonctrl mytonctrl --cmd status
```

Keep the old volume until you have verified the copied installation and backup.
Do not run the old and new controllers against the same data concurrently.

## Installation arguments in .env

Use the same [installation options](README.md#installation-options) as the host installer,
provided through `MYTONCTRL_ARGS` in the `.env` created by quick setup.
The default settings use a published controller image and install a mainnet
validator using a prepared dump:

```dotenv
TON_IMAGE=ghcr.io/ton-blockchain/ton:latest
MYTONCTRL_IMAGE=ghcr.io/neodix42/mytonctrl:latest
TON_WORK_HOST_DIR=
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

## Start and open the console

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

Open the console or run a command using the same [console arguments](README.md#console-arguments)
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

## Run a benchmark

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

## Build from a local checkout (optional)

For development, use the repository root's `compose.yaml`, which supports
building the local checkout. The quick setup's `compose.yml` uses published
images only. On the first setup in a checkout, create its `.env`:

```sh
cp .env.example .env
```

Leave `TON_WORK_HOST_DIR` blank for the named volume, or select a host directory
as described in [storage setup](#store-ton-data-on-a-separate-disk). Keep
`MYTONCTRL_IMAGE=mytonctrl:local` or choose another local image tag, then run
these commands from that checkout's root:

```sh
docker compose -f compose.yaml pull ton-binaries
docker compose -f compose.yaml build mytonctrl
docker compose -f compose.yaml up -d --no-build --pull never
```

Compose embeds `MYTONCTRL_IMAGE` as the controller image reference. For a direct
`docker build`, pass `--build-arg MYTONCTRL_IMAGE_REF=mytonctrl:local` alongside
`-t mytonctrl:local`, replacing both values with your chosen image name and tag.

## Stop and resume

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

## Upgrade the TON image

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

## Upgrade the MyTonCtrl image

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

## Use Docker without Compose

These examples use Docker directly on Linux, with the same two images and
persistent volumes as the Compose setup. Run them from your deployment
directory. Keep the image and volume variables available in your shell; in a
new terminal, set them again to the values used for this installation.

### Set up and open the console

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
TON_WORK_HOST_DIR=

docker pull "$MYTONCTRL_IMAGE"
docker pull "$TON_IMAGE"
docker volume create "$TON_SCRIPTS_VOLUME"
docker volume create "$TON_ARTIFACTS_VOLUME"
if [ -n "$TON_WORK_HOST_DIR" ]; then
  TON_WORK_MOUNT="type=bind,src=$TON_WORK_HOST_DIR,dst=/var/ton-work"
else
  docker volume create "$TON_WORK_VOLUME"
  TON_WORK_MOUNT="type=volume,src=$TON_WORK_VOLUME,dst=/var/ton-work"
fi
```

The default uses a named volume. For a host directory, set `TON_WORK_HOST_DIR`
in both your shell and `.env`, prepare it on your mounted disk as described in
[storage setup](#store-ton-data-on-a-separate-disk), then run the mount-selection
block above. Keep `TON_WORK_MOUNT` available for startup and image upgrades.

Docker's [`--env-file`](https://docs.docker.com/reference/cli/docker/container/run/#env)
passes settings to the container; it does not choose the image, volume names or
host path in these shell commands. Keep `MYTONCTRL_ARGS` unquoted as in `.env.example`,
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

Start the controller with the artifact volume read-only and your selected data
storage mounted read-write. These examples use the default container work
path `/var/ton-work`; if you select a different path with `-W`, change the work
mount destination to that container path.

```sh
docker run -d --name mytonctrl --pull never --network host \
  --restart unless-stopped --stop-timeout 75 --env-file .env \
  --mount "type=volume,src=$TON_ARTIFACTS_VOLUME,dst=/ton-artifacts,readonly" \
  --mount "$TON_WORK_MOUNT" \
  "$MYTONCTRL_IMAGE"
docker logs -f mytonctrl
```

Open the console in another terminal, or run a single command:

```sh
docker exec -it mytonctrl mytonctrl
docker exec mytonctrl mytonctrl --cmd status
```

### Stop and resume

Stop the container while retaining its data, then start it again when needed:

```sh
docker stop mytonctrl
docker start mytonctrl
```

Stopping uses the 75-second grace period configured above. Starting or restarting
retains the container's image and environment. Recreate it using the controller
upgrade commands below to load a changed image or `.env` file.

### Upgrade TON independently

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

### Upgrade MyTonCtrl

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
  --mount "$TON_WORK_MOUNT" \
  "$MYTONCTRL_IMAGE"
```

Keep the same volume names, optional host data directory and installation paths.
The recreated container reuses the node database, keys, wallets and settings; interrupted initialization
resumes with its existing dump cache. It also adopts the currently exported
TON release. There is no need to export TON again for a controller-only update.

### Remove the standalone setup

Remove this setup's container and its artifact/script volumes:

**In named-volume mode, these commands also delete node keys, wallets, blockchain
data and dumps. Back them up first.** With a host path, its directory remains intact.

```sh
docker stop mytonctrl
docker rm mytonctrl
docker volume rm "$TON_ARTIFACTS_VOLUME" "$TON_SCRIPTS_VOLUME"
if [ -z "$TON_WORK_HOST_DIR" ]; then
  docker volume rm "$TON_WORK_VOLUME"
fi
```

The helper containers were removed automatically after exporting. For complete
host data removal, follow [data cleanup](#remove-the-docker-setup).
Optionally, remove the downloaded images when other containers no
longer use them and delete the local environment file:

```sh
docker image rm "$MYTONCTRL_IMAGE" "$TON_IMAGE"
rm -f .env
```

## Recover interrupted initialization

Use a controller image containing the recovery fixes, then follow the image
upgrade commands above with the same `TON_WORK_VOLUME` or `TON_WORK_HOST_DIR`
and installation paths.
The container resumes initialization automatically, including installations
left by an older image with an empty `.initializing` marker. Keep the existing
work storage and marker. **In named-volume mode, `docker compose down -v` deletes
the downloaded dump and node data.** With a host directory, that command removes
only the script/artifact volumes and retains node data. Use `docker compose down`
without `-v` to retain all storage in either mode.

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

An extracted dump means the downloaded archive has been unpacked into the work
volume. The validator may still need to import archive blocks and catch up with
the network. It must start and accept console commands before installation can finish.
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

## Diagnose a node that is not catching up

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

TON also writes worker diagnostics to `/var/ton-work/log.threadN.log`. Inspect
those files when the main log contains only a fatal error and backtrace:

```sh
docker compose exec mytonctrl sh -c '
tail -n 80 /var/ton-work/log /var/ton-work/log.thread*.log |
grep -E "==>|FATAL_ERROR|Unexpected Status|STATUS:|import-db-slice|apply-block|celldb"
'
```

Compare the timestamps inside the messages. Persistent log files can contain
crashes from before an image upgrade, and inactive worker files retain older
entries. A running validator process can also be a replacement started by
Supervisor after a crash; check block progress as well as process state.

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

### Archive block application timeouts

An `Error : 652 : timeout` from `import-db-slice.cpp` with an actor named
`!apply(-1,...)` means applying an imported masterchain block failed. In
[TON commit `3d478cb`](https://github.com/ton-blockchain/ton/blob/3d478cbde854be03a18ab2a59f8fc3c565cf7d14/validator/import-db-slice.cpp#L258-L270),
the application request has a 600-second deadline, and a failed result triggers
a fatal assertion. Supervisor then restarts the engine. This deadline covers
block application, including database and state operations; the archive download
has a separate timeout. MyTonCtrl cannot increase this deadline through an
installer argument.

High disk latency or competing database workloads can prevent timely block
application. [TON's troubleshooting guide](https://github.com/ton-blockchain/docs/blob/main/content/nodes/cpp/run-archive-liteserver.mdx#performance-issues)
also identifies storage performance as a cause of archive import timeouts.
Use `iostat` to inspect latency and queues, rather than relying on disk utilization
alone. If another full node such as gton shares the storage, temporarily pause
it using its own service manager and compare TON's block progress and disk
latency. Change one setting at a time so the comparison is meaningful.

For a machine running many validator threads, a lower thread count is another
reversible trial. Record the existing value, then try 32 threads using the
existing installer command:

```sh
docker compose exec mytonctrl mytonctrl --cmd 'installer status'
docker compose exec mytonctrl mytonctrl --cmd 'installer set_node_argument --threads 32'
docker compose exec mytonctrl mytonctrl --cmd 'installer status'
docker compose exec mytonctrl systemctl show validator --property=SubState,MainPID,ExecMainStatus
```

This changes the persistent validator service and restarts the validator with
the same database and keys. Compare raw block counters and I/O readings over
at least 15 minutes, including the former ten-minute crash interval. If it does
not help, restore the recorded thread count with the same command. For example,
use `installer set_node_argument --threads 127` if the previous value was 127.
Changing `CUSTOM_PARAMETERS` in `.env` applies only during first installation;
use the installer command to adjust an existing node.

For a short diagnostic window, enable detailed engine logs, collect the worker
messages, then restore normal verbosity to limit log traffic:

```sh
docker compose exec mytonctrl mytonctrl --cmd 'installer set_node_argument --verbosity 3'
# After collecting the engine's logs and progress counters:
docker compose exec mytonctrl mytonctrl --cmd 'installer set_node_argument --verbosity 1'
```

Both commands restart the validator. Preserve the data volume when diagnosing
timeouts. The message `Too much metadata in the database, do only partial check`
means a [bounded metadata check](https://github.com/ton-blockchain/ton/blob/3d478cbde854be03a18ab2a59f8fc3c565cf7d14/validator/db/celldb.cpp#L119-L141)
reached its inspection limit; that message alone does not establish database
corruption or require a new dump.

For a setup without Compose, replace `docker compose exec mytonctrl` with
`docker exec mytonctrl`, and use `docker logs --since 30m --tail 300 mytonctrl`.
Retain the work volume while diagnosing synchronization or engine failures.

## Remove the Docker setup

Remove this Compose setup's containers, named volumes and service images:

**When `TON_WORK_HOST_DIR` is blank, this deletes the node data volume, including
keys, wallets, blockchain data, controller settings and downloaded dumps. Save a
backup outside these volumes first.** It also deletes the TON artifacts and
packaged script volume. When `TON_WORK_HOST_DIR` is set, that external directory
remains intact, including all node data.

```sh
docker compose down --volumes --rmi all --remove-orphans
```

The cleanup applies to the services and named volumes in this Compose file; see
[Compose down reference](https://docs.docker.com/reference/cli/docker/compose/down/)
for flag details. To also remove the files downloaded by quick setup after
teardown, run:

```sh
rm -f .env compose.yml install.sh
```

To erase the node data too, first stop and remove the containers, save any
required backup elsewhere, and verify the exact directory you selected. For the
example path in this guide, permanently delete it with:

```sh
sudo rm -rf -- /mnt/ton/ton-work
```

Replace that example with your actual `TON_WORK_HOST_DIR` when it differs.
