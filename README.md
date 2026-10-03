![GitHub stars](https://img.shields.io/github/stars/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub forks](https://img.shields.io/github/forks/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub issues](https://img.shields.io/github/issues/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub pull requests](https://img.shields.io/github/issues-pr/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub license](https://img.shields.io/github/license/ton-blockchain/mytonctrl?style=flat-square&logo=github)

# MyTonCtrl

MyTonCtrl is a console application that is used for launching and managing TON blockchain nodes.

The extended documentation can be found at https://docs.ton.org/v3/documentation/nodes/mytonctrl/overview and https://docs.ton.org/v3/guidelines/nodes/overview.

## Host installation

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

Installation and upgrades use `sudo` or `su` to install system components. You
may be prompted for the root or sudo user's password.

1. Download installation script:
	```shell
	wget https://raw.githubusercontent.com/ton-blockchain/mytonctrl/master/scripts/install.sh
	```

2. Run script with desired options:
	```shell
	sudo bash install.sh -m <mode>
	```
	Or for Debian:
	```shell
	su root -c 'bash install.sh -m <mode>'
	```

To install a full archive liteserver, use:
```shell
sudo bash install.sh -m liteserver --archive
```

To view all available installation options use `bash install.sh --help`

### Installation options

Pass these options directly to `sudo bash install.sh`. For example:

```sh
sudo bash install.sh -m validator -n mainnet -d
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
sudo bash install.sh -m <mode> --env-file /path/to/installer.env
```

### Interactive CLI installer

To use the interactive CLI installer, run the installation script without a
mode (`-m`) or backup (`-p`):

```shell
sudo bash install.sh [args]
```
You will be prompted to choose the installation mode and other options.

To run the interactive installer in `dry-run` mode, which will show you all the options you have selected and command 
that will be executed during installation without actually installing MyTonCtrl, use flag `--print-env`:

```shell
sudo bash install.sh --print-env
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
sudo bash install.sh -m <mode> -t
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

The commands below use the included `compose.yaml` from the repository root.
Use the same `.env` volume names and Compose project name throughout the setup's
lifetime. Compose uses host networking for Linux nodes. See [Docker setup](docker/README.md)
for standalone Docker commands, existing TON container mounts and runtime details.

### Installation arguments in .env

Use the same [installation options](#installation-options) as the host installer,
provided through `MYTONCTRL_ARGS` in `.env`. Create the file on first setup:

```sh
cp .env.example .env
```

The default settings build the local controller checkout and install a mainnet
validator using a prepared dump:

```dotenv
TON_IMAGE=ghcr.io/ton-blockchain/ton:latest
MYTONCTRL_IMAGE=mytonctrl:local
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
volumes. `--archive` also requires a mounted prebuilt `tonutils-storage` executable;
see [Docker environment options](docker/README.md#environment-options).

### Start and open the console

Build the local checkout and start both services:

```sh
docker compose pull ton-binaries
docker compose build mytonctrl
docker compose up -d --no-build --pull never
docker compose logs -f mytonctrl
```

The `ton-binaries` service exits after exporting artifacts. The `mytonctrl`
service keeps the node and controller running. Allow the configured validator
and QUIC UDP ports and liteserver TCP port through the host firewall; keep the
validator console port private.

Open the console or run a command using the same [console arguments](#console-arguments)
as the host utility:

```sh
docker compose exec mytonctrl mytonctrl
docker compose exec mytonctrl mytonctrl --cmd "get modes"
```

Console defaults can also be set in `.env` using `MYTONCTRL_CONFIG`,
`MYTONCTRL_WALLETS` and `MYTONCTRL_CMD`. Use `-s` in `MYTONCTRL_ARGS` for the startup
check default. Explicit console arguments take precedence for options with values.

To start with a published controller image, set
`MYTONCTRL_IMAGE=ghcr.io/<repository-owner>/mytonctrl:<tag>` in `.env`, then:

```sh
docker compose pull mytonctrl ton-binaries
docker compose up -d --no-build
```

The publishing workflows use `dev` for commits to `dev`, `latest` for commits to
`master`, and a required tag input for manual builds.

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

Start them again with `docker compose up -d --no-build`.

### Upgrade the TON image

Set `TON_IMAGE` to the desired tag or digest in `.env`, then pull the image and
export its binaries:

```sh
docker compose pull ton-binaries
docker compose run --rm --no-deps ton-binaries
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
docker compose up -d --no-deps --no-build mytonctrl
```

For a local build, update the checkout, keep a local `MYTONCTRL_IMAGE` tag in
`.env`, and build and recreate the controller:

```sh
docker compose build mytonctrl
docker compose up -d --no-deps --no-build --pull never mytonctrl
```

Both methods preserve the work volume and reuse node keys, wallets and settings.
Recreation also adopts the currently exported TON release. Use these image
updates for container deployments; the console's `update` and `upgrade` commands
refer to this workflow. A container restart alone does not replace its controller
image or reload `.env` changes.

### Remove the Docker setup

Remove this Compose setup's containers, named volumes and service images:

```sh
docker compose down --volumes --rmi all --remove-orphans
```

**This deletes node keys, wallets, blockchain data, controller settings and
exported TON artifacts. Save any required backup outside these volumes first.**
The cleanup applies to the services and volumes in this Compose file; see the
[Compose down reference](https://docs.docker.com/reference/cli/docker/compose/down/)
for flag details. To also remove the local configuration file after teardown,
run `rm .env`.
