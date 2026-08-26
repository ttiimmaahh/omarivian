import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "local-plugin"
PLUGIN_ID = "io.github.ttiimmaahh.omarivian"


class LocalPluginHelperTests(unittest.TestCase):
    def test_install_waits_until_rescanned_plugin_is_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            bin_dir = root / "bin"
            bin_dir.mkdir()

            omarchy = bin_dir / "omarchy"
            omarchy.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    state="$HOME/discovery-count"
                    ready="$HOME/plugin-ready"
                    case "${{1:-}} ${{2:-}}" in
                      "plugin validate") exit 0 ;;
                      "plugin list")
                        count=0
                        [[ ! -f "$state" ]] || count=$(cat "$state")
                        count=$((count + 1))
                        printf '%s' "$count" > "$state"
                        if (( count >= 2 )); then
                          touch "$ready"
                          printf '[{{"id":"{PLUGIN_ID}"}}]\n'
                        else
                          printf '[]\n'
                        fi
                        ;;
                      "plugin enable")
                        if [[ ! -f "$ready" ]]; then
                          echo "omarchy-plugin-enable: plugin '$3' is not known; run: omarchy-shell shell rescanPlugins" >&2
                          exit 1
                        fi
                        ;;
                      *) exit 0 ;;
                    esac
                    """
                )
            )
            shell = bin_dir / "omarchy-shell"
            shell.write_text("#!/usr/bin/env bash\nexit 0\n")
            omarchy.chmod(0o755)
            shell.chmod(0o755)

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                [str(HELPER), "install"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plugin = home / ".config" / "omarchy" / "plugins" / PLUGIN_ID
            self.assertTrue(plugin.is_symlink())
            self.assertEqual(plugin.resolve(), ROOT)

    def test_release_replaces_local_link_with_latest_stable_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            bin_dir = root / "bin"
            remote = root / "remote"
            bin_dir.mkdir()
            remote.mkdir()

            subprocess.run(["git", "init", "-q", str(remote)], check=True)
            subprocess.run(
                ["git", "-C", str(remote), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(remote), "config", "user.name", "Test"],
                check=True,
            )
            manifest = remote / "manifest.json"
            manifest.write_text(json.dumps({"id": PLUGIN_ID, "version": "0.1.0"}))
            subprocess.run(["git", "-C", str(remote), "add", "manifest.json"], check=True)
            subprocess.run(["git", "-C", str(remote), "commit", "-qm", "v0.1.0"], check=True)
            subprocess.run(["git", "-C", str(remote), "tag", "v0.1.0"], check=True)
            manifest.write_text(json.dumps({"id": PLUGIN_ID, "version": "0.2.0"}))
            subprocess.run(["git", "-C", str(remote), "commit", "-qam", "v0.2.0"], check=True)
            subprocess.run(["git", "-C", str(remote), "tag", "v0.2.0"], check=True)

            omarchy = bin_dir / "omarchy"
            omarchy.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    plugin="$HOME/.config/omarchy/plugins/{PLUGIN_ID}"
                    case "${{1:-}} ${{2:-}}" in
                      "plugin validate") exit 0 ;;
                      "plugin remove") rm -rf -- "$plugin" ;;
                      "plugin add") mkdir -p -- "$(dirname -- "$plugin")"; git clone -q -- "$3" "$plugin" ;;
                      "plugin list") printf '[{{"id":"{PLUGIN_ID}"}}]\\n' ;;
                      "plugin enable") exit 0 ;;
                      *) exit 0 ;;
                    esac
                    """
                )
            )
            shell = bin_dir / "omarchy-shell"
            shell.write_text("#!/usr/bin/env bash\nexit 0\n")
            omarchy.chmod(0o755)
            shell.chmod(0o755)

            plugin = home / ".config" / "omarchy" / "plugins" / PLUGIN_ID
            plugin.parent.mkdir(parents=True)
            plugin.symlink_to(ROOT, target_is_directory=True)
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["OMARIVIAN_REPO_URL"] = str(remote)
            result = subprocess.run(
                [str(HELPER), "release"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(plugin.is_symlink())
            self.assertTrue((plugin / ".git").is_dir())
            tag = subprocess.run(
                ["git", "-C", str(plugin), "describe", "--tags", "--exact-match"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(tag, "v0.2.0")


if __name__ == "__main__":
    unittest.main()
