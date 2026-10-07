"""Check actual Compose interpolation without starting the node or using Docker's daemon."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (ROOT / "compose.yaml", ROOT / "docker/compose.yml")


def compose_available():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(
            ["docker", "compose", "version"], capture_output=True, timeout=10
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(compose_available(), "Docker Compose is not installed")
class ComposeStorageTests(unittest.TestCase):
    def render(self, compose_file, host_dir, work_volume="mytonctrl-ton-work"):
        environment = {
            **os.environ,
            "MYTONCTRL_ENV_FILE": str(ROOT / ".env.example"),
            "TON_WORK_VOLUME": work_volume,
        }
        if host_dir is None:
            environment.pop("TON_WORK_HOST_DIR", None)
        else:
            environment["TON_WORK_HOST_DIR"] = host_dir
        return subprocess.run(
            ["docker", "compose", "--env-file", str(ROOT / ".env.example"),
             "-f", str(compose_file), "config", "--format", "json"],
            env=environment, capture_output=True, text=True, timeout=20,
        )

    def test_configured_directory_with_spaces_is_used_without_a_data_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            host_dir = Path(directory) / "external disk" / "ton-work"
            host_dir.mkdir(parents=True)
            for compose_file in COMPOSE_FILES:
                with self.subTest(compose_file=compose_file.name):
                    result = self.render(compose_file, str(host_dir))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    config = json.loads(result.stdout)
                    mounts = config["services"]["mytonctrl"]["volumes"]
                    work = next(mount for mount in mounts if mount["target"] == "/var/ton-work")
                    self.assertEqual(work["type"], "bind")
                    self.assertEqual(work["source"], str(host_dir))
                    self.assertNotIn("ton-work", config["volumes"])

    def test_blank_or_unset_storage_path_uses_the_original_named_volume(self):
        for compose_file in COMPOSE_FILES:
            for host_dir in ("", None):
                with self.subTest(compose_file=compose_file.name, host_dir=host_dir):
                    result = self.render(compose_file, host_dir)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    config = json.loads(result.stdout)
                    mounts = config["services"]["mytonctrl"]["volumes"]
                    work = next(mount for mount in mounts if mount["target"] == "/var/ton-work")
                    self.assertEqual(work["type"], "volume")
                    self.assertEqual(work["source"], "ton-work")
                    self.assertEqual(config["volumes"]["ton-work"]["name"], "mytonctrl-ton-work")

    def test_custom_named_volume_is_preserved_when_host_path_is_blank(self):
        for compose_file in COMPOSE_FILES:
            with self.subTest(compose_file=compose_file.name):
                result = self.render(compose_file, "", "existing-ton-work")
                self.assertEqual(result.returncode, 0, result.stderr)
                config = json.loads(result.stdout)
                self.assertEqual(config["volumes"]["ton-work"]["name"], "existing-ton-work")


if __name__ == "__main__":
    unittest.main()
