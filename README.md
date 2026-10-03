![GitHub stars](https://img.shields.io/github/stars/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub forks](https://img.shields.io/github/forks/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub issues](https://img.shields.io/github/issues/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub pull requests](https://img.shields.io/github/issues-pr/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/ton-blockchain/mytonctrl?style=flat-square&logo=github) ![GitHub license](https://img.shields.io/github/license/ton-blockchain/mytonctrl?style=flat-square&logo=github)

# MyTonCtrl

MyTonCtrl is a console application that is used for launching and managing TON blockchain nodes.

The extended documentation can be found at https://docs.ton.org/v3/documentation/nodes/mytonctrl/overview and https://docs.ton.org/v3/guidelines/nodes/overview.

For a controller Docker image that consumes mounted binaries from a separate
official TON image, see [Docker setup](docker/README.md). The repository includes
a `Dockerfile`, `.env.example`, and optional `compose.yaml`.

## Operating Systems

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

## Installation
Please note that during the installation and upgrade procedures, MyTonCtrl will need to escalate privileges using the `sudo` or `su` methods in order to upgrade / install system wide components. Depending on your environment, you may be prompted to enter the password for the root or sudo user.


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

Pass these options to `sudo bash install.sh` for a host installation. For Docker,
put installation options in `.env` as `MYTONCTRL_ARGS`; the default is:

```dotenv
MYTONCTRL_ARGS=-m validator -n mainnet -d
PUBLIC_IP=
```

Blank or omitted `PUBLIC_IP` makes Docker autodetect the node's public IPv4
address. Set it explicitly when the advertised address differs, such as behind
NAT. The entrypoint validates the address before installation begins. Docker
installation options apply when initializing an empty TON work volume. See
[Docker setup](docker/README.md) for image selection, mounts and updates.

| Original installation option | Host installer behavior | Docker equivalent |
| --- | --- | --- |
| `-m`, `--mode MODE` | Select any mode listed above; omitting it opens the interactive installer. | `-m validator` in `MYTONCTRL_ARGS`; all existing modes are supported. |
| `-n`, `--network NETWORK` | Select `mainnet` (default) or `testnet`. | `-n mainnet`, `-n testnet`, or `-n custom` in `MYTONCTRL_ARGS`. |
| `-c`, `--config URL` | Use a custom global network configuration URL. | `-c URL` or `-c /mounted/global.config.json` in `MYTONCTRL_ARGS`; mount local files read-only. |
| `-u`, `--user USER` | Select the account used for MyTonCtrl. | `-u USER` in `MYTONCTRL_ARGS` (default `root`); the entrypoint runs as root and controller services use the selected account. |
| `-t`, `--telemetry` | Disable telemetry. | `-t` in `MYTONCTRL_ARGS`. |
| `-i`, `--ignore-reqs` | Skip the minimum CPU and RAM check. | `-i` in `MYTONCTRL_ARGS`. |
| `-d`, `--dump` | Download a prepared dump to reduce initial synchronization time. | `-d` in `MYTONCTRL_ARGS` (enabled in `.env.example`). |
| `--archive` | Install a full archive liteserver; requires `-m liteserver`. | `-m liteserver --archive` in `MYTONCTRL_ARGS`; also supply a prebuilt `tonutils-storage` binary. |
| `-o`, `--only-mtc` | Install only MyTonCtrl; requires `-p`. | `-o -p /mounted/backup.tar.gz` in `MYTONCTRL_ARGS`. |
| `-l`, `--only-node` | Install only the TON node. | `-l` in `MYTONCTRL_ARGS`. |
| `-p`, `--backup PATH` | Restore installation settings from a backup. | `-p /mounted/backup.tar.gz` in `MYTONCTRL_ARGS`; mount the backup. |
| `-B`, `--bin-dir PATH` | Select the binary directory (default `/usr/bin` on Linux). | `-B PATH` in `MYTONCTRL_ARGS`; a writable compatibility layout points to the mounted TON binaries. |
| `-S`, `--src-dir PATH` | Select the source directory (default `/usr/src` on Linux). | `-S PATH` in `MYTONCTRL_ARGS`; used for Fift resources without a TON repository. |
| `-W`, `--ton-work-dir PATH` | Select the node's work directory (default `/var/ton-work`). | `-W PATH` in `MYTONCTRL_ARGS`; Compose keeps data in its `/var/ton-work` volume through a path alias. |
| `-e`, `--env-file PATH` | Read installation environment variables from a file. | Docker `--env-file .env`, Compose `env_file`, or `-e /mounted/installer.env` in `MYTONCTRL_ARGS` for native parameters. |
| `-a`/`-r`/`-b`, `--author`/`--repo`/`--branch` | Select the MyTonCtrl GitHub owner, repository and branch. | Build the chosen checkout or select `MYTONCTRL_IMAGE`; runtime source selection is unavailable. |
| `-g`/`-v`, `--node-repo`/`--node-version` | Select the TON repository and commit, branch or tag to build. | Select `TON_IMAGE`; its binaries are mounted separately. |
| `--print-env` | Show the interactive installer's selected command and environment without installing. | `--print-env` in `MYTONCTRL_ARGS` prints the parsed installation configuration and exits. |
| `-h`, `--help` | Print installation help. | `--help` in `MYTONCTRL_ARGS` prints Docker installation help and exits. |

The Docker-only `-s`, `--no-startup-checks` option in `MYTONCTRL_ARGS` disables
console startup checks. `-i` skips installation hardware checks; it does not
disable console startup checks. The installer's `-c` selects the network
configuration, while the interactive `mytonctrl -c` option selects its database.

### Installation configuration

You can also configure some installation parameters using environment variables. For example:
* `VALIDATOR_CONSOLE_PORT` - port for validator console (default: random port in range 2000-65000)
* `LITESERVER_PORT` - port for liteserver (default: random port in range 2000-65000)
* `VALIDATOR_PORT` - port for validator (default: random port in range 2000-64000)

You can provide `env` file with allowed variables to installation script:
```shell
sudo bash install.sh -m <mode> --env-file /path/to/env/
```

### Interactive CLI installer

To install MyTonCtrl using convenient interactive CLI installer, run the installation script without providing mode to it:

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

## Telemetry
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
