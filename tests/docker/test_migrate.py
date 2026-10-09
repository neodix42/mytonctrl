"""Check migration safeguards with disposable legacy data and fake Docker calls."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock


MIGRATE_SCRIPT = Path(__file__).resolve().parents[2] / "migrate.sh"


def load_wizard():
    """Load the standalone script's embedded Python without invoking its CLI."""
    source = MIGRATE_SCRIPT.read_text()
    match = re.search(r"<<'PY'\n(.*?)\nPY(?:\n|$)", source, re.DOTALL)
    if match is None:
        raise AssertionError("migrate.sh must contain its standalone Python wizard")
    module = types.ModuleType("migration_wizard_test")
    sys.modules[module.__name__] = module
    exec(compile(match.group(1), str(MIGRATE_SCRIPT), "exec"), module.__dict__)
    return module


def file_digests(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    }


NODE_CONFIG = {
    "addrs": [
        {"@type": "engine.addr", "ip": 1547602011, "port": 40303},
        {"@type": "engine.quicAddr", "ip": 1547602011, "port": 41303},
    ],
    "control": [{"port": 40304, "id": "console-key", "allowed": ["client-key"]}],
    "liteservers": [{"port": 40305, "id": "lite-key"}],
    "fullnode": "original-fullnode-key",
}

CORE_CONFIG = {
    "fift": {"appPath": "/usr/bin/ton/crypto/fift"},
    "liteClient": {
        "appPath": "/usr/bin/ton/lite-client/lite-client",
        "configPath": "/usr/bin/ton/global.config.json",
        "liteServer": {"ip": "192.0.2.1", "port": 30003,
                       "pubkeyPath": "/var/ton-work/keys/liteserver.pub"},
    },
    "validatorConsole": {
        "appPath": "/usr/bin/ton/validator-engine-console/validator-engine-console",
        "addr": "192.0.2.1:30002",
        "privKeyPath": "/var/ton-work/keys/client",
        "pubKeyPath": "/var/ton-work/keys/server.pub",
    },
    "validatorWalletName": "existing-wallet",
    "adnlAddr": "original-validator-adnl",
    "modes": {"validator": True, "nominator-pool": True, "liteserver": False},
    "customPools": ["original-pool"],
}


class MigrationFixture(unittest.TestCase):
    def setUp(self):
        self.wizard = load_wizard()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.donor = self.root / "donor"
        self.donor.mkdir()
        self.node = copy.deepcopy(NODE_CONFIG)
        self.core = copy.deepcopy(CORE_CONFIG)

    def create_legacy_data(self):
        files = {
            "ton-work/db/config.json": json.dumps(self.node),
            "ton-work/db/keyring/node-key": "unchanged-node-private-key",
            "ton-work/db/archive/history": "retained-block-history",
            "ton-work/db/celldb/state": "retained-cell-database",
            "ton-work/db/import/archive.slice": "retained-import-progress",
            "ton-work/keys/client": "unchanged-console-private-key",
            "ton-work/keys/server.pub": "unchanged-console-public-key",
            "ton-work/keys/liteserver.pub": "unchanged-liteserver-public-key",
            "ton-work/dump-cache/saved-dump.tar.lz": "retained-dump-cache",
            "mytoncore/mytoncore.db": json.dumps(self.core),
            "mytoncore/wallets/existing-wallet.pk": "unchanged-wallet-private-key",
            "mytoncore/wallets/existing-wallet.addr": "unchanged-wallet-address",
            "mytoncore/contracts/pool.json": "unchanged-contract-settings",
            "mytonctrl/mytonctrl.db": "retained-console-settings",
            "ton-runtime/global.config.json": json.dumps({"@type": "config.global", "validator": {}}),
            "ton-runtime/local.config.json": json.dumps({"@type": "config.local", "liteservers": []}),
        }
        for name, contents in files.items():
            destination = self.donor / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents)
        (self.donor / "mytoncore/mytoncore.log").symlink_to("/proc/999999/fd/1")
        return file_digests(self.donor)

    def stage_identity(self):
        before = self.create_legacy_data()
        migration = self.root / "migration"
        migration.mkdir()
        shutil.copytree(self.donor / "ton-work", migration / "ton-work", symlinks=True)
        shutil.copytree(self.donor, migration / "legacy", symlinks=True)
        identity = migration / "identity"
        identity.mkdir()
        shutil.copytree(self.donor / "mytoncore", identity / "mytoncore", symlinks=True)
        shutil.copytree(self.donor / "ton-work/keys", identity / "keys", symlinks=True)
        (identity / "db").mkdir()
        shutil.copyfile(self.donor / "ton-work/db/config.json", identity / "db/config.json")
        shutil.copytree(self.donor / "ton-work/db/keyring", identity / "db/keyring", symlinks=True)
        return migration, before

    def test_environment_values_stay_literal_and_cannot_execute_shell_code(self):
        marker = self.root / "must-not-exist"
        values = self.wizard.parse_env(
            "# Legacy settings\n"
            "NETWORK=testnet\n"
            "MYTONCTRL_ARGS='-m validator -n testnet'\n"
            f"UNTRUSTED=$(touch {marker})\n"
            f"BACKTICKS=`touch {marker}`\n"
        )
        self.assertEqual(values["NETWORK"], "testnet")
        self.assertEqual(values["MYTONCTRL_ARGS"], "-m validator -n testnet")
        self.assertIn("$(touch", values["UNTRUSTED"])
        self.assertIn("`touch", values["BACKTICKS"])
        self.assertFalse(marker.exists())

    def test_destination_refuses_ancestor_descendant_equal_and_symlink_overlap(self):
        source = self.donor / "ton-work"
        source.mkdir()
        alias = self.root / "source-alias"
        alias.symlink_to(source, target_is_directory=True)
        for destination in (source, source / "new-deployment", source.parent, alias / "new"):
            with self.subTest(destination=destination):
                with self.assertRaises(self.wizard.MigrationError):
                    self.wizard.ensure_destination_isolated(destination, [str(source)])
        isolated = self.root / "independent-storage" / "migration"
        isolated.parent.mkdir()
        self.assertEqual(self.wizard.ensure_destination_isolated(isolated, [str(source)]), isolated.resolve())
        self.assertFalse(isolated.exists(), "The guard must not create destination directories")

    def test_testnet_validator_ports_and_finite_retention_are_retained(self):
        service = (
            "[Service]\nExecStart=/usr/bin/ton/validator-engine/validator-engine "
            "--threads 127 --global-config /usr/bin/ton/global.config.json "
            "--db /var/ton-work/db --archive-ttl 86400 --state-ttl 3600 -M\n"
        )
        settings = self.wizard.infer_settings(self.core, self.node, service, {"TON_BRANCH": "testnet"})
        expected = {
            "MODE": "validator", "NETWORK": "testnet", "PUBLIC_IP": "92.62.136.91",
            "VALIDATOR_PORT": "40303", "VALIDATOR_CONSOLE_PORT": "40304",
            "LITESERVER_PORT": "40305", "QUIC_PORT": "41303",
            "ARCHIVE_TTL": "90000", "STATE_TTL": "3600", "ADD_SHARD": "",
        }
        for name, value in expected.items():
            with self.subTest(setting=name):
                self.assertEqual(str(settings[name]), value)

    def test_archive_liteserver_preserves_permanent_storage_without_downloader(self):
        self.core["modes"] = {"validator": False, "liteserver": True}
        service = (
            "[Service]\nExecStart=/usr/bin/ton/validator-engine/validator-engine "
            "--permanent-celldb --archive-ttl 1000000000 --state-ttl 1000000000\n"
        )
        settings = self.wizard.infer_settings(self.core, self.node, service, {"NETWORK": "mainnet"})
        self.assertEqual(settings["MODE"], "liteserver")
        self.assertEqual(settings["NETWORK"], "mainnet")
        self.assertEqual(str(settings["ARCHIVE_TTL"]), "-1")
        self.assertFalse(settings.get("STATE_TTL"))
        self.assertNotIn("ARCHIVE_BLOCKS", settings)
        self.assertNotIn("ARCHIVE", settings)
        self.assertNotIn("DUMP", settings)
        self.assertNotIn("ADD_SHARD", settings)

    def test_liteserver_missing_validator_mode_is_staged_disabled_before_startup(self):
        self.core["modes"] = {"liteserver": True}
        migration, before = self.stage_identity()
        self.wizard.normalize_identity(migration)
        staged = json.loads((migration / "identity/mytoncore/mytoncore.db").read_text())
        self.assertEqual(staged["modes"], {"liteserver": True, "validator": False})
        original = json.loads((self.donor / "mytoncore/mytoncore.db").read_text())
        self.assertEqual(original["modes"], {"liteserver": True})
        self.assertEqual(file_digests(self.donor), before)

    def test_unknown_legacy_mode_schema_requires_review(self):
        self.core["modes"] = ["liteserver"]
        with self.assertRaises(self.wizard.MigrationError):
            self.wizard.infer_settings(self.core, self.node,
                                       ["/usr/bin/ton/validator-engine/validator-engine"], {})

    def test_multiple_endpoints_require_review_instead_of_silently_rekeying(self):
        self.node["control"].append({"port": 40314, "id": "second-console-key"})
        with self.assertRaises(self.wizard.MigrationError):
            self.wizard.infer_settings(self.core, self.node, "[Service]\nExecStart=/bin/validator\n", {})

    def test_normalized_backup_keeps_wallets_keys_settings_and_complete_work_copy(self):
        migration, before = self.stage_identity()
        (migration / "identity/mytoncore/wallets/existing-wallet.pk").chmod(0o600)
        (migration / "identity/mytoncore/venv").mkdir()
        (migration / "identity/mytoncore/venv/stale-interpreter").write_text("old image executable")
        self.wizard.normalize_identity(migration)
        self.assertEqual(file_digests(self.donor), before)
        self.assertEqual(file_digests(migration / "ton-work/db"),
                         file_digests(self.donor / "ton-work/db"))
        core = json.loads((migration / "identity/mytoncore/mytoncore.db").read_text())
        self.assertEqual(core["validatorConsole"]["addr"], "127.0.0.1:40304")
        self.assertEqual(core["liteClient"]["liteServer"]["ip"], "127.0.0.1")
        self.assertEqual(core["liteClient"]["liteServer"]["port"], 40305)
        for name in ("modes", "validatorWalletName", "adnlAddr", "customPools"):
            self.assertEqual(core[name], self.core[name])
        node = json.loads((migration / "identity/db/config.json").read_text())
        self.assertEqual(node, self.node)
        archive_path = self.wizard.create_backup(migration)
        self.assertEqual(stat.S_IMODE(archive_path.stat().st_mode), 0o600)
        docker_dir = MIGRATE_SCRIPT.parent / "docker"
        with mock.patch.object(sys, "path", [str(docker_dir), *sys.path]):
            spec = importlib.util.spec_from_file_location("migration_actual_entrypoint", docker_dir / "entrypoint.py")
            entrypoint = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(entrypoint)
            entrypoint.check_backup(archive_path)
        with tarfile.open(archive_path, "r:gz") as archive:
            members = {member.name: member for member in archive.getmembers()}
            self.assertNotIn("mytoncore/mytoncore.log", members)
            self.assertFalse(any(name.startswith("mytoncore/venv") for name in members))
            self.assertFalse(any(member.issym() or member.islnk() for member in members.values()))
            self.assertEqual(archive.extractfile("mytoncore/wallets/existing-wallet.pk").read(),
                             b"unchanged-wallet-private-key")
            self.assertEqual(members["mytoncore/wallets/existing-wallet.pk"].mode, 0o600)
            self.assertEqual(archive.extractfile("db/keyring/node-key").read(),
                             b"unchanged-node-private-key")
            self.assertEqual(archive.extractfile("keys/client").read(), b"unchanged-console-private-key")
        self.assertEqual(file_digests(self.donor), before)
        for name in ("archive/history", "celldb/state", "import/archive.slice"):
            self.assertEqual((migration / "ton-work/db" / name).read_bytes(),
                             (self.donor / "ton-work/db" / name).read_bytes())

    def test_backup_rejects_custom_escaping_symlink_and_preserves_source(self):
        migration, before = self.stage_identity()
        (migration / "identity/mytoncore/wallets/external.pk").symlink_to("/etc/shadow")
        with self.assertRaises(self.wizard.MigrationError):
            self.wizard.create_backup(migration)
        self.assertEqual(file_digests(self.donor), before)

    def test_help_and_noninteractive_execution_cannot_touch_docker(self):
        tools = self.root / "bin"
        tools.mkdir()
        docker_log = self.root / "docker-called"
        docker = tools / "docker"
        docker.write_text(
            f"#!{sys.executable}\n"
            "from pathlib import Path\n"
            f"Path({str(docker_log)!r}).write_text('unexpected Docker call')\n"
            "raise SystemExit(99)\n"
        )
        docker.chmod(0o755)
        environment = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"]}
        help_result = subprocess.run(
            ["bash", str(MIGRATE_SCRIPT), "--help"], input="", capture_output=True,
            text=True, timeout=10, cwd=self.root, env=environment,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--branch", help_result.stdout)
        run_result = subprocess.run(
            ["bash", str(MIGRATE_SCRIPT)], input="", capture_output=True,
            text=True, timeout=10, cwd=self.root, env=environment,
        )
        self.assertNotEqual(run_result.returncode, 0)
        self.assertFalse(docker_log.exists())

    def test_failure_or_interrupt_stops_destination_and_leaves_donor_stopped(self):
        for failure in (self.wizard.MigrationError("injected verification failure"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                tty = io.StringIO()
                wizard = self.wizard.Wizard(tty=tty)
                wizard.root = self.root
                wizard.old_id = "original-donor"
                wizard.donor_stopped = True
                wizard.destination_attempted = True
                wizard.compose_run = mock.Mock()
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(self.wizard, "Wizard", return_value=wizard), \
                        mock.patch.object(wizard, "execute", side_effect=failure), \
                        mock.patch.object(self.wizard, "run") as run, \
                        mock.patch.object(self.wizard.signal, "signal"), \
                        mock.patch("builtins.open", return_value=tty), \
                        mock.patch.object(sys, "argv", ["migrate.sh"]), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(self.wizard.main(), 1)
                wizard.compose_run.assert_called_once_with(["stop", "--timeout", "120"], capture=True)
                self.assertFalse(wizard.destination_attempted)
                self.assertTrue(wizard.donor_stopped)
                run.assert_called_once_with(["docker", "stop", "--time", "120", "original-donor"], capture=False)
                self.assertIn("original container", stdout.getvalue())
                self.assertIn("remain stopped", stdout.getvalue())

    def test_failed_destination_stop_never_claims_rollback_is_safe(self):
        tty = io.StringIO()
        wizard = self.wizard.Wizard(tty=tty)
        wizard.root = self.root
        wizard.old_id = "original-donor"
        wizard.donor_stopped = True
        wizard.destination_attempted = True
        wizard.compose_run = mock.Mock(side_effect=self.wizard.MigrationError("injected stop failure"))
        stderr = io.StringIO()
        with mock.patch.object(self.wizard, "Wizard", return_value=wizard), \
                mock.patch.object(wizard, "execute", side_effect=self.wizard.MigrationError("failed migration")), \
                mock.patch.object(self.wizard, "run") as run, \
                mock.patch.object(self.wizard.signal, "signal"), \
                mock.patch("builtins.open", return_value=tty), \
                mock.patch.object(sys, "argv", ["migrate.sh"]), \
                redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            self.assertEqual(self.wizard.main(), 1)
        self.assertTrue(wizard.destination_attempted)
        self.assertTrue(wizard.donor_stopped)
        run.assert_not_called()
        self.assertIn("Keep the original node stopped", stderr.getvalue())

    def test_key_verification_refuses_symlinks_and_changed_private_keys(self):
        migration, before = self.stage_identity()
        hashes = self.wizard.normalize_identity(migration)
        work = migration / "ton-work"
        self.wizard.copy_controller(migration / "identity/mytoncore", work / "controller/mytoncore")
        self.wizard.verify_keys(work, hashes)
        private_key = work / "keys/client"
        private_key.write_text("different private key")
        with self.assertRaises(self.wizard.MigrationError):
            self.wizard.verify_keys(work, hashes)
        private_key.unlink()
        private_key.symlink_to(self.donor / "ton-work/keys/client")
        with self.assertRaises(self.wizard.MigrationError):
            self.wizard.verify_keys(work, hashes)
        self.assertEqual(file_digests(self.donor), before)

    def test_donor_probe_inventories_full_history_and_refuses_external_wallet_links(self):
        self.create_legacy_data()
        ignored = self.donor / "mytoncore/venv/ignored-interpreter"
        ignored.parent.mkdir()
        with ignored.open("wb") as output:
            output.truncate(4 * 2**20)
        sparse = self.donor / "ton-work/db/sparse-data"
        with sparse.open("wb") as output:
            output.truncate(8 * 2**20)
        before = file_digests(self.donor)
        proc = self.root / "proc" / "1234"
        proc.mkdir(parents=True)
        (proc / "cmdline").write_bytes(
            b"/usr/bin/ton/validator-engine/validator-engine\0--db\0/var/ton-work/db\0"
        )
        mappings = {
            "/proc": proc.parent,
            "/var/ton-work": self.donor / "ton-work",
            "/usr/local/bin/mytoncore": self.donor / "mytoncore",
            "/usr/local/bin/mytonctrl": self.donor / "mytonctrl",
            "/usr/bin/ton": self.donor / "ton-runtime",
        }

        def isolated_path(value):
            value = str(value)
            for prefix, destination in mappings.items():
                if value == prefix:
                    return destination
                if value.startswith(prefix + "/"):
                    return destination / value[len(prefix) + 1:]
            return type(self.root)(value)

        stdout = io.StringIO()
        with mock.patch("pathlib.Path", side_effect=isolated_path), redirect_stdout(stdout):
            exec(compile(self.wizard.SOURCE_PROBE, "donor-probe", "exec"), {})
        probe = json.loads(stdout.getvalue())
        for name in ("archive/history", "celldb/state", "import/archive.slice"):
            self.assertIn("ton-work/db/" + name, probe["sizes"])
        self.assertIn("mytoncore/wallets/existing-wallet.pk", probe["hashes"])
        self.assertIn("ton-work/db/keyring/node-key", probe["hashes"])
        self.assertNotIn("mytoncore/venv/ignored-interpreter", probe["sizes"])
        self.assertGreaterEqual(probe["copy_totals"]["mytoncore"]["bytes"], ignored.stat().st_size)
        self.assertEqual(probe["sizes"]["ton-work/db/sparse-data"], sparse.stat().st_size)
        self.assertGreaterEqual(probe["copy_totals"]["ton-work"]["bytes"], sparse.stat().st_size)
        self.assertGreater(probe["copy_totals"]["ton-work"]["entries"], 1)
        self.assertEqual(probe["config_bytes"], sum(path.stat().st_size for path in
                                                  (self.donor / "ton-runtime").glob("*.config.json")))
        self.assertEqual(file_digests(self.donor), before)
        (self.donor / "mytoncore/wallets/external.pk").symlink_to("/etc/shadow")
        with mock.patch("pathlib.Path", side_effect=isolated_path), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                exec(compile(self.wizard.SOURCE_PROBE, "donor-probe", "exec"), {})
        self.assertEqual(file_digests(self.donor), before)

    def exercise_wizard(self, fail_at=None, core_update=None, node_update=None, restart_policy=None,
                        existing_env=None, env_consent="yes"):
        """Run the real workflow, substituting only host tools and image processes."""
        self.create_legacy_data()
        latest_core = {**copy.deepcopy(self.core), **(core_update or {})}
        latest_node = {**copy.deepcopy(self.node), **(node_update or {})}
        (self.donor / "mytoncore/mytoncore.db").write_text(json.dumps(latest_core))
        (self.donor / "ton-work/db/config.json").write_text(json.dumps(latest_node))
        global_config = {"validator": {"zero_state": {"root_hash": "main-root", "file_hash": "main-file"}}}
        (self.donor / "ton-runtime/global.config.json").write_text(json.dumps(global_config))
        before = file_digests(self.donor)
        before_modes = {str(path.relative_to(self.donor)): stat.S_IMODE(path.stat().st_mode)
                        for path in self.donor.rglob("*") if not path.is_symlink()}
        migration = self.root / "automatic-migration"
        answers = ["original-node", str(migration), "", "", "yes"]
        if existing_env is not None:
            (migration / "deployment").mkdir(parents=True)
            (migration / "deployment/.env").write_bytes(existing_env)
            answers.append(env_consent)
        answers.extend(("yes", "yes"))
        wizard = self.wizard.Wizard(tty=io.StringIO("\n".join(answers) + "\n"))
        command = ["/usr/bin/ton/validator-engine/validator-engine", "--threads", "127",
                   "--global-config", "/usr/bin/ton/global.config.json", "--db", "/var/ton-work/db",
                   "--archive-ttl", "86400", "--state-ttl", "3600", "-M"]
        mappings = {"/var/ton-work": self.donor / "ton-work",
                    "/usr/local/bin/mytoncore": self.donor / "mytoncore",
                    "/usr/local/bin/mytonctrl": self.donor / "mytonctrl",
                    "/usr/bin/ton": self.donor / "ton-runtime"}
        inspected = {"Id": "donor-id", "State": {"Running": True},
                     "Config": {"Env": ["NETWORK=mainnet"]}, "HostConfig": {},
                     "GraphDriver": {"Name": "overlay2", "Data": {"UpperDir": str(self.root)}},
                     "Mounts": [{"Destination": name, "Source": str(source)}
                                for name, source in mappings.items() if name != "/usr/bin/ton"]}
        if restart_policy is not None:
            inspected["HostConfig"]["RestartPolicy"] = restart_policy
        sizes = {name: (self.donor / name).stat().st_size for name in before
                 if not name.startswith("ton-runtime/")}
        hashes = {name: digest for name, digest in before.items()
                  if name.startswith(("ton-work/db/keyring/", "ton-work/keys/", "mytoncore/wallets/"))}
        copy_totals = {}
        for name in ("ton-work", "mytoncore", "mytonctrl"):
            paths = list((self.donor / name).rglob("*"))
            copy_totals[name] = {"bytes": sum(path.lstat().st_size for path in paths
                                              if path.is_file() or path.is_symlink()), "entries": len(paths) + 1}
        config_bytes = sum(path.stat().st_size for path in (self.donor / "ton-runtime").glob("*.config.json"))
        state = {"writer_running": True, "container_running": True, "probes": 0, "pulled": False}
        calls = []

        def probe():
            state["probes"] += 1
            totals = copy.deepcopy(copy_totals)
            if fail_at == "offline-space" and not state["writer_running"]:
                totals["ton-work"]["bytes"] += 2**45
            return {"core": copy.deepcopy(self.core if state["probes"] == 1 else latest_core),
                    "node": copy.deepcopy(self.node if state["probes"] == 1 else latest_node),
                    "command": command if state["writer_running"] else None,
                    "sizes": sizes, "hashes": hashes, "log_links": [],
                    "copy_totals": totals, "config_bytes": config_bytes,
                    "configs": {"global.config.json": "/usr/bin/ton/global.config.json",
                                "local.config.json": "/usr/bin/ton/local.config.json"}}

        def download(url):
            if url.endswith("testnet-global.config.json"):
                return json.dumps({"validator": {"zero_state": {"root_hash": "test-root", "file_hash": "test-file"}}}).encode()
            if url.endswith("global.config.json"):
                return json.dumps(global_config).encode()
            if url.endswith("/.env.example"):
                return (MIGRATE_SCRIPT.parent / ".env.example").read_bytes()
            if url.endswith("/docker/compose.yml"):
                return (MIGRATE_SCRIPT.parent / "docker/compose.yml").read_bytes()
            raise AssertionError("Unexpected download: " + url)

        def run(args, capture=True, **kwargs):
            args = [str(value) for value in args]
            calls.append(args)
            if args[:2] == ["docker", "compose"]:
                operation = args[len(wizard.compose):]
                if operation == ["pull"] and fail_at == "pull":
                    raise self.wizard.MigrationError("injected image pull failure")
                if operation == ["pull"]:
                    state["pulled"] = True
                if operation and operation[0] == "up":
                    (migration / "ton-work/controller/initialized.json").write_text("{}")
                if operation[:4] == ["exec", "-T", "mytonctrl", "python3"]:
                    return json.dumps([command])
                if operation[:5] == ["exec", "-T", "mytonctrl", "systemctl", "show"]:
                    return "active\n"
                return ""
            if args[:2] == ["docker", "ps"]:
                return "original-node legacy:image Up"
            if args[:2] == ["docker", "info"]:
                self.assertEqual(args[-1], "{{.DockerRootDir}}")
                return str(self.root)
            if args[:2] == ["docker", "inspect"]:
                return json.dumps([inspected]) if len(args) == 3 else str(state["container_running"]).lower()
            if args[:4] == ["docker", "exec", "donor-id", "cat"]:
                return json.dumps(global_config)
            if args[:4] == ["docker", "exec", "donor-id", "systemctl"]:
                if args[-2:] == ["stop", "validator"]:
                    state["writer_running"] = False
                return ""
            if args[:2] == ["docker", "stop"]:
                state["container_running"] = False
                return ""
            if args[:2] == ["docker", "update"]:
                return ""
            if args[0] == "findmnt":
                return "/mnt/data /dev/data ext4"
            if args[:2] == ["docker", "cp"]:
                if fail_at == "copy":
                    raise self.wizard.MigrationError("injected offline copy failure")
                source = args[-2].split(":", 1)[1]
                if source.endswith("/."):
                    source = source[:-2]
                original = next(base / source[len(prefix):].lstrip("/") for prefix, base in mappings.items()
                                if source == prefix or source.startswith(prefix + "/"))
                destination = Path(args[-1])
                if original.is_dir():
                    shutil.copytree(original, destination, dirs_exist_ok=True, symlinks=True)
                else:
                    shutil.copy2(original, destination)
                return ""
            if args[:2] == ["docker", "run"]:
                if "du" in args:
                    return "1024 /usr/local/bin\n512 /usr/lib/fift\n256 /usr/share/ton/smartcont\n"
                if "--mount" in args:
                    self.assertTrue((migration / "backup.tar.gz").is_file())
                else:
                    self.assertTrue(state["writer_running"])
                    self.assertTrue(state["container_running"])
                    self.assertFalse((migration / "ton-work").exists())
                    if fail_at == "image-probe":
                        raise self.wizard.MigrationError("injected missing image migration helper")
                return ""
            raise AssertionError("Unexpected command: " + repr(args))

        def logs(args, stdout, stderr, check):
            self.assertEqual(args[:2], ["docker", "logs"])
            stdout.write("saved legacy stdout log\n")
            return subprocess.CompletedProcess(args, 0)

        def capacity(path):
            free = 2**40
            if fail_at == "after-pull-space" and state["pulled"]:
                free = 0
            if fail_at == "current-space" and state["probes"] >= 2:
                free = 0
            return types.SimpleNamespace(free=free)

        with mock.patch.object(wizard, "validate_host"), mock.patch.object(wizard, "probe", side_effect=probe), \
                mock.patch.object(wizard, "check_ports"), mock.patch.object(self.wizard, "download", side_effect=download), \
                mock.patch.object(wizard, "measure_logs", return_value=128), \
                mock.patch.object(self.wizard.shutil, "disk_usage", side_effect=capacity), \
                mock.patch.object(self.wizard, "run", side_effect=run), \
                mock.patch.object(self.wizard.time, "sleep", side_effect=AssertionError("Unexpected service wait")), \
                mock.patch.object(self.wizard.subprocess, "run", side_effect=logs), redirect_stdout(io.StringIO()):
            if fail_at == "env-cancel":
                with mock.patch.object(self.wizard, "Wizard", return_value=wizard), \
                        mock.patch("builtins.open", return_value=wizard.tty), \
                        mock.patch.object(sys, "argv", ["migrate.sh"]), \
                        mock.patch.object(self.wizard.signal, "signal"), redirect_stderr(io.StringIO()):
                    self.assertEqual(self.wizard.main(), 1)
            elif fail_at:
                with self.assertRaises(self.wizard.MigrationError):
                    wizard.execute()
            else:
                wizard.execute()
        self.assertEqual(file_digests(self.donor), before)
        self.assertEqual({str(path.relative_to(self.donor)): stat.S_IMODE(path.stat().st_mode)
                          for path in self.donor.rglob("*") if not path.is_symlink()}, before_modes)
        return wizard, calls, state

    def test_image_pull_failure_does_not_stop_or_copy_the_original_node(self):
        wizard, calls, state = self.exercise_wizard(fail_at="pull")
        self.assertFalse(wizard.donor_stopped)
        self.assertTrue(state["writer_running"])
        self.assertTrue(state["container_running"])
        self.assertFalse(any(call[:2] == ["docker", "stop"] or call[:2] == ["docker", "cp"]
                             or call[-2:-1] == ["stop"] for call in calls))

    def test_failed_offline_copy_keeps_original_storage_and_both_nodes_stopped(self):
        wizard, calls, state = self.exercise_wizard(fail_at="copy")
        self.assertTrue(wizard.donor_stopped)
        self.assertFalse(wizard.destination_attempted)
        self.assertFalse(state["writer_running"])
        self.assertFalse(state["container_running"])
        self.assertFalse(any(call[:2] == ["docker", "start"] for call in calls))
        self.assertFalse(any("up" in call for call in calls))

    def test_incompatible_controller_image_is_rejected_before_donor_downtime(self):
        wizard, calls, state = self.exercise_wizard(fail_at="image-probe")
        self.assertFalse(wizard.donor_stopped)
        self.assertTrue(state["writer_running"])
        self.assertTrue(state["container_running"])
        self.assertFalse(any(call[:2] == ["docker", "stop"] or call[:2] == ["docker", "cp"]
                             or call[-2:-1] == ["stop"] for call in calls))

    def test_automatic_migration_copies_data_and_verifies_identity_before_starting(self):
        wizard, calls, state = self.exercise_wizard()
        self.assertFalse(state["container_running"])
        migration = wizard.root
        self.assertEqual(json.loads((migration / "migration.json").read_text())["phase"], "verified")
        self.assertEqual(file_digests(migration / "ton-work/db"), file_digests(self.donor / "ton-work/db"))
        self.assertEqual((migration / "ton-work/controller/mytoncore/wallets/existing-wallet.pk").read_bytes(),
                         (self.donor / "mytoncore/wallets/existing-wallet.pk").read_bytes())
        self.assertEqual((migration / "ton-work/dump-cache/saved-dump.tar.lz").read_bytes(),
                         (self.donor / "ton-work/dump-cache/saved-dump.tar.lz").read_bytes())
        env = self.wizard.parse_env((migration / "deployment/.env").read_text())
        self.assertEqual(env["ARCHIVE_TTL"], "90000")
        self.assertEqual(env["STATE_TTL"], "3600")
        self.assertNotIn("-d", env["MYTONCTRL_ARGS"].split())
        self.assertNotIn("ARCHIVE_BLOCKS", env)
        stop = next(index for index, call in enumerate(calls) if call[:2] == ["docker", "stop"])
        controller_stop = next(index for index, call in enumerate(calls)
                               if call == ["docker", "exec", "donor-id", "systemctl", "stop", "mytoncore"])
        image_probe = next(index for index, call in enumerate(calls)
                           if call[:2] == ["docker", "run"] and "--mount" not in call)
        first_copy = next(index for index, call in enumerate(calls) if call[:2] == ["docker", "cp"])
        start = next(index for index, call in enumerate(calls) if "up" in call)
        self.assertLess(stop, first_copy)
        self.assertLess(first_copy, start)
        self.assertLess(image_probe, controller_stop)
        self.assertLess(image_probe, first_copy)

    def test_recent_background_metadata_changes_are_copied_from_offline_controller(self):
        updates = {"lastScan": 123456, "customPools": ["updated-pool"], "statistics": {"load": 42}}
        wizard, _, _ = self.exercise_wizard(core_update=updates)
        migrated = json.loads((wizard.root / "ton-work/controller/mytoncore/mytoncore.db").read_text())
        for name, value in updates.items():
            self.assertEqual(migrated[name], value)

    def test_identity_change_during_planning_refuses_copy_and_destination_start(self):
        wizard, calls, _ = self.exercise_wizard(fail_at="identity-change", core_update={"adnlAddr": "new-identity"})
        self.assertTrue(wizard.donor_stopped)
        self.assertFalse(any(call[:2] == ["docker", "cp"] for call in calls))
        self.assertFalse(any("up" in call for call in calls))

    def test_endpoint_change_during_planning_refuses_copy_and_destination_start(self):
        changed = [{"port": 40314, "id": "console-key", "allowed": ["client-key"]}]
        wizard, calls, _ = self.exercise_wizard(fail_at="identity-change", node_update={"control": changed})
        self.assertTrue(wizard.donor_stopped)
        self.assertFalse(any(call[:2] == ["docker", "cp"] for call in calls))
        self.assertFalse(any("up" in call for call in calls))

    def test_rollback_stop_ignores_later_environment_overrides(self):
        wizard, _, _ = self.exercise_wizard()
        tools = self.root / "rollback-tools"
        tools.mkdir()
        log = self.root / "rollback-docker.json"
        docker = tools / "docker"
        docker.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\nfrom pathlib import Path\n"
            f"Path({str(log)!r}).write_text(json.dumps({{'args': sys.argv[1:], 'host_dir': os.environ.get('TON_WORK_HOST_DIR'), "
            "'compose_file': os.environ.get('COMPOSE_FILE'), 'image': os.environ.get('MYTONCTRL_IMAGE')}))\n"
        )
        docker.chmod(0o755)
        stop_line = next(line for line in (wizard.root / "rollback.sh").read_text().splitlines()
                         if line.startswith("env "))
        environment = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                       "TON_WORK_HOST_DIR": "/different-data", "COMPOSE_FILE": "/different-compose.yml",
                       "MYTONCTRL_IMAGE": "different:image"}
        result = subprocess.run(shlex.split(stop_line), env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        invoked = json.loads(log.read_text())
        self.assertIsNone(invoked["host_dir"])
        self.assertIsNone(invoked["compose_file"])
        self.assertIsNone(invoked["image"])
        self.assertEqual(invoked["args"][-3:], ["stop", "--timeout", "120"])
        self.assertIn(str(wizard.root / "deployment/.env"), invoked["args"])

    def test_donor_restart_policy_is_disabled_before_downtime_and_restored_after_destination_stop(self):
        wizard, calls, _ = self.exercise_wizard(
            restart_policy={"Name": "always", "MaximumRetryCount": 0}
        )
        disable = next(index for index, call in enumerate(calls)
                       if call == ["docker", "update", "--restart", "no", "donor-id"])
        controller_stop = next(index for index, call in enumerate(calls)
                               if call == ["docker", "exec", "donor-id", "systemctl", "stop", "mytoncore"])
        first_copy = next(index for index, call in enumerate(calls) if call[:2] == ["docker", "cp"])
        self.assertLess(disable, controller_stop)
        self.assertLess(controller_stop, first_copy)
        rollback = (wizard.root / "rollback.sh").read_text().splitlines()
        stop = next(index for index, line in enumerate(rollback) if line.startswith("env "))
        restore = next(index for index, line in enumerate(rollback)
                       if shlex.split(line) == ["docker", "update", "--restart", "always", "donor-id"])
        start = next(index for index, line in enumerate(rollback)
                     if shlex.split(line) == ["docker", "start", "donor-id"])
        self.assertLess(stop, restore)
        self.assertLess(restore, start)

    def test_private_umask_allows_engine_network_config_access_and_keeps_wallets_private(self):
        previous_umask = os.umask(0o077)
        try:
            wizard, _, _ = self.exercise_wizard()
        finally:
            os.umask(previous_umask)
        controller = wizard.root / "ton-work/controller"
        self.assertEqual(stat.S_IMODE(controller.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((controller / "global.config.json").stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((controller / "local.config.json").stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((controller / "mytoncore").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((controller / "mytoncore/wallets").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((controller / "mytoncore/wallets/existing-wallet.pk").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.donor / "ton-runtime/global.config.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.donor / "ton-runtime/local.config.json").stat().st_mode), 0o600)

    def space_probe(self):
        return {
            "sizes": {
                "ton-work/db/archive/history": 8 * 2**30,
                "ton-work/db/config.json": 512,
                "ton-work/db/keyring/key": 128,
                "ton-work/keys/client": 64,
                "mytoncore/mytoncore.db": 2 * 2**20,
                "mytoncore/wallets/wallet.pk": 64,
                "mytonctrl/mytonctrl.db": 256,
            },
            "copy_totals": {
                "ton-work": {"bytes": 8 * 2**30 + 704, "entries": 12},
                "mytoncore": {"bytes": 2**30 + 2 * 2**20 + 64, "entries": 8},
                "mytonctrl": {"bytes": 256, "entries": 3},
            },
            "config_bytes": 1024,
        }

    def test_space_budget_includes_complete_copy_and_identity_copies_without_compression_credit(self):
        probe = self.space_probe()
        plan = self.wizard.migration_space_plan(probe, log_bytes=4096)
        self.assertGreaterEqual(plan["copy"], 9 * 2**30 + 4096 + probe["config_bytes"])
        identity = sum(size for name, size in probe["sizes"].items()
                       if name.startswith(("mytoncore/", "ton-work/keys/", "ton-work/db/keyring/"))
                       or name == "ton-work/db/config.json")
        core = 2 * 2**20 + 64
        self.assertGreaterEqual(plan["stage"], identity + 256 + probe["config_bytes"])
        self.assertGreater(plan["archive"], identity)
        self.assertGreaterEqual(plan["restore"], identity)
        self.assertGreaterEqual(plan["prime"], core)
        self.assertGreaterEqual(plan["startup"], core)
        self.assertGreaterEqual(plan["reserve"], 2**30)
        # Ignored venv bytes are retained by docker cp but do not enter the
        # identity archive or controller's additional copies.
        more_venv = copy.deepcopy(probe)
        more_venv["copy_totals"]["mytoncore"]["bytes"] += 2**30
        larger = self.wizard.migration_space_plan(more_venv, log_bytes=4096)
        self.assertEqual(larger["copy"] - plan["copy"], 2**30)
        for phase in ("stage", "archive", "prime", "startup", "restore"):
            self.assertEqual(larger[phase], plan[phase])

    def test_disk_space_combines_requirements_on_the_same_device(self):
        data = self.root / "data"
        docker = self.root / "docker"
        with mock.patch.object(Path, "stat", autospec=True, return_value=types.SimpleNamespace(st_dev=1)), \
                mock.patch.object(self.wizard.shutil, "disk_usage", return_value=types.SimpleNamespace(free=100)), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(self.wizard.MigrationError):
                self.wizard.check_disk_space([("migration data", data, 70), ("Docker restore", docker, 60)])

    def test_disk_space_checks_separate_devices_independently(self):
        data = self.root / "data"
        docker = self.root / "docker"
        def device(path):
            return types.SimpleNamespace(st_dev=1 if path == data else 2)
        with mock.patch.object(Path, "stat", autospec=True, side_effect=device), \
                mock.patch.object(self.wizard.shutil, "disk_usage", return_value=types.SimpleNamespace(free=100)), \
                redirect_stdout(io.StringIO()):
            self.wizard.check_disk_space([("migration data", data, 70), ("Docker restore", docker, 60)])

    def test_post_pull_low_space_preserves_running_donor_and_restart_policy(self):
        wizard, calls, state = self.exercise_wizard(
            fail_at="after-pull-space", restart_policy={"Name": "always", "MaximumRetryCount": 0}
        )
        self.assertTrue(state["pulled"])
        self.assertFalse(wizard.donor_stopped)
        self.assertTrue(state["writer_running"])
        self.assertTrue(state["container_running"])
        self.assertFalse(any(call[:2] in (["docker", "stop"], ["docker", "update"], ["docker", "cp"])
                             or call[-2:-1] == ["stop"] for call in calls))

    def test_current_pre_downtime_low_space_preserves_running_donor_and_restart_policy(self):
        wizard, calls, state = self.exercise_wizard(
            fail_at="current-space", restart_policy={"Name": "always", "MaximumRetryCount": 0}
        )
        self.assertGreaterEqual(state["probes"], 2)
        self.assertFalse(wizard.donor_stopped)
        self.assertTrue(state["writer_running"])
        self.assertTrue(state["container_running"])
        self.assertFalse(any(call[:2] in (["docker", "stop"], ["docker", "update"], ["docker", "cp"])
                             or call[-2:-1] == ["stop"] for call in calls))

    def test_offline_source_growth_is_rejected_before_copying(self):
        wizard, calls, state = self.exercise_wizard(fail_at="offline-space")
        self.assertTrue(wizard.donor_stopped)
        self.assertFalse(state["writer_running"])
        self.assertFalse(state["container_running"])
        self.assertFalse(any(call[:2] == ["docker", "cp"] for call in calls))
        self.assertFalse(any("up" in call for call in calls))

    def test_remaining_space_rechecks_do_not_charge_completed_phases_again(self):
        wizard = self.wizard.Wizard()
        wizard.root = self.root / "migration"
        wizard.docker_root = self.root / "docker"
        wizard.docker_root.mkdir()
        wizard.log_bytes = 4096
        wizard.artifact_bytes = 2048
        requests = []
        probe = self.space_probe()
        plan = self.wizard.migration_space_plan(probe, log_bytes=4096)
        with mock.patch.object(self.wizard.os, "statvfs", return_value=types.SimpleNamespace(f_frsize=4096)), \
                mock.patch.object(self.wizard, "check_disk_space", side_effect=lambda requirements: requests.append(requirements)):
            for phase in ("copy", "stage", "archive", "startup"):
                wizard.check_space(probe, phase)
        self.assertEqual(requests[0][0][2] - requests[1][0][2], plan["copy"])
        self.assertEqual(requests[1][0][2] - requests[2][0][2], plan["stage"])
        self.assertEqual(requests[3][0][2], plan["startup"] + plan["reserve"])
        self.assertEqual({sum(item[2] for item in requirements[1:]) for requirements in requests},
                         {sum(item[2] for item in requests[0][1:])})
        self.assertGreaterEqual(sum(item[2] for item in requests[0][1:]),
                                plan["restore"] + 2 * wizard.artifact_bytes + 2**30)

    def test_docker_storage_uses_actual_upper_layer_and_volume_directory(self):
        docker_root = self.root / "docker-root"
        volumes = docker_root / "volumes"
        volumes.mkdir(parents=True)
        upper = self.root / "independent-writable-layer"
        upper.mkdir()
        inspected = {"GraphDriver": {"Name": "overlay2", "Data": {"UpperDir": str(upper)}}}
        self.assertEqual(self.wizard.docker_storage_paths(inspected, docker_root), (volumes, upper))

    def test_docker_storage_rejects_missing_explicit_upper_layer(self):
        docker_root = self.root / "docker-root"
        (docker_root / "overlay2").mkdir(parents=True)
        inspected = {"GraphDriver": {"Name": "overlay2", "Data": {"UpperDir": str(self.root / "missing-layer")}}}
        with self.assertRaises(self.wizard.MigrationError):
            self.wizard.docker_storage_paths(inspected, docker_root)

    def test_docker_storage_refuses_unknown_store_instead_of_assuming_root_filesystem(self):
        docker_root = self.root / "docker-root"
        docker_root.mkdir()
        # Ignore any unrelated containerd store on the host running the tests.
        with mock.patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path == docker_root):
            with self.assertRaises(self.wizard.MigrationError):
                self.wizard.docker_storage_paths({}, docker_root)

    def test_container_log_measurement_streams_all_bytes_and_rejects_driver_failure(self):
        wizard = self.wizard.Wizard()
        wizard.old_id = "original-container"
        contents = b"rotated log line\n" * 100000 + b"last log line\n"
        process = mock.MagicMock()
        process.__enter__.return_value = process
        process.stdout = io.BytesIO(contents)
        process.wait.return_value = 0
        with mock.patch.object(self.wizard.subprocess, "Popen", return_value=process):
            self.assertEqual(wizard.measure_logs(), len(contents))
        process.stdout = io.BytesIO(b"logger driver error\n")
        process.wait.return_value = 1
        with mock.patch.object(self.wizard.subprocess, "Popen", return_value=process):
            with self.assertRaises(self.wizard.MigrationError):
                wizard.measure_logs()

    def environment_writer(self, name, consent):
        wizard = self.wizard.Wizard(tty=io.StringIO(consent))
        wizard.root = self.root / name
        (wizard.root / "deployment").mkdir(parents=True)
        wizard.root.chmod(0o750)
        (wizard.root / "deployment").chmod(0o755)
        wizard.project = "environment-consent-test"
        wizard.settings = {"MYTONCTRL_IMAGE": "selected:new", "TON_WORK_HOST_DIR": str(wizard.root / "ton-work")}
        original = b"SECRET=original-value\r\nLITERAL=$HOME\r\n"
        path = wizard.root / "deployment/.env"
        path.write_bytes(original)
        path.chmod(0o640)
        return wizard, path, original

    def test_existing_environment_requires_explicit_yes_including_default_and_eof(self):
        for index, answer in enumerate(("no\n", "\n", "")):
            with self.subTest(answer=repr(answer)):
                wizard, path, original = self.environment_writer(f"cancel-{index}", answer)
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(self.wizard.MigrationError):
                    wizard.write_deployment("MYTONCTRL_IMAGE=template:image\n", "services: {}\n")
                self.assertIn(str(path), output.getvalue())
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
                self.assertEqual(stat.S_IMODE(wizard.root.stat().st_mode), 0o750)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o755)
                self.assertEqual({child.name for child in path.parent.iterdir()}, {".env"})
                self.assertFalse((wizard.root / "migration.json").exists())

    def test_confirmed_environment_replacement_is_atomic_private_and_backed_up(self):
        wizard, path, original = self.environment_writer("accept", "yes\n")
        original_inode = path.stat().st_ino
        caller_env = self.root / ".env"
        caller_env.write_text("CALLER_CONFIGURATION=untouched\n")
        output = io.StringIO()
        with redirect_stdout(output):
            wizard.write_deployment("MYTONCTRL_IMAGE=template:image\n", "services: {}\n")
        self.assertIn(str(path), output.getvalue())
        self.assertEqual(self.wizard.parse_env(path.read_text())["MYTONCTRL_IMAGE"], "selected:new")
        self.assertNotEqual(path.stat().st_ino, original_inode)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(wizard.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        backup = path.with_name(".env.before-migration")
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(caller_env.read_text(), "CALLER_CONFIGURATION=untouched\n")
        self.assertFalse(any(child.name.startswith(".env.") and child.name != backup.name
                             for child in path.parent.iterdir()))

    def test_environment_backup_uses_unique_names_and_never_replaces_existing_backups(self):
        wizard, path, original = self.environment_writer("backup-collision", "yes\n")
        first = path.with_name(".env.before-migration")
        second = path.with_name(".env.before-migration.1")
        first.write_bytes(b"older backup zero")
        second.write_bytes(b"older backup one")
        with redirect_stdout(io.StringIO()):
            wizard.write_deployment("MYTONCTRL_IMAGE=template:image\n", "services: {}\n")
        self.assertEqual(first.read_bytes(), b"older backup zero")
        self.assertEqual(second.read_bytes(), b"older backup one")
        third = path.with_name(".env.before-migration.2")
        self.assertEqual(third.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(third.stat().st_mode), 0o600)

    def test_destination_accepts_an_empty_directory_or_only_deployment_and_regular_environment(self):
        for name, contents in (("empty", None), ("deployment-only", "deployment"), ("environment-only", ".env")):
            with self.subTest(contents=contents):
                destination = self.root / name
                destination.mkdir()
                if contents:
                    (destination / "deployment").mkdir()
                if contents == ".env":
                    (destination / "deployment/.env").write_text("EXISTING=configuration\n")
                before = file_digests(destination)
                self.assertEqual(self.wizard.ensure_destination_isolated(destination, [self.donor]), destination.resolve())
                self.assertEqual(file_digests(destination), before)

    def test_destination_refuses_node_data_prior_state_compose_and_linked_environments(self):
        invalid = ("ton-work/data", "legacy/data", "migration.json", "backup.tar.gz",
                   "deployment/compose.yml", "deployment/compose.yaml", "deployment/unexpected", ".env")
        for index, name in enumerate(invalid):
            with self.subTest(contents=name):
                destination = self.root / f"unexpected-{index}"
                path = destination / name
                path.parent.mkdir(parents=True)
                path.write_text("original contents\n")
                before = file_digests(destination)
                with self.assertRaises(self.wizard.MigrationError):
                    self.wizard.ensure_destination_isolated(destination, [self.donor])
                self.assertEqual(file_digests(destination), before)
        for index, kind in enumerate(("deployment symlink", "env symlink", "env hardlink")):
            with self.subTest(link=kind):
                destination = self.root / f"linked-{index}"
                destination.mkdir()
                target = self.root / f"link-target-{index}"
                if kind == "deployment symlink":
                    target.mkdir()
                    (destination / "deployment").symlink_to(target, target_is_directory=True)
                else:
                    (destination / "deployment").mkdir()
                    target.write_text("external configuration\n")
                    if kind == "env symlink":
                        (destination / "deployment/.env").symlink_to(target)
                    else:
                        os.link(target, destination / "deployment/.env")
                with self.assertRaises(self.wizard.MigrationError):
                    self.wizard.ensure_destination_isolated(destination, [self.donor])
                if target.is_file():
                    self.assertEqual(target.read_text(), "external configuration\n")

    def test_cancelled_environment_replacement_never_pulls_stops_or_creates_migration_state(self):
        original = b"EXISTING_DEPLOYMENT=preserved\n"
        wizard, calls, state = self.exercise_wizard(fail_at="env-cancel", existing_env=original, env_consent="no")
        self.assertEqual((wizard.root / "deployment/.env").read_bytes(), original)
        self.assertFalse((wizard.root / "migration.json").exists())
        self.assertFalse((wizard.root / "legacy").exists())
        self.assertFalse(wizard.donor_stopped)
        self.assertTrue(state["writer_running"])
        self.assertTrue(state["container_running"])
        self.assertFalse(state["pulled"])
        self.assertFalse(any(call[:2] == ["docker", "stop"] or call[:2] == ["docker", "update"]
                             or call[-2:-1] == ["stop"] for call in calls))

    def test_accepted_existing_environment_completes_migration_and_keeps_original_backup(self):
        original = b"PREVIOUS_DEPLOYMENT=preserved\r\n"
        wizard, _, state = self.exercise_wizard(existing_env=original, env_consent="yes")
        deployment = wizard.root / "deployment"
        self.assertEqual((deployment / ".env.before-migration").read_bytes(), original)
        self.assertEqual(stat.S_IMODE((deployment / ".env.before-migration").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(deployment.stat().st_mode), 0o700)
        self.assertEqual(self.wizard.parse_env((deployment / ".env").read_text())["NETWORK"], "mainnet")
        self.assertEqual(json.loads((wizard.root / "migration.json").read_text())["phase"], "verified")
        self.assertTrue(state["pulled"])
        self.assertFalse(state["container_running"])
        self.assertTrue((wizard.root / "ton-work/controller/initialized.json").is_file())


if __name__ == "__main__":
    unittest.main()
