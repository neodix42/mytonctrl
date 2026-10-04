import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docker"))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "docker" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entrypoint = load_script("entrypoint")
console = load_script("console")
docker_args = load_script("mytonctrl_docker_args")


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def artifacts(self, root):
        sources = tuple(root / name for name in ("bin", "fift", "smartcont"))
        for source in sources:
            source.mkdir(parents=True)
        for name in entrypoint.REQUIRED_BINARIES:
            path = sources[0] / name
            path.write_text("original executable")
            path.chmod(0o755)
        for name in ("Fift.fif", "TonUtil.fif", "Asm.fif"):
            (sources[1] / name).write_text("original library")
        for name in ("wallet-v3.fif", "validator-elect-signed.fif"):
            (sources[2] / name).write_text("original contract")
        return sources

    def test_snapshot_keeps_binaries_and_resources_when_provider_updates(self):
        sources = self.artifacts(self.root / "provider")
        active = entrypoint.snapshot_artifacts(sources, self.root / "active")
        (sources[0] / "validator-engine").write_text("new executable")
        (sources[1] / "TonUtil.fif").write_text("new library")
        self.assertEqual((active / "bin/validator-engine").read_text(), "original executable")
        self.assertEqual((active / "fift/TonUtil.fif").read_text(), "original library")
        self.assertEqual((active / "bin/validator-engine").stat().st_mode & 0o222, 0)

    def test_existing_native_mounts_need_no_export_metadata(self):
        sources = self.artifacts(self.root / "native")
        env = dict(zip(("TON_BINARIES_DIR", "FIFT_LIB_DIR", "TON_SMARTCONT_DIR"), map(str, sources)))
        env["TON_ARTIFACTS_DIR"] = str(self.root / "absent")
        with patch.object(entrypoint, "mounted", return_value=True):
            self.assertEqual(entrypoint.artifact_sources(env), sources)

    def test_missing_mount_fails_before_creating_runtime_or_state(self):
        with self.assertRaisesRegex(ValueError, "Missing TON artifact mount"):
            entrypoint.artifact_sources({"TON_BINARIES_DIR": str(self.root / "missing")})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_blank_or_missing_public_ip_is_detected_before_installation(self):
        for value in (None, "", " \t"):
            env = {} if value is None else {"PUBLIC_IP": value}
            with self.subTest(value=value), patch.object(entrypoint, "detect_public_ip", return_value="192.0.2.10") as detect:
                entrypoint.resolve_public_ip(env)
                detect.assert_called_once_with()
                self.assertEqual(env["PUBLIC_IP"], "192.0.2.10")

    def test_explicit_ipv4_is_trimmed_and_accepts_custom_network_addresses(self):
        for value in (" 192.0.2.10 ", "127.0.0.1", "10.0.0.5"):
            env = {"PUBLIC_IP": value}
            with self.subTest(value=value), patch.object(entrypoint, "detect_public_ip") as detect:
                entrypoint.resolve_public_ip(env)
                detect.assert_not_called()
                self.assertEqual(env["PUBLIC_IP"], value.strip())

    def test_invalid_explicit_public_ip_fails_without_discovery(self):
        for value in ("not-an-ip", "::1", "256.0.0.1"):
            env = {"PUBLIC_IP": value}
            with self.subTest(value=value), patch.object(entrypoint, "detect_public_ip") as detect:
                with self.assertRaises(ValueError):
                    entrypoint.resolve_public_ip(env)
                detect.assert_not_called()

    def test_failed_public_ip_discovery_explains_env_configuration(self):
        env = {"PUBLIC_IP": ""}
        with patch.object(entrypoint, "detect_public_ip", side_effect=OSError("discovery service unavailable")):
            with self.assertRaisesRegex(ValueError, "PUBLIC_IP.*\\.env"):
                entrypoint.resolve_public_ip(env)
        self.assertEqual(env["PUBLIC_IP"], "")

    def test_invalid_discovered_ip_cannot_reach_installer(self):
        for value in ("", "not-an-ip", "2001:db8::1"):
            env = {}
            with self.subTest(value=value), patch.object(entrypoint, "detect_public_ip", return_value=value):
                with self.assertRaises(ValueError):
                    entrypoint.resolve_public_ip(env)
            self.assertNotIn("PUBLIC_IP", env)

    def test_controller_only_restore_skips_public_ip_resolution(self):
        env = {"ONLY_MTC": "true", "PUBLIC_IP": ""}
        with patch.object(entrypoint, "detect_public_ip") as detect:
            entrypoint.resolve_public_ip(env)
            detect.assert_not_called()
        self.assertEqual(env["PUBLIC_IP"], "")

    def test_discovery_failure_precedes_pending_marker_and_installer_process(self):
        work = self.root / "node-work"
        env = {"PUBLIC_IP": "", "TON_WORK_DIR": str(work), "MTC_USER": "root"}
        with patch.object(entrypoint.sys, "argv", ["entrypoint.py", "run"]), \
             patch.object(entrypoint, "installation_environment", return_value=env), \
             patch.object(entrypoint, "artifact_sources", return_value=()), \
             patch.object(entrypoint, "snapshot_artifacts", return_value=self.root / "active"), \
             patch.object(entrypoint, "check_binaries"), \
             patch.object(entrypoint.os, "getuid", return_value=0), \
             patch.object(entrypoint.os, "environ", {}), \
             patch.object(entrypoint, "mounted", return_value=False), \
             patch.object(entrypoint, "check_requirements"), \
             patch.object(entrypoint, "detect_public_ip", side_effect=OSError("discovery unavailable")), \
             patch.object(entrypoint, "prepare_layout") as prepare, \
             patch.object(entrypoint.subprocess, "Popen") as process:
            with self.assertRaisesRegex(ValueError, "PUBLIC_IP.*\\.env"):
                entrypoint.main()
            prepare.assert_not_called()
            process.assert_not_called()
        self.assertFalse((work / "controller/.initializing").exists())
        self.assertFalse((work / "db").exists())

    def test_release_is_pinned_once_and_cannot_escape_volume(self):
        root = self.root / "artifacts"
        release = root / "releases/first"
        sources = self.artifacts(release)
        (root / "current").symlink_to("releases/first")
        with patch.object(entrypoint, "mounted", return_value=True):
            selected = entrypoint.artifact_sources({"TON_ARTIFACTS_DIR": str(root)})
        self.assertEqual(selected, sources)
        (root / "current").unlink()
        (root / "current").symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, "must stay inside"):
            entrypoint.artifact_sources({"TON_ARTIFACTS_DIR": str(root)})

    def test_missing_fift_resources_are_required_alongside_executables(self):
        sources = self.artifacts(self.root / "native")
        (sources[1] / "Asm.fif").unlink()
        with self.assertRaisesRegex(ValueError, "Asm.fif"):
            entrypoint.validate_artifacts(*sources)

    def test_env_maps_all_installer_arguments_without_a_shell(self):
        env = {"MTC_USER": "validator", "TELEMETRY": "false", "DUMP": "yes", "MODE": "single-nominator",
               "ONLY_MTC": "0", "ONLY_NODE": "true", "BACKUP": "none", "BIN_DIR": "/custom/bin",
               "SRC_DIR": "/custom/resources", "TON_WORK_DIR": "/custom/work"}
        self.assertEqual(entrypoint.installer_args(env), [
            "-u", "validator", "-t", "false", "--dump", "true", "-m", "single-nominator",
            "--only-mtc", "false", "--only-node", "true", "--backup", "none",
            "--bin-dir", "/custom/bin", "--src-dir", "/custom/resources", "--ton-work-dir", "/custom/work"])

    def test_default_mytonctrl_args_configure_the_installer(self):
        env = docker_args.installation_environment({"MYTONCTRL_ARGS": "-m validator -n mainnet -d"})
        args = entrypoint.installer_args(env)
        self.assertEqual(args[args.index("--dump") + 1], "true")
        self.assertEqual(args[args.index("-m") + 1], "validator")
        self.assertEqual(env["NETWORK"], "mainnet")
        self.assertEqual(console.console_args(env), [])

    def test_installer_long_and_short_arguments_are_equivalent(self):
        short = "-m liteserver -n testnet -u mtc -t -i -d -l -p /backup.tar.gz -B /bin-mount -S /resources -W /data -s"
        long = "--mode liteserver --network testnet --user mtc --telemetry --ignore-reqs --dump --only-node --backup /backup.tar.gz --bin-dir /bin-mount --src-dir /resources --ton-work-dir /data --no-startup-checks"
        first = docker_args.installation_environment({"MYTONCTRL_ARGS": short})
        second = docker_args.installation_environment({"MYTONCTRL_ARGS": long})
        first.pop("MYTONCTRL_ARGS")
        second.pop("MYTONCTRL_ARGS")
        self.assertEqual(first, second)
        self.assertEqual(first["TELEMETRY"], "false")
        self.assertEqual(first["IGNORE_MINIMAL_REQS"], "true")
        self.assertEqual(first["MTC_USER"], "mtc")
        self.assertEqual(first["TON_WORK_DIR"], "/data")
        self.assertEqual(console.console_args(first), ["--no-startup-checks"])

    def test_argument_config_selects_url_or_mounted_file(self):
        for config, name in (("https://example.org/global.json", "GLOBAL_CONFIG_URL"),
                             ("/mounted/custom network.json", "GLOBAL_CONFIG_FILE")):
            env = docker_args.installation_environment({"GLOBAL_CONFIG_FILE": "old-file",
                                                       "MYTONCTRL_ARGS": f"-c '{config}'"})
            self.assertEqual(env[name], config)
            if name == "GLOBAL_CONFIG_URL":
                self.assertNotIn("GLOBAL_CONFIG_FILE", env)

    def test_mounted_env_parameters_are_data_and_flags_take_precedence(self):
        path = self.root / "parameters.env"
        path.write_text("# Native parameters\nARCHIVE_TTL=123\nMODE=collator\n"
                        "PUBLIC_IP='127.0.0.1'\nPUBLIC_TEXT=$(touch should-not-exist)\n")
        env = docker_args.installation_environment({"MYTONCTRL_ARGS": f"-e '{path}' -m liteserver"})
        self.assertEqual(env["MODE"], "liteserver")
        self.assertEqual(env["ARCHIVE_TTL"], "123")
        self.assertEqual(env["PUBLIC_IP"], "127.0.0.1")
        self.assertEqual(env["PUBLIC_TEXT"], "$(touch should-not-exist)")
        self.assertFalse((self.root / "should-not-exist").exists())

    def test_literal_arguments_never_execute_shell_substitutions(self):
        marker = self.root / "unexpected"
        env = docker_args.installation_environment({"MYTONCTRL_ARGS": f"-o -p '$(touch {marker})'"})
        self.assertEqual(env["BACKUP"], f"$(touch {marker})")
        self.assertFalse(marker.exists())

    def test_source_selection_has_explicit_image_based_errors(self):
        for option in ("-a", "-r", "-b", "-g", "-v"):
            with self.subTest(option=option), self.assertRaisesRegex(ValueError, "select MYTONCTRL_IMAGE/TON_IMAGE"):
                docker_args.installation_environment({"MYTONCTRL_ARGS": f"{option} custom-source"})

    def test_direct_entrypoint_arguments_override_env_defaults(self):
        env = docker_args.installation_environment({"MYTONCTRL_ARGS": "-m validator -n mainnet"},
                                                  ["-m", "liteserver", "-n", "testnet"])
        self.assertEqual(env["MODE"], "liteserver")
        self.assertEqual(env["NETWORK"], "testnet")

    def test_archive_preserves_original_full_archive_settings(self):
        env = {"ARCHIVE": "true", "MODE": "liteserver", "STATE_TTL": "123"}
        entrypoint.installer_args(env)
        self.assertEqual(env["ARCHIVE_BLOCKS"], "1")
        self.assertEqual(env["ARCHIVE_TTL"], "-1")
        self.assertNotIn("STATE_TTL", env)

    def test_restore_mount_is_needed_only_during_initial_install(self):
        env = {"ONLY_MTC": "true", "BACKUP": str(self.root / "removed-backup.tar.gz")}
        entrypoint.installer_args(env, validate_backup=False)
        with self.assertRaisesRegex(ValueError, "Backup file is missing"):
            entrypoint.installer_args(env)

    def test_invalid_or_conflicting_flags_fail(self):
        for env in ({"MODE": "bogus"}, {"ONLY_NODE": "true", "ONLY_MTC": "true", "BACKUP": "x"},
                    {"ARCHIVE": "true"}, {"TELEMETRY": "perhaps"}, {"BIN_DIR": "relative"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                entrypoint.installer_args(env)

    def test_custom_args_are_data_and_cannot_replace_owned_paths(self):
        self.assertEqual(entrypoint.custom_validator_args({"CUSTOM_PARAMETERS": "--threads 2 --archive-ttl -1"}),
                         ["--threads", "2", "--archive-ttl", "-1"])
        for value in ("--db=/tmp/db", "--daemonize", "--global-config /tmp/config"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                entrypoint.custom_validator_args({"CUSTOM_PARAMETERS": value})

    def test_all_console_flags_and_quoting_pass_through(self):
        self.assertEqual(console.console_args({"MYTONCTRL_CONFIG": "/config/core.db", "MYTONCTRL_WALLETS": "/wallets",
                         "MYTONCTRL_CMD": "get sendTelemetry",
                         "MYTONCTRL_ARGS": "-m validator -n mainnet -d -s"}),
                         ["--config", "/config/core.db", "--wallets", "/wallets", "--cmd", "get sendTelemetry",
                          "--no-startup-checks"])

    def test_customized_unit_requires_restart_to_apply_parameters(self):
        state = self.root / "controller"
        services = state / "services"
        services.mkdir(parents=True)
        unit = services / "validator.service"
        unit.write_text("[Service]\nExecStart = /bin/validator-engine --threads 1\n")
        self.assertTrue(entrypoint.customize_validator({"CUSTOM_PARAMETERS": "--threads 2"}, state))
        self.assertIn("--threads 1 --threads 2", unit.read_text())
        self.assertFalse(entrypoint.customize_validator({}, state))

    def test_backup_metadata_is_checked_before_restoration(self):
        path = self.root / "backup.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, contents in (("./mytoncore/mytoncore.db", {"fift": {}, "liteClient": {}, "validatorConsole": {}}),
                                   ("./db/config.json", {"addrs": [], "control": []}), ("./keys/client", "key")):
                payload = json.dumps(contents).encode()
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
        entrypoint.check_backup(path)
        invalid = self.root / "invalid.tar.gz"
        with tarfile.open(invalid, "w:gz"):
            pass
        with self.assertRaisesRegex(ValueError, "missing mytoncore"):
            entrypoint.check_backup(invalid)


if __name__ == "__main__":
    unittest.main()
