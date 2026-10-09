#!/usr/bin/env bash
# Standalone, same-host migration wizard. Python is embedded so only this file is downloaded.
set -euo pipefail
command -v python3 >/dev/null 2>&1 || { printf 'Install python3 to run the migration wizard.\n' >&2; exit 1; }
python3 - "$@" <<'PY'
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.request import urlopen

if sys.version_info < (3, 8):
    print('Python 3.8 or newer is required for the migration wizard.', file=sys.stderr)
    sys.exit(1)


class MigrationError(Exception):
    pass


def run(args, capture=True, **kwargs):
    result = subprocess.run([str(arg) for arg in args], check=False,
                            text=True, capture_output=capture, **kwargs)
    if result.returncode:
        # Do not print captured configuration/private data on failure.
        raise MigrationError(f"Command failed ({result.returncode}): {shlex.join([str(arg) for arg in args[:4]])}")
    return result.stdout or ""


def parse_env(text):
    """Read simple dotenv assignments without executing or expanding them."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[key] = value
    return result


def ensure_destination_isolated(path, mount_sources):
    path = Path(path).expanduser()
    if not path.is_absolute() or re.search(r'[\s,$:#\x00-\x1f]', str(path)):
        raise MigrationError('Choose an absolute destination without whitespace or Compose metacharacters.')
    if path.is_symlink():
        raise MigrationError('The migration destination must be a real directory, not a symlink.')
    path = path.resolve()
    for source in mount_sources:
        source = Path(source).resolve()
        if path == source or source in path.parents or path in source.parents:
            raise MigrationError(f'Destination overlaps donor storage: {source}')
    if path.exists():
        # A prepared .env is allowed, but never reuse node data or a prior migration.
        if not path.is_dir() or {item.name for item in path.iterdir()} - {'deployment'}:
            raise MigrationError('Destination contains existing data; choose a new directory. Existing data was preserved.')
        deployment = path / 'deployment'
        if deployment.exists() or deployment.is_symlink():
            if deployment.is_symlink() or not deployment.is_dir() or {item.name for item in deployment.iterdir()} - {'.env'}:
                raise MigrationError('An existing deployment may contain only .env; other files were preserved.')
            env_path = deployment / '.env'
            if env_path.exists() or env_path.is_symlink():
                if env_path.is_symlink() or not env_path.is_file() or env_path.stat().st_nlink != 1:
                    raise MigrationError('Existing .env must be a regular file without links.')
    if not path.parent.is_dir():
        raise MigrationError('Mount the destination disk and create its parent directory first.')
    return path


def engine_args(service):
    if isinstance(service, list):
        return service
    lines = service.replace('\\\n', ' ').splitlines()
    commands = [line.split('=', 1)[1].strip() for line in lines if line.startswith('ExecStart=')]
    if not commands:
        raise MigrationError('Cannot read the validator command.')
    return shlex.split(commands[-1])


def infer_settings(core, node, service, legacy_env):
    """Translate actual endpoints/retention; never request a dump or archive download."""
    for key in ('fift', 'liteClient', 'validatorConsole'):
        if not isinstance(core.get(key), dict):
            raise MigrationError(f'Donor controller JSON is missing {key}.')
    if not core.get('validatorWalletName') or not core.get('adnlAddr'):
        raise MigrationError('Donor wallet/ADNL identity is missing; finish or repair its installation first.')
    for section in ('control', 'liteservers'):
        if len(node.get(section, [])) != 1:
            raise MigrationError(f'Multiple or missing {section} endpoints require manual review.')
    addrs = node.get('addrs', [])
    udp = [item for item in addrs if item.get('@type', 'engine.addr') == 'engine.addr']
    quic = [item for item in addrs if item.get('@type') == 'engine.quicAddr']
    if len(udp) != 1 or len(quic) > 1 or len(udp) + len(quic) != len(addrs):
        raise MigrationError('Multiple/proxied node addresses require manual review.')
    if len({item.get('ip') for item in addrs}) != 1:
        raise MigrationError('Different advertised IPs require manual review.')
    address = ipaddress.IPv4Address(int(udp[0]['ip']) & 0xffffffff)
    if not address.is_global:
        raise MigrationError('Donor must have an advertised public IPv4 address.')
    modes = core.get('modes', {})
    if not isinstance(modes, dict):
        raise MigrationError('The donor uses an older mode schema; convert it with the legacy controller before migration.')
    active = [name for name in ('validator', 'liteserver') if modes.get(name)]
    mode = legacy_env.get('MODE')
    if mode not in ('validator', 'liteserver') or mode not in active:
        mode = next((name for name in ('validator', 'liteserver') if name in active), None)
    if mode is None:
        raise MigrationError('Automatic migration supports existing validator and liteserver modes.')
    network = legacy_env.get('NETWORK', 'testnet' if legacy_env.get('TON_BRANCH') == 'testnet' else 'mainnet')
    settings = {'MODE': mode, 'NETWORK': network, 'PUBLIC_IP': str(address),
                'VALIDATOR_PORT': str(udp[0]['port']),
                'QUIC_PORT': str(quic[0]['port']) if quic else '',
                'VALIDATOR_CONSOLE_PORT': str(node['control'][0]['port']),
                'LITESERVER_PORT': str(node['liteservers'][0]['port']), 'STATE_TTL': ''}
    for name in ('VALIDATOR_PORT', 'VALIDATOR_CONSOLE_PORT', 'LITESERVER_PORT', 'QUIC_PORT'):
        if settings[name] and not 1 <= int(settings[name]) <= 65535:
            raise MigrationError(f'Invalid saved {name}.')
    if settings['VALIDATOR_CONSOLE_PORT'] == settings['LITESERVER_PORT']:
        raise MigrationError('Console and liteserver TCP ports collide.')
    args = engine_args(service)
    if not args or Path(args[0]).name != 'validator-engine':
        raise MigrationError('Unrecognized validator executable.')
    values = {}
    permanent = False
    shards = []
    has_shards = False
    safe_custom = []
    index = 1
    value_flags = ('--threads', '--global-config', '--db', '--logname', '--verbosity',
                   '--archive-ttl', '--state-ttl', '--add-shard')
    while index < len(args):
        flag = args[index]
        if '=' in flag:
            flag, value = flag.split('=', 1)
            args = args[:index] + [flag, value] + args[index + 1:]
        if flag in value_flags:
            if index + 1 >= len(args):
                raise MigrationError(f'Missing value for {flag}.')
            value = args[index + 1]
            if flag == '--add-shard':
                has_shards = True
                if not re.fullmatch(r'-?\d+:[0-9a-fA-F]+', value):
                    raise MigrationError('Unrecognized shard selector.')
                shards.append(value)
            else:
                values[flag] = value
                if flag in ('--threads', '--verbosity'):
                    if not value.isdigit():
                        raise MigrationError(f'Invalid {flag}.')
                    safe_custom.extend((flag, value))
            index += 2
        elif flag in ('-M', '--permanent-celldb', '--daemonize', '--skip-key-sync'):
            permanent |= flag == '--permanent-celldb'
            has_shards |= flag == '-M'
            if flag == '--skip-key-sync':
                safe_custom.append(flag)
            index += 1
        else:
            raise MigrationError(f'Unsupported engine option {flag}; review it before migration. The donor was not changed.')
    for flag, expected in (('--global-config', '/usr/bin/ton/global.config.json'),
                           ('--db', '/var/ton-work/db'), ('--logname', '/var/ton-work/log')):
        if flag in values and values[flag].rstrip('/') != expected:
            raise MigrationError(f'Custom {flag} paths require manual review.')
    archive_ttl = int(values.get('--archive-ttl', '2592000' if mode == 'liteserver' else '86400'))
    state_ttl = int(values['--state-ttl']) if '--state-ttl' in values else None
    if permanent:
        if archive_ttl != 10**9 or (state_ttl is not None and state_ttl != 10**9):
            raise MigrationError('Custom permanent-storage retention requires manual review.')
        settings['ARCHIVE_TTL'] = '-1'
    else:
        if archive_ttl <= 0 or (state_ttl is not None and state_ttl <= 0):
            raise MigrationError('Unsupported retention values; donor data was preserved.')
        settings['ARCHIVE_TTL'] = str(archive_ttl + (state_ttl or 0))
        if state_ttl is not None:
            settings['STATE_TTL'] = str(state_ttl)
    if has_shards:
        settings['ADD_SHARD'] = ' '.join(shards)
    custom = [item for flag in ('--threads', '--verbosity') if flag in values for item in (flag, values[flag])]
    if '--skip-key-sync' in safe_custom:
        custom.append('--skip-key-sync')
    settings['CUSTOM_PARAMETERS'] = shlex.join(custom)
    settings['VERBOSITY'] = values.get('--verbosity', '1')
    return settings


def ignored_controller_file(path):
    return any(part in ('venv', 'python-site-packages', '__pycache__') for part in path.parts) or path.name in ('mytoncore.log', 'mytonctrl.log')


def safe_files(root, exclude_controller=False):
    """Reject unresolved links; do not silently leave wallets/external data behind."""
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            relative = path.relative_to(root)
            controller_relative = relative if root.name in ('mytoncore', 'mytonctrl') else (
                Path(*relative.parts[1:]) if relative.parts[0] in ('mytoncore', 'mytonctrl') else None)
            if exclude_controller and controller_relative is not None and ignored_controller_file(controller_relative):
                if name in directories:
                    directories.remove(name)
                continue
            if path.is_symlink():
                raise MigrationError(f'Unresolved data link requires review: {path}')
            if path.is_file():
                yield path
            elif name not in directories:
                raise MigrationError(f'Unsupported nonregular data file: {path}')


def normalize_identity(root):
    root = Path(root)
    identity = root / 'identity'
    list(safe_files(identity, exclude_controller=True))
    node = json.loads((identity / 'db/config.json').read_text())
    path = identity / 'mytoncore/mytoncore.db'
    core = json.loads(path.read_text())
    if len(node.get('control', [])) != 1 or len(node.get('liteservers', [])) != 1:
        raise MigrationError('Multiple or missing controller endpoints require review.')
    wallet = core.get('validatorWalletName', '')
    if not wallet or Path(wallet).name != wallet or not core.get('adnlAddr'):
        raise MigrationError('Saved wallet/ADNL identity is incomplete.')
    if not (identity / 'mytoncore/wallets' / (wallet + '.pk')).is_file():
        raise MigrationError('The validator wallet private key is missing or uses a custom path.')
    core['validatorConsole']['addr'] = '127.0.0.1:' + str(node['control'][0]['port'])
    # Older liteservers may omit validator=False. The new default must not
    # silently enable staking during startup before the verification step.
    for mode in ('validator', 'liteserver'):
        core['modes'].setdefault(mode, False)
    core['liteClient']['liteServer']['ip'] = '127.0.0.1'
    core['liteClient']['liteServer']['port'] = node['liteservers'][0]['port']
    core['paths'] = {'ton_work': '/var/ton-work/', 'ton_db': '/var/ton-work/db/',
                     'ton_keys': '/var/ton-work/keys/', 'ton_src': '/usr/src/ton/',
                     'ton_bin': '/usr/bin/ton/', 'mtc_src': '/usr/src/mytonctrl/', 'src_dir': '/usr/src/'}
    core['fift'].update(appPath='/usr/bin/ton/crypto/fift', libsPath='/usr/src/ton/crypto/fift/lib',
                        smartcontsPath='/usr/src/ton/crypto/smartcont')
    core['liteClient'].update(appPath='/usr/bin/ton/lite-client/lite-client', configPath='/usr/bin/ton/global.config.json')
    core['liteClient']['liteServer']['pubkeyPath'] = '/var/ton-work/keys/liteserver.pub'
    core['validatorConsole'].update(appPath='/usr/bin/ton/validator-engine-console/validator-engine-console',
                                    privKeyPath='/var/ton-work/keys/client', pubKeyPath='/var/ton-work/keys/server.pub')
    path.write_text(json.dumps(core, indent=2))
    os.chmod(path, 0o600)
    hashes = {}
    for base, destination in (('db/keyring', 'db/keyring'), ('keys', 'keys'),
                              ('mytoncore/wallets', 'controller/mytoncore/wallets')):
        files = list(safe_files(identity / base))
        if not files:
            raise MigrationError(f'The donor has no files in {base}.')
        for source in files:
            target = str(Path(destination) / source.relative_to(identity / base))
            hashes[target] = hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


def create_backup(root):
    root = Path(root)
    identity = root / 'identity'
    files = list(safe_files(identity, exclude_controller=True))
    backup = root / 'backup.tar.gz'
    # All remaining entries are regular files/directories. Dereference hard links
    # so the runtime's stricter backup validator receives actual file contents.
    with tarfile.open(backup, 'w:gz', dereference=True) as archive:
        directories = {identity / name for name in ('mytoncore', 'keys', 'db')}
        for path in files:
            directories.update(parent for parent in path.parents if identity in parent.parents)
        for path in sorted(directories, key=lambda item: (len(item.parts), str(item))):
            archive.add(path, arcname=str(path.relative_to(identity)), recursive=False)
        for path in files:
            archive.add(path, arcname=str(path.relative_to(identity)), recursive=False)
    os.chmod(backup, 0o600)
    return backup


def copy_controller(source, destination):
    destination.mkdir(parents=True, exist_ok=False)
    for path in safe_files(source, exclude_controller=True):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def verify_keys(work, hashes):
    for name, expected in hashes.items():
        path = Path(work) / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise MigrationError(f'Key/wallet preservation check failed: {name}. Stop and use the saved rollback instructions.')


def download(url):
    with urlopen(url, timeout=60) as response:
        content = response.read(8 * 1024 * 1024)
    if not content:
        raise MigrationError(f'Download is empty: {url}')
    return content


def zero_state(config):
    state = config.get('validator', {}).get('zero_state', {})
    return (state.get('root_hash'), state.get('file_hash'))


def migration_space_plan(probe, log_bytes=0, block_size=4096):
    """Budget every retained copy; sparse files and compression get no credit."""
    block_size = max(4096, block_size)

    def stored_files(files):
        directories = {str(parent) for name in files for parent in Path(name).parents}
        return sum(files.values()) + (2 * len(files) + len(directories)) * block_size

    core = {name: size for name, size in probe['sizes'].items() if name.startswith('mytoncore/')}
    console = {name: size for name, size in probe['sizes'].items() if name.startswith('mytonctrl/')}
    identity = {name: size for name, size in probe['sizes'].items()
                if name.startswith(('mytoncore/', 'ton-work/keys/', 'ton-work/db/keyring/'))
                or name in ('ton-work/db/config.json', 'ton-work/db/collators-list.json')}
    # Full legacy copies include virtual environments/cache excluded from the
    # identity inventory. Docker cp also copies those trees and normal log files.
    copied = sum(item['bytes'] + 2 * item['entries'] * block_size
                 for item in probe['copy_totals'].values())
    identity_bytes = stored_files(identity)
    core_bytes = stored_files(core)
    # Allow tar/PAX padding and gzip overhead even for incompressible contents.
    archive_bytes = identity_bytes + (identity_bytes + 99) // 100 + 10240
    plan = {'copy': copied + log_bytes + probe['config_bytes'],
            'stage': identity_bytes + stored_files(console) + probe['config_bytes'],
            'archive': archive_bytes, 'prime': core_bytes,
            'startup': core_bytes,  # Installer also retains mytoncore.db.backup.
            'restore': identity_bytes}
    peak = sum(plan[name] for name in ('copy', 'stage', 'archive', 'prime', 'startup'))
    # Keep the original reserve at later checkpoints, including initial node growth.
    plan['reserve'] = max(2**30, (peak + 9) // 10)
    return plan


def check_disk_space(requirements):
    """Combine allocations on the same filesystem instead of counting free space twice."""
    filesystems = {}
    for label, path, required in requirements:
        path = Path(path)
        device = path.stat().st_dev
        available = shutil.disk_usage(path).free
        group = filesystems.setdefault(device, {'path': path, 'labels': [], 'required': 0, 'free': available})
        group['labels'].append(label)
        group['required'] += required
        group['free'] = min(group['free'], available)
    for group in filesystems.values():
        label = ' + '.join(group['labels'])
        print(f"Disk space ({label}, {group['path']}): required {group['required'] / 2**30:.2f} GiB; "
              f"available {group['free'] / 2**30:.2f} GiB.")
        if group['free'] < group['required']:
            raise MigrationError(f"Not enough free disk space for {label}: need {group['required'] / 2**30:.2f} GiB, "
                                 f"available {group['free'] / 2**30:.2f} GiB on {group['path']}. "
                                 'Free space or select a larger destination; original data was preserved.')


def docker_storage_paths(inspected, root):
    """Volumes and writable layers may be mounted on different host filesystems."""
    root = Path(root)
    volumes = root / 'volumes'
    volumes = volumes if volumes.is_dir() else root
    upper = inspected.get('GraphDriver', {}).get('Data', {}).get('UpperDir')
    if upper:
        writable = Path(upper)
        if not writable.is_absolute() or not writable.is_dir():
            raise MigrationError('Cannot inspect the Docker writable-layer filesystem on this host.')
        return volumes, writable
    # Docker's managed containerd and the standard system containerd store can
    # also be independent mounts. Do not charge their data to DockerRootDir.
    driver = inspected.get('GraphDriver', {}).get('Name')
    candidates = {'overlay2': (root / 'overlay2',), 'vfs': (root / 'vfs',), 'btrfs': (root / 'btrfs',)}
    containerd = (root / 'containerd/daemon/io.containerd.snapshotter.v1.overlayfs',
                  Path('/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs'))
    found = [path for path in candidates.get(driver, containerd if driver in (None, '', 'overlayfs') else ())
             if path.is_dir()]
    if len({path.stat().st_dev for path in found}) > 1:
        raise MigrationError('Multiple containerd storage filesystems detected; confirm the active Docker store before migration.')
    if found:
        return volumes, found[0]
    raise MigrationError('Cannot determine Docker writable storage for the disk-space check; original node was not stopped.')


SOURCE_PROBE = r'''
import hashlib, json, os, stat
from pathlib import Path
def read(path):
    return json.loads(Path(path).read_text())
node = read('/var/ton-work/db/config.json')
core = read('/usr/local/bin/mytoncore/mytoncore.db')
commands = []
for proc in Path('/proc').glob('[0-9]*'):
    try:
        args = (proc / 'cmdline').read_bytes().decode().strip('\0').split('\0')
        if args and Path(args[0]).name == 'validator-engine': commands.append(args)
    except (OSError, UnicodeError): pass
if len(commands) > 1: raise SystemExit('Expected at most one validator-engine')
sizes, hashes, links, copy_totals = {}, {}, [], {}
for name, location in [('ton-work', '/var/ton-work'), ('mytoncore', '/usr/local/bin/mytoncore'), ('mytonctrl', '/usr/local/bin/mytonctrl')]:
    base = Path(location)
    # Separate unfiltered accounting: docker cp retains ignored venv/cache/logs.
    total, entries = 0, 1
    for directory, directories, files in os.walk(base, followlinks=False):
        for child in directories + files:
            info = (Path(directory) / child).lstat()
            entries += 1
            if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                total += info.st_size
    copy_totals[name] = dict(bytes=total, entries=entries)
    for directory, directories, files in os.walk(base, followlinks=False):
        for child in directories + files:
            path = Path(directory) / child
            relative = path.relative_to(base)
            if name != 'ton-work' and (any(p in ('venv', 'python-site-packages', '__pycache__') for p in relative.parts) or child in ('mytoncore.log', 'mytonctrl.log')):
                if child in directories: directories.remove(child)
                continue
            key = name + '/' + str(relative)
            if path.is_symlink():
                if name == 'ton-work' and len(relative.parts) == 1 and child.startswith('log') and '/fd/' in os.readlink(path) and os.readlink(path).startswith('/proc/'):
                    links.append(key)
                    continue
                raise SystemExit('Unresolved data symlink: ' + key)
            if path.is_file():
                sizes[key] = path.stat().st_size
                if name == 'mytoncore' and relative.parts[0] == 'wallets' or name == 'ton-work' and relative.parts[0] == 'keys' or name == 'ton-work' and relative.parts[:2] == ('db', 'keyring'):
                    hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            elif child not in directories:
                raise SystemExit('Unsupported nonregular data file: ' + key)
configs, config_bytes = {}, 0
for name in ('global.config.json', 'local.config.json'):
    path = Path('/usr/bin/ton') / name
    if path.is_file():
        configs[name] = str(path.resolve(strict=True))
        config_bytes += path.stat().st_size
print(json.dumps(dict(node=node, core=core, command=commands[0] if commands else None, sizes=sizes, hashes=hashes, log_links=links, configs=configs, copy_totals=copy_totals, config_bytes=config_bytes)))
'''


class Wizard:
    def __init__(self, branch='master', tty=None):
        self.branch = branch
        self.tty = tty
        self.root = None
        self.old_id = None
        self.old_restart = 'no'
        self.donor_stopped = False
        self.destination_attempted = False
        self.compose = []
        self.compose_env = None
        self.project = ''
        self.settings = {}
        self.docker_root = None
        self.docker_volumes = None
        self.docker_writable = None
        self.artifact_bytes = 0
        self.log_bytes = 0

    def ask(self, title, default=None):
        suffix = f' [{default}]' if default is not None else ''
        print(title + suffix + ': ', end='', flush=True)
        value = self.tty.readline()
        if not value:
            raise MigrationError('Input ended; no confirmation was assumed.')
        return value.strip() or (str(default) if default is not None else '')

    def confirm(self, message):
        if self.ask(message + ' (type yes to continue)', 'no').lower() != 'yes':
            raise MigrationError('Cancelled. Existing data was preserved.')

    def compose_run(self, args, capture=False):
        return run(self.compose + args, capture=capture, env=self.compose_env)

    def journal(self, phase):
        if self.root and self.root.is_dir() and (phase == 'prepared' or (self.root / 'migration.json').is_file()):
            temporary = self.root / 'migration.json.tmp'
            temporary.write_text(json.dumps({'phase': phase, 'old_container': self.old_id,
                                             'project': self.project, 'settings': self.settings}, indent=2))
            temporary.replace(self.root / 'migration.json')

    def stop_destination(self):
        if self.destination_attempted:
            # Failure/interrupt must never leave two controllers running.
            self.compose_run(['stop', '--timeout', '120'], capture=True)
            self.destination_attempted = False

    def rollback_instructions(self):
        if not self.donor_stopped:
            return
        print('\nThe original container and all of its storage were retained. Both nodes must remain stopped before rollback.')
        print(f'Migration files: {self.root}')
        if self.compose:
            print('Logs: sudo ' + shlex.join(self.compose + ['logs', '--tail', '100']))
        print('Rollback: sudo bash ' + shlex.quote(str(self.root / 'rollback.sh')))
        print('Before rollback, reconcile any election/stake/wallet transactions broadcast by the new controller.')

    def validate_host(self):
        if sys.platform != 'linux' or os.geteuid() != 0:
            raise MigrationError('Run on the Docker host with sudo bash migrate.sh (Linux, Python 3.8+, Docker Compose required).')
        for tool in ('docker', 'ss', 'findmnt'):
            if not shutil.which(tool):
                raise MigrationError(f'Install {tool} before running the wizard.')
        endpoint = os.environ.get('DOCKER_HOST')
        if not endpoint:
            context = json.loads(run(['docker', 'context', 'inspect']))[0]
            endpoint = context['Endpoints']['docker']['Host']
        if not endpoint.startswith('unix://') or not Path(endpoint[7:]).exists():
            raise MigrationError('Use a local Unix-socket Docker daemon on this host; remote/Desktop daemons are not supported.')
        run(['docker', 'info', '--format', '{{.OSType}}'])
        run(['docker', 'compose', 'version'])

    def image(self, label, default):
        value = self.ask(label, default)
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:/@-]*', value):
            raise MigrationError('Invalid image reference.')
        return value

    def probe(self):
        return json.loads(run(['docker', 'exec', self.old_id, 'python3', '-c', SOURCE_PROBE]))

    def measure_logs(self):
        # docker logs can include rotations and non-file logging drivers. Count
        # the actual export stream without writing it or keeping it in memory.
        with subprocess.Popen(['docker', 'logs', '--timestamps', self.old_id], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as process:
            size = sum(len(chunk) for chunk in iter(lambda: process.stdout.read(1024 * 1024), b''))
            if process.wait():
                raise MigrationError('Cannot measure the original container log export.')
        return size

    def check_space(self, probe, phase='copy'):
        destination = self.root if self.root.exists() else self.root.parent
        volumes = self.docker_volumes or self.docker_root
        writable = self.docker_writable or self.docker_root
        block = max(os.statvfs(path).f_frsize for path in (destination, volumes, writable))
        plan = migration_space_plan(probe, self.log_bytes, block)
        phases = ('copy', 'stage', 'archive', 'prime', 'startup')
        remaining = sum(plan[name] for name in phases[phases.index(phase):])
        # Backup extraction in /tmp and the artifact volume plus /run snapshot
        # all live in Docker storage, rather than necessarily on the data disk.
        docker_bytes = plan['restore'] + self.artifact_bytes
        docker_reserve = max(2**30, (docker_bytes + 9) // 10)
        artifact_reserve = max(2**30, (self.artifact_bytes + 9) // 10)
        if writable.stat().st_dev == volumes.stat().st_dev:
            # One reserve for Docker allocations sharing a filesystem.
            docker_reserve = max(2**30, (docker_bytes + self.artifact_bytes + 9) // 10)
            artifact_reserve = 0
        check_disk_space([('migration data', destination, remaining + plan['reserve']),
                          ('Docker restore/snapshot', writable, docker_bytes + docker_reserve),
                          ('Docker artifact volumes', volumes, self.artifact_bytes + artifact_reserve)])

    def execute(self):
        self.validate_host()
        print('MyTonCtrl migration wizard: same-host, offline copy; original data is never removed.\n')
        print(run(['docker', 'ps', '--format', 'table {{.Names}}\t{{.Image}}\t{{.Status}}']))
        old_name = self.ask('Existing ton-docker-ctrl container name or ID')
        inspected = json.loads(run(['docker', 'inspect', old_name]))[0]
        self.old_id = inspected['Id']
        restart = inspected.get('HostConfig', {}).get('RestartPolicy', {})
        self.old_restart = restart.get('Name') or 'no'
        if self.old_restart == 'on-failure' and restart.get('MaximumRetryCount'):
            self.old_restart += ':' + str(restart['MaximumRetryCount'])
        if not inspected['State']['Running']:
            raise MigrationError('Start the healthy original node before migration so its actual settings can be detected.')
        mounts = inspected.get('Mounts', [])
        for required in ('/var/ton-work', '/usr/local/bin/mytoncore', '/usr/local/bin/mytonctrl'):
            if not any(item['Destination'].rstrip('/') == required and Path(item['Source']).is_dir() for item in mounts):
                raise MigrationError(f'Missing standard donor mount {required}; custom layouts require review.')
        old_env = parse_env('\n'.join(inspected['Config'].get('Env') or []))
        print('Inspecting the running node and controller; large file inventories may take time...')
        probe = self.probe()
        if not probe['command']:
            raise MigrationError('The donor validator is not running; repair the original node before migration.')
        self.settings = infer_settings(probe['core'], probe['node'], probe['command'], old_env)
        for name, value in probe['core'].get('paths', {}).items():
            expected = {'ton_work': '/var/ton-work', 'ton_db': '/var/ton-work/db', 'ton_keys': '/var/ton-work/keys'}
            if name in expected and value.rstrip('/') != expected[name]:
                raise MigrationError(f'Custom controller {name} path requires review.')
        wallet = probe['core']['validatorWalletName']
        if f'mytoncore/wallets/{wallet}.pk' not in probe['hashes']:
            raise MigrationError('The donor validator wallet private key is missing or external.')
        if f'mytoncore/wallets/{wallet}.addr' not in probe['hashes'] or not isinstance(probe['core']['liteClient'].get('liteServer'), dict):
            raise MigrationError('The saved wallet address or local liteserver configuration is incomplete.')
        for record, key, expected in ((probe['core']['validatorConsole'], 'privKeyPath', '/var/ton-work/keys/client'),
                                      (probe['core']['validatorConsole'], 'pubKeyPath', '/var/ton-work/keys/server.pub'),
                                      (probe['core']['liteClient']['liteServer'], 'pubkeyPath', '/var/ton-work/keys/liteserver.pub')):
            if record.get(key) != expected or 'ton-work/' + expected[len('/var/ton-work/'):] not in probe['hashes']:
                raise MigrationError(f'Missing or custom controller key {key}; resolve the legacy key layout first.')
        if 'global.config.json' not in probe['configs']:
            raise MigrationError('The donor network configuration is missing.')
        global_config = json.loads(run(['docker', 'exec', self.old_id, 'cat', probe['configs']['global.config.json']]))
        detected = []
        for network, filename in (('mainnet', 'global.config.json'), ('testnet', 'testnet-global.config.json')):
            canonical = json.loads(download('https://ton-blockchain.github.io/' + filename))
            if zero_state(global_config) == zero_state(canonical) and all(zero_state(global_config)):
                detected.append(network)
        if len(detected) != 1:
            raise MigrationError('Unrecognized/custom network zerostate; automatic migration supports mainnet and testnet.')
        self.settings['NETWORK'] = detected[0]
        for binding, records in (inspected.get('HostConfig', {}).get('PortBindings') or {}).items():
            if any(record.get('HostPort') != binding.split('/')[0] for record in records or []):
                raise MigrationError('Remapped bridge ports require manual review before switching to host networking.')
        active_services = run(['docker', 'exec', self.old_id, 'systemctl', 'list-units', '--type=service', '--state=running', '--no-legend', '--no-pager'])
        if re.search(r'\b(?:ton_storage|ton_http_api|ls_proxy|collator)\.service\b', active_services):
            raise MigrationError('Active auxiliary TON services require a separate migration; source was not stopped.')
        parent = Path(self.ask('New migration directory on the mounted data disk', '/mnt/ton/mytonctrl-migration'))
        self.root = ensure_destination_isolated(parent, [item['Source'] for item in mounts])
        filesystem = run(['findmnt', '-n', '-o', 'TARGET,SOURCE,FSTYPE', '--target', self.root.parent])
        print(f'Destination filesystem: {filesystem.strip()}')
        self.docker_root = Path(run(['docker', 'info', '--format', '{{.DockerRootDir}}']).strip())
        if not self.docker_root.is_absolute() or not self.docker_root.is_dir():
            raise MigrationError('Cannot inspect Docker storage on this host for the migration space check.')
        self.docker_volumes, self.docker_writable = docker_storage_paths(inspected, self.docker_root)
        self.log_bytes = self.measure_logs()
        self.check_space(probe)
        print('Space includes staging, backup creation/restoration and at least 10% or 1 GiB reserve per storage area.')
        if filesystem.split()[0] == '/':
            self.confirm('The destination is on the root filesystem. Use this disk anyway?')
        tag = 'dev' if self.branch == 'dev' else 'latest'
        controller_image = self.image('New MyTonCtrl image', 'ghcr.io/neodix42/mytonctrl:' + tag)
        ton_default = 'ghcr.io/ton-blockchain/ton:v2026.08-amd64' if platform.machine() == 'x86_64' else None
        ton_image = self.image('Official TON image (choose a compatible tag for this host; upgrade separately)', ton_default)
        self.project = 'mytonctrl-migrated-' + time.strftime('%Y%m%d%H%M%S') + '-' + str(os.getpid())
        self.settings.update(MYTONCTRL_IMAGE=controller_image, TON_IMAGE=ton_image,
                             TON_WORK_HOST_DIR=str(self.root / 'ton-work'),
                             TON_ARTIFACTS_VOLUME=self.project + '-artifacts', TON_SCRIPTS_VOLUME=self.project + '-scripts',
                             TON_WORK_VOLUME=self.project + '-unused-work')
        args = ['-m', self.settings['MODE'], '-n', self.settings['NETWORK'], '-p', '/migration/backup.tar.gz']
        if probe['core'].get('sendTelemetry') is False:
            args.append('-t')
        self.settings['MYTONCTRL_ARGS'] = shlex.join(args)
        base = f'https://raw.githubusercontent.com/neodiX42/mytonctrl/{self.branch}'
        template = download(base + '/.env.example').decode()
        compose = download(base + '/docker/compose.yml').decode()
        print('\nMigration plan:')
        for key in ('NETWORK', 'MODE', 'PUBLIC_IP', 'VALIDATOR_PORT', 'QUIC_PORT', 'VALIDATOR_CONSOLE_PORT', 'LITESERVER_PORT', 'ARCHIVE_TTL', 'STATE_TTL', 'MYTONCTRL_IMAGE', 'TON_IMAGE'):
            print(f'  {key}={self.settings[key]}')
        print('  Database/history, cached dumps, wallets, keys and controller settings will be copied.')
        print('  No dump/archive download. Original container, image and volumes remain available for rollback.')
        print('  New Compose uses host networking. Retain UDP/QUIC/liteserver firewall access; keep the console port private.')
        print('  Keep an independent backup/snapshot, especially for archive nodes.')
        self.confirm('Prepare this separate destination and pull the selected images?')
        ensure_destination_isolated(self.root, [item['Source'] for item in mounts])
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / 'deployment').mkdir(exist_ok=True)
        self.write_deployment(template, compose)
        (self.root / 'legacy').mkdir()
        (self.root / 'legacy/container.json').write_text(json.dumps(inspected, indent=2))
        (self.root / 'legacy/validator-command.json').write_text(json.dumps(probe['command']))
        self.write_rollback()
        self.journal('prepared')
        self.compose_run(['config', '--quiet'], capture=True)
        self.compose_run(['pull'])
        run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--workdir', '/tmp',
             '--entrypoint', '/opt/mytonctrl/venv/bin/python', controller_image, '-c',
             'import sys; sys.path.insert(0,"/usr/local/lib/mytonctrl"); from entrypoint import check_backup; from mytoninstaller.settings import update_client_path_settings'])
        footprint = run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only',
                         '--entrypoint', 'du', ton_image, '-sbL', '--count-links',
                         '/usr/local/bin', '/usr/lib/fift', '/usr/share/ton/smartcont'])
        self.artifact_bytes = sum(int(line.split()[0]) for line in footprint.splitlines())
        if len(footprint.splitlines()) != 3 or self.artifact_bytes <= 0:
            raise MigrationError('Cannot measure the selected TON image artifacts.')
        # Image downloads have already consumed their disk space. Charge only
        # the remaining work, then refresh again after the user's confirmation.
        self.check_space(probe)
        self.confirm('Stop the original controller/node now and copy all data? This starts downtime.')
        print('Rechecking current source sizes and free space before stopping the original node...')
        self.log_bytes = self.measure_logs()
        self.check_space(self.probe())
        # Once stopping begins, errors leave the donor stopped; restarting is an explicit rollback.
        self.donor_stopped = True
        self.journal('stopping-donor')
        if self.old_restart != 'no':
            run(['docker', 'update', '--restart', 'no', self.old_id])
        run(['docker', 'exec', self.old_id, 'systemctl', 'stop', 'mytoncore'])
        offline = self.probe()
        identity_fields = ('validatorWalletName', 'adnlAddr', 'modes')
        node_fields = ('addrs', 'control', 'liteservers', 'fullnode')
        if (any(offline['node'].get(key) != probe['node'].get(key) for key in node_fields)
                or any(offline['core'].get(key) != probe['core'].get(key) for key in identity_fields)
                or offline['command'] != probe['command']):
            raise MigrationError('Donor configuration changed during planning; inspect the saved migration and retry in a new directory.')
        run(['docker', 'exec', self.old_id, 'systemctl', 'stop', 'validator'])
        # Inventory only after the writer has exited: active RocksDB files change size.
        offline = self.probe()
        if offline['command'] is not None:
            raise MigrationError('The donor validator did not stop cleanly; no database copy was made.')
        if (any(offline['node'].get(key) != probe['node'].get(key) for key in node_fields)
                or any(offline['core'].get(key) != probe['core'].get(key) for key in identity_fields)):
            raise MigrationError('Donor settings changed during migration planning; retained donor needs review.')
        run(['docker', 'stop', '--time', '120', self.old_id], capture=False)
        if run(['docker', 'inspect', self.old_id, '--format', '{{.State.Running}}']).strip() != 'false':
            raise MigrationError('The donor container is still running.')
        self.log_bytes = self.measure_logs()
        self.check_space(offline)
        self.journal('copying')
        print('Copying stopped node data. This can take hours for an archive; keep this terminal open.')
        self.copy_data(offline)
        self.check_space(offline, phase='stage')
        self.stage_import()
        hashes = normalize_identity(self.root)
        (self.root / 'key-checksums.json').write_text(json.dumps(hashes, indent=2))
        self.check_space(offline, phase='archive')
        backup = create_backup(self.root)
        run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--workdir', '/tmp',
             '--entrypoint', '/opt/mytonctrl/venv/bin/python', '--mount', f'type=bind,src={backup},dst=/migration/backup.tar.gz,readonly',
             controller_image, '-c', 'import sys; from pathlib import Path; sys.path.insert(0,"/usr/local/lib/mytonctrl"); from entrypoint import check_backup; check_backup(Path("/migration/backup.tar.gz"))'])
        copy_controller(self.root / 'identity/mytoncore', self.root / 'ton-work/controller/mytoncore')
        verify_keys(self.root / 'ton-work', hashes)
        self.check_ports()
        self.journal('copied-and-validated')
        self.confirm('Offline copy and keys verified. Start the new node now?')
        self.check_space(offline, phase='startup')
        self.destination_attempted = True
        self.journal('starting-destination')
        self.compose_run(['up', '-d', '--no-build', '--pull', 'never'])
        print('Waiting up to 15 minutes for controller initialization; dump data will not be downloaded again.')
        marker = self.root / 'ton-work/controller/initialized.json'
        deadline = time.monotonic() + 900
        while not marker.is_file():
            if time.monotonic() >= deadline:
                raise MigrationError('Initialization did not finish in 15 minutes. Copied data was retained; inspect deployment logs before retrying.')
            time.sleep(5)
        # The marker precedes final service activation; wait for both services.
        while True:
            try:
                status = self.compose_run(['exec', '-T', 'mytonctrl', 'systemctl', 'show', 'validator', '--property=ActiveState', '--value'], capture=True).strip()
                controller_status = self.compose_run(['exec', '-T', 'mytonctrl', 'systemctl', 'show', 'mytoncore', '--property=ActiveState', '--value'], capture=True).strip()
                if status == controller_status == 'active':
                    break
            except MigrationError:
                pass  # A container may briefly restart during final service activation.
            if time.monotonic() >= deadline:
                raise MigrationError('Migrated services are not active; destination stopped for review.')
            time.sleep(3)
        self.verify_runtime(hashes, offline)
        self.journal('verified')
        print('\nMigration initialized and original keys verified. Review status and synchronization:')
        self.compose_run(['exec', '-T', 'mytonctrl', 'mytonctrl', '--cmd', 'status'])
        print('\nKeep the original storage and backup. Archive nodes also need historical liteserver-query verification.')
        print('Deployment: ' + str(self.root / 'deployment'))
        print('Use the printed Compose prefix for logs, upgrades and stopping the migrated node:')
        print(shlex.join(self.compose))
        self.rollback_instructions()

    def write_deployment(self, template, compose):
        values = parse_env(template)
        for key in ('DUMP', 'ARCHIVE', 'ARCHIVE_BLOCKS', 'ONLY_NODE', 'ONLY_MTC', 'BACKUP', 'MYTONCTRL_ENV_FILE',
                    'MODE', 'NETWORK', 'ADD_SHARD', 'GLOBAL_CONFIG_URL', 'GLOBAL_CONFIG_FILE', 'CONFIG_URL',
                    'MYTONCTRL_CONFIG', 'MYTONCTRL_WALLETS', 'MYTONCTRL_CMD'):
            values.pop(key, None)
        values.update(self.settings)
        # Single-quoted dotenv values remain literal, including dollars in paths.
        for key, value in values.items():
            if '\n' in value or '\r' in value or "'" in value:
                raise MigrationError('An environment value cannot safely be represented in dotenv.')
        deployment = self.root / 'deployment'
        env_path = deployment / '.env'
        existing_env = env_path.exists() or env_path.is_symlink()
        if existing_env:
            if env_path.is_symlink() or not env_path.is_file() or env_path.stat().st_nlink != 1:
                raise MigrationError('Existing .env must be a regular file without links.')
            self.confirm(f'{env_path} already exists. Replace it with the migration settings?')
        # Reused setup directories must protect the later wallet/key copies too.
        # Do this after consent so declining preserves their original permissions.
        self.root.chmod(0o700)
        deployment.chmod(0o700)
        if existing_env:
            previous = env_path.read_bytes()
            suffix = 0
            while True:
                backup = deployment / ('.env.before-migration' + (f'.{suffix}' if suffix else ''))
                try:
                    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    suffix += 1
                    continue
                with os.fdopen(descriptor, 'wb') as output:
                    os.fchmod(output.fileno(), 0o600)
                    output.write(previous)
                break
            print(f'Previous .env saved to {backup}')
        descriptor, temporary = tempfile.mkstemp(prefix='.env.', dir=deployment)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write('# Generated by migrate.sh; retention applies before first startup.\n' +
                             ''.join(f"{key}='{value}'\n" for key, value in values.items()))
            Path(temporary).replace(env_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        (deployment / 'compose.yml').write_text(compose)
        override = {'services': {'mytonctrl': {'volumes': [{'type': 'bind', 'source': str(self.root / 'backup.tar.gz'),
                                                          'target': '/migration/backup.tar.gz', 'read_only': True,
                                                          'bind': {'create_host_path': False}}]}}}
        (deployment / 'migration.override.json').write_text(json.dumps(override, indent=2))
        self.compose = ['docker', 'compose', '--project-name', self.project, '--env-file', str(deployment / '.env'),
                        '-f', str(deployment / 'compose.yml'), '-f', str(deployment / 'migration.override.json')]
        self.compose_env = {key: value for key, value in os.environ.items()
                            if key not in values and not key.startswith('COMPOSE_') and key != 'MYTONCTRL_ENV_FILE'}
        self.compose_keys = set(values) | {'MYTONCTRL_ENV_FILE', 'COMPOSE_FILE', 'COMPOSE_PROJECT_NAME', 'COMPOSE_PROFILES', 'COMPOSE_ENV_FILES'}

    def write_rollback(self):
        script = self.root / 'rollback.sh'
        script.write_text('#!/usr/bin/env bash\nset -euo pipefail\n' +
                          "printf 'Stop the new deployment and restart the original node? Reconcile any new staking transactions first. Type yes: '\n" +
                          "read -r answer </dev/tty\n[[ \"$answer\" == yes ]] || exit 1\n" +
                          shlex.join(['env'] + [item for key in sorted(self.compose_keys | (set(os.environ) - set(self.compose_env)))
                                              for item in ('-u', key)] + self.compose + ['stop', '--timeout', '120']) + '\n' +
                          shlex.join(['docker', 'update', '--restart', self.old_restart, self.old_id]) + '\n' +
                          shlex.join(['docker', 'start', self.old_id]) + '\n')
        script.chmod(0o700)

    def copy_data(self, offline):
        for name, source in (('ton-work', '/var/ton-work'), ('legacy/mytoncore', '/usr/local/bin/mytoncore'),
                              ('legacy/mytonctrl', '/usr/local/bin/mytonctrl')):
            target = self.root / name
            target.mkdir()
            run(['docker', 'cp', '-a', self.old_id + ':' + source + '/.', target], capture=False)
        runtime = self.root / 'legacy/ton-runtime'
        runtime.mkdir()
        for name, source in offline['configs'].items():
            run(['docker', 'cp', '-a', '-L', self.old_id + ':' + source, runtime / name])
        with (self.root / 'legacy/container.log').open('w') as output:
            subprocess.run(['docker', 'logs', '--timestamps', self.old_id], stdout=output, stderr=subprocess.STDOUT, check=True)
        for key, size in offline['sizes'].items():
            if key.startswith('ton-work/'):
                target = self.root / key
            else:
                target = self.root / 'legacy' / key
            if target.is_symlink() or not target.is_file() or target.stat().st_size != size:
                raise MigrationError(f'Offline copy inventory mismatch: {key}')
        for key, expected in offline['hashes'].items():
            target = self.root / key if key.startswith('ton-work/') else self.root / 'legacy' / key
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise MigrationError(f'Offline key/wallet checksum mismatch: {key}')
        for key in offline['log_links']:
            path = self.root / key
            if path.is_symlink():
                path.unlink()  # Only the independent destination; original stdout saved above.
        (self.root / 'offline-inventory.json').write_text(json.dumps(offline['sizes'], indent=2))

    def stage_import(self):
        work = self.root / 'ton-work'
        if (work / 'controller').exists():
            raise MigrationError('Existing container migration markers detected; use the appropriate recovery procedure.')
        list(safe_files(work))
        controller = work / 'controller'
        controller.mkdir()
        # The unprivileged engine follows /usr/bin/ton/global.config.json here.
        # Wallet/controller subdirectories remain private; network configs are public.
        controller.chmod(0o755)
        runtime = self.root / 'legacy/ton-runtime'
        for path in runtime.iterdir():
            json.loads(path.read_text())
            shutil.copy2(path, controller / path.name)
            (controller / path.name).chmod(0o644)
        copy_controller(self.root / 'legacy/mytonctrl', controller / 'mytonctrl')
        identity = self.root / 'identity'
        identity.mkdir()
        copy_controller(self.root / 'legacy/mytoncore', identity / 'mytoncore')
        shutil.copytree(work / 'keys', identity / 'keys')
        (identity / 'db').mkdir()
        shutil.copy2(work / 'db/config.json', identity / 'db/config.json')
        shutil.copytree(work / 'db/keyring', identity / 'db/keyring')
        collators = work / 'db/collators-list.json'
        if collators.is_file():
            shutil.copy2(collators, identity / 'db/collators-list.json')

    def check_ports(self):
        for protocol, names in ((socket.SOCK_STREAM, ('VALIDATOR_CONSOLE_PORT', 'LITESERVER_PORT')),
                                (socket.SOCK_DGRAM, ('VALIDATOR_PORT', 'QUIC_PORT'))):
            for name in names:
                if self.settings[name]:
                    with socket.socket(socket.AF_INET, protocol) as test_socket:
                        try:
                            test_socket.bind(('0.0.0.0', int(self.settings[name])))
                        except OSError as error:
                            raise MigrationError(f'{name} is already occupied; keep the donor stopped and review the conflicting process.') from error

    def verify_runtime(self, hashes, original):
        verify_keys(self.root / 'ton-work', hashes)
        core = json.loads((self.root / 'ton-work/controller/mytoncore/mytoncore.db').read_text())
        for field in ('validatorWalletName', 'adnlAddr'):
            if core.get(field) != original['core'].get(field):
                raise MigrationError(f'Saved {field} changed; the destination was stopped for review.')
        old_modes, new_modes = original['core'].get('modes', {}), core.get('modes', {})
        if isinstance(old_modes, dict) and isinstance(new_modes, dict):
            if any(new_modes.get(key) != value for key, value in old_modes.items()):
                raise MigrationError('Saved node modes changed; destination stopped for review.')
            if any(value for key, value in new_modes.items() if key not in old_modes):
                raise MigrationError('Unexpected node modes were enabled; destination stopped for review.')
        elif old_modes != new_modes:
            raise MigrationError('Saved node modes changed; destination stopped for review.')
        node = json.loads((self.root / 'ton-work/db/config.json').read_text())
        for field in ('fullnode', 'control', 'liteservers', 'addrs'):
            if node.get(field) != original['node'].get(field):
                raise MigrationError(f'Node {field} changed; the destination was stopped for review.')
        command = json.loads(self.compose_run(['exec', '-T', 'mytonctrl', 'python3', '-c', '''
import json
from pathlib import Path
commands = []
for path in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        args = path.read_bytes().decode().strip('\\0').split('\\0')
        if args and Path(args[0]).name == 'validator-engine': commands.append(args)
    except (OSError, UnicodeError): pass
print(json.dumps(commands))
'''], capture=True))
        if len(command) != 1:
            raise MigrationError('Expected one running destination validator-engine.')
        actual = infer_settings(core, node, command[0], {'NETWORK': self.settings['NETWORK'], 'MODE': self.settings['MODE']})
        for field in ('ARCHIVE_TTL', 'STATE_TTL', 'ADD_SHARD', 'CUSTOM_PARAMETERS'):
            if actual.get(field) != self.settings.get(field):
                raise MigrationError(f'Runtime {field} differs from the donor; destination stopped to protect retention.')


def main():
    parser = argparse.ArgumentParser(prog='migrate.sh', description='Interactive same-host migration from ton-docker-ctrl; preserves the original container/storage for rollback.')
    parser.add_argument('--branch', choices=('master', 'dev'), default='master', help='Branch for downloaded .env and Compose assets (default: master).')
    args = parser.parse_args()
    try:
        tty = open('/dev/tty', 'r')
    except OSError:
        print('Use an interactive terminal: sudo bash migrate.sh (download it before running).', file=sys.stderr)
        return 1
    wizard = Wizard(args.branch, tty)
    previous_umask = os.umask(0o077)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    for name in ('SIGTERM', 'SIGHUP'):
        signal.signal(getattr(signal, name), interrupted)
    try:
        wizard.execute()
        return 0
    except (MigrationError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print('\nMigration stopped: ' + (str(error) or 'interrupted'), file=sys.stderr)
        try:
            wizard.stop_destination()
            if wizard.donor_stopped:
                run(['docker', 'stop', '--time', '120', wizard.old_id], capture=False)
            wizard.journal('stopped-for-review')
        except (MigrationError, OSError) as stop_error:
            print('Could not confirm destination shutdown: ' + str(stop_error), file=sys.stderr)
            print('Keep the original node stopped until the destination is confirmed stopped.', file=sys.stderr)
        wizard.rollback_instructions()
        return 1
    finally:
        tty.close()
        os.umask(previous_umask)


if __name__ == '__main__':
    sys.exit(main())
PY
