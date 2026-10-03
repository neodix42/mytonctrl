"""Exercise the standalone deployment bootstrap without network or Docker."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


INSTALL_SCRIPT = Path(__file__).resolve().parents[2] / "install.sh"
EXISTING_NAMES = (".env", "compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deployment = self.root / "deployment"
        self.deployment.mkdir()
        self.tools = self.root / "bin"
        self.tools.mkdir()
        # PATH contains no real downloader or Docker executable.
        for name in ("bash", "cat", "mktemp", "rm", "chmod", "ln"):
            self.assertIsNotNone(shutil.which(name), f"Missing test utility: {name}")
            (self.tools / name).symlink_to(shutil.which(name))
        self.download_log = self.root / "downloads.jsonl"
        self.docker_log = self.root / "docker-called"
        self.env_template = self.root / "env.example"
        self.env_contents = (
            "# Downloaded configuration stays literal.\n"
            "MYTONCTRL_IMAGE=template:image\n"
            "PUBLIC_IP=\n"
            "MYTONCTRL_ARGS=-m validator -n mainnet -d\n"
            "SUBSTITUTION=$(touch unexpected)\n"
            "BACKTICKS=`touch unexpected-backtick`\n"
            "LITERAL=${HOME} # keep this text\n"
        )
        self.env_template.write_text(self.env_contents)
        self.compose_template = self.root / "compose-template.yml"
        self.compose_contents = "services:\n  mytonctrl:\n    image: ${MYTONCTRL_IMAGE}\n"
        self.compose_template.write_text(self.compose_contents)
        self.environment = dict(os.environ)
        self.environment.update(
            PATH=str(self.tools),
            INSTALL_TEST_DOWNLOAD_LOG=str(self.download_log),
            INSTALL_TEST_DOCKER_LOG=str(self.docker_log),
            INSTALL_TEST_ENV_TEMPLATE=str(self.env_template),
            INSTALL_TEST_COMPOSE_TEMPLATE=str(self.compose_template),
        )
        docker = self.tools / "docker"
        docker.write_text(
            f"#!{sys.executable}\n"
            "import os\nfrom pathlib import Path\n"
            "Path(os.environ['INSTALL_TEST_DOCKER_LOG']).write_text('unexpected Docker invocation')\n"
            "raise SystemExit(99)\n"
        )
        docker.chmod(0o755)

    def downloader(self, name):
        executable = self.tools / name
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json\nimport os\nfrom pathlib import Path\nimport shutil\nimport sys\n"
            "args = sys.argv[1:]\n"
            "tool = Path(sys.argv[0]).name\n"
            "flag = '--output' if tool == 'curl' else '-O'\n"
            "destination = Path(args[args.index(flag) + 1])\n"
            "url = args[-1]\n"
            "log = Path(os.environ['INSTALL_TEST_DOWNLOAD_LOG'])\n"
            "count = len(log.read_text().splitlines()) if log.exists() else 0\n"
            "with log.open('a') as output:\n"
            "    output.write(json.dumps({'tool': tool, 'url': url, 'args': args}) + '\\n')\n"
            "if count + 1 == int(os.environ.get('INSTALL_TEST_FAIL_DOWNLOAD', '0')):\n"
            "    destination.write_text('partial download')\n"
            "    raise SystemExit(22)\n"
            "if url.endswith('/.env.example'):\n"
            "    source = os.environ['INSTALL_TEST_ENV_TEMPLATE']\n"
            "elif url.endswith('/docker/compose.yml'):\n"
            "    source = os.environ['INSTALL_TEST_COMPOSE_TEMPLATE']\n"
            "else:\n"
            "    raise SystemExit('Unexpected asset URL: ' + url)\n"
            "shutil.copyfile(source, destination)\n"
        )
        executable.chmod(0o755)

    def run_install(self, args=(), stdin=False, directory=None, success=True):
        directory = directory or self.deployment
        if stdin:
            command = [str(self.tools / "bash"), "-s", "--", *args]
            payload = INSTALL_SCRIPT.read_text()
        else:
            command = [str(INSTALL_SCRIPT), *args]
            payload = None
        result = subprocess.run(command, input=payload, cwd=directory, env=self.environment,
                                capture_output=True, text=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.docker_log.exists(), "The bootstrap must not start Docker")
        self.assertFalse(list(directory.glob(".mytonctrl-install.*")), "Download staging files must be removed")
        return result

    def requests(self):
        if not self.download_log.exists():
            return []
        return [json.loads(line) for line in self.download_log.read_text().splitlines()]

    def assert_deployment(self, image, branch="master", tool="curl"):
        self.assertEqual((self.deployment / ".env").read_text(),
                         self.env_contents.replace("MYTONCTRL_IMAGE=template:image", "MYTONCTRL_IMAGE=" + image))
        self.assertEqual((self.deployment / "compose.yml").read_text(), self.compose_contents)
        self.assertEqual(stat.S_IMODE((self.deployment / ".env").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.deployment / "compose.yml").stat().st_mode), 0o644)
        self.assertEqual({path.name for path in self.deployment.iterdir()}, {".env", "compose.yml"})
        self.assertFalse((self.deployment / "unexpected").exists())
        self.assertFalse((self.deployment / "unexpected-backtick").exists())
        base = f"https://raw.githubusercontent.com/neodiX42/mytonctrl/{branch}"
        self.assertEqual([(request["tool"], request["url"]) for request in self.requests()],
                         [(tool, base + "/.env.example"), (tool, base + "/docker/compose.yml")])

    def test_executable_bootstrap_fetches_only_two_assets_and_defaults_to_latest(self):
        self.downloader("curl")
        self.downloader("wget")
        self.run_install()
        self.assert_deployment("ghcr.io/neodix42/mytonctrl:latest")

    def test_wget_stdin_bootstrap_selects_dev_assets_and_image(self):
        self.downloader("wget")
        self.run_install(["--branch", "dev"], stdin=True)
        self.assert_deployment("ghcr.io/neodix42/mytonctrl:dev", branch="dev", tool="wget")

    def test_explicit_master_branch_selects_latest_image(self):
        self.downloader("curl")
        self.run_install(["--branch", "master"])
        self.assert_deployment("ghcr.io/neodix42/mytonctrl:latest")

    def test_custom_image_changes_only_image_setting_and_keeps_asset_branch(self):
        self.downloader("wget")
        image = "registry.example.org/team/controller@sha256:" + "a" * 64
        self.run_install(["--branch", "dev", "--image", image], stdin=True)
        self.assert_deployment(image, branch="dev", tool="wget")

    def test_failed_second_download_installs_neither_file_and_removes_staging(self):
        self.downloader("curl")
        self.environment["INSTALL_TEST_FAIL_DOWNLOAD"] = "2"
        result = self.run_install(success=False)
        self.assertIn("Download failed", result.stderr)
        self.assertEqual(len(self.requests()), 2)
        self.assertEqual(list(self.deployment.iterdir()), [])

    def test_empty_second_download_installs_neither_file(self):
        self.downloader("wget")
        self.compose_template.write_text("")
        result = self.run_install(stdin=True, success=False)
        self.assertIn("Downloaded file is empty", result.stderr)
        self.assertEqual(list(self.deployment.iterdir()), [])

    def test_existing_environment_or_any_compose_filename_is_preserved(self):
        self.downloader("curl")
        for index, name in enumerate(EXISTING_NAMES):
            directory = self.root / f"existing-file-{index}"
            directory.mkdir()
            original = directory / name
            original.write_text("existing deployment must survive\n")
            with self.subTest(name=name):
                result = self.run_install(directory=directory, success=False)
                self.assertIn(name + " already exists", result.stderr)
                self.assertEqual(original.read_text(), "existing deployment must survive\n")
                self.assertEqual({path.name for path in directory.iterdir()}, {name})
        self.assertEqual(self.requests(), [])

    def test_existing_dangling_symlinks_are_preserved_before_download(self):
        self.downloader("wget")
        for index, name in enumerate(EXISTING_NAMES):
            directory = self.root / f"existing-link-{index}"
            directory.mkdir()
            original = directory / name
            original.symlink_to("missing-target")
            with self.subTest(name=name):
                result = self.run_install(stdin=True, directory=directory, success=False)
                self.assertIn(name + " already exists", result.stderr)
                self.assertTrue(original.is_symlink())
                self.assertEqual(os.readlink(original), "missing-target")
                self.assertEqual({path.name for path in directory.iterdir()}, {name})
        self.assertEqual(self.requests(), [])

    def test_existing_symlink_and_its_target_are_preserved(self):
        self.downloader("curl")
        target = self.root / "existing-config"
        target.write_text("external deployment configuration\n")
        original = self.deployment / "compose.yaml"
        original.symlink_to(target)
        self.run_install(success=False)
        self.assertTrue(original.is_symlink())
        self.assertEqual(target.read_text(), "external deployment configuration\n")
        self.assertEqual(self.requests(), [])

    def test_existing_compose_directory_is_preserved(self):
        self.downloader("curl")
        original = self.deployment / "compose.yml"
        original.mkdir()
        (original / "data").write_text("preserved")
        self.run_install(success=False)
        self.assertEqual((original / "data").read_text(), "preserved")
        self.assertEqual(self.requests(), [])

    def test_invalid_flags_and_images_fail_before_fetch_or_filesystem_changes(self):
        self.downloader("curl")
        invalid = (["--unknown"], ["--branch"], ["--image"], ["--branch", "other"],
                   ["--image", "image with spaces"], ["--image", "$(touch unexpected)"])
        for args in invalid:
            with self.subTest(args=args):
                self.run_install(args, success=False)
                self.assertEqual(list(self.deployment.iterdir()), [])
        self.assertEqual(self.requests(), [])

    def test_help_needs_no_downloader_or_docker(self):
        result = self.run_install(["--help"], stdin=True)
        self.assertIn("--branch master|dev", result.stdout)
        self.assertIn("does not start containers", result.stdout)
        self.assertEqual(self.requests(), [])
        self.assertEqual(list(self.deployment.iterdir()), [])

    def test_missing_downloader_fails_without_creating_deployment_files(self):
        result = self.run_install(success=False)
        self.assertIn("Install wget or curl", result.stderr)
        self.assertEqual(list(self.deployment.iterdir()), [])

    def test_ambiguous_image_template_installs_neither_file(self):
        self.downloader("wget")
        self.env_template.write_text("MYTONCTRL_IMAGE=first\nMYTONCTRL_IMAGE=second\n")
        result = self.run_install(stdin=True, success=False)
        self.assertIn("must contain one MYTONCTRL_IMAGE", result.stderr)
        self.assertEqual(len(self.requests()), 2)
        self.assertEqual(list(self.deployment.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
