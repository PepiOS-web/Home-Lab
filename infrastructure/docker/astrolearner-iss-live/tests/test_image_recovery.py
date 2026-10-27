"""Fake-Docker shell integration tests; no root, Docker daemon or credentials."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "enable-browser-camera.sh"


class RecoverySourceTests(unittest.TestCase):
    def test_recovery_precedes_configuration_replacement(self):
        source = SCRIPT.read_text(encoding="utf-8")
        assert source.index("preserve_image iss-live") < source.index('mv -- "$prepared_env" .env')
        assert source.index('preserve_image camera-browser') < source.index('mv -- "$prepared_env" .env')
        assert 'compose_current build "$service"' in source
        assert 'docker commit' not in source and 'docker export' not in source
        assert 'rebuilt-current-source' in source
        assert source.count('stopped ||') == 2


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Shell integration requires native POSIX bash")
class RecoveryShellTests(unittest.TestCase):
    def run_case(self, mode, service="iss-live"):
        source = SCRIPT.read_text(encoding="utf-8")
        match = re.search(r"^preserve_image\(\) \{\n.*?^\}", source, re.M | re.S)
        self.assertIsNotNone(match)
        original, rebuilt = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        reference = "astrolearner-iss-live:local" if service == "iss-live" else "astrolearner-iss-camera-browser:local"
        record = "image-id" if service == "iss-live" else "browser-image-id"
        fake = r'''
docker() {
    if [[ "$1" == inspect ]]; then
        if [[ "$MODE" == bad_original ]]; then printf '%s\n' invalid; else printf '%s\n' "$ORIGINAL"; fi
    elif [[ "$1 $2" == 'image inspect' && "$3" == --format ]]; then
        [[ "$5" == "$REFERENCE" ]] || return 80
        [[ "$MODE" != inspect_failure ]] || return 81
        if [[ "$MODE" == bad_rebuilt ]]; then printf '%s\n' invalid; else printf '%s\n' "$REBUILT"; fi
    elif [[ "$1 $2" == 'image inspect' ]]; then
        [[ "$MODE" == original || "$MODE" == tag_failure_original ]]
    elif [[ "$1 $2" == 'image tag' ]]; then
        printf 'TAG %s\n' "$3" >> "$backup_dir/calls"
        [[ "$MODE" != tag_failure && "$MODE" != tag_failure_original ]]
    else return 82; fi
}
compose_current() {
    [[ "$1" == build && "$2" == "$SERVICE" && "$#" == 2 ]] || return 83
    printf 'BUILD %s\n' "$2" >> "$backup_dir/calls"
    [[ "$MODE" != build_failure ]]
}
'''
        with tempfile.TemporaryDirectory(prefix="iss-recovery-unit-") as temporary:
            env = {**os.environ, "MODE": mode, "ORIGINAL": original, "REBUILT": rebuilt,
                   "REFERENCE": reference, "SERVICE": service, "backup_dir": temporary}
            code = "set -Eeuo pipefail\n" + fake + "\n" + match[0] + "\n"
            code += f'preserve_image "$SERVICE" container "$REFERENCE" {record} recovery:unit || exit 1\n'
            result = subprocess.run(["bash", "-c", code], env=env, capture_output=True, text=True, timeout=10)
            files = {p.name: p.read_text() for p in Path(temporary).iterdir()}
        return result, files, original, rebuilt

    def test_original_image_is_preserved_without_build(self):
        result, files, original, _ = self.run_case("original")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(files["image-id"].strip(), original)
        self.assertEqual(files["original-image-id"].strip(), original)
        self.assertEqual(files["image-id.origin"].strip(), "original")
        self.assertNotIn("BUILD", files["calls"])

    def test_missing_main_image_gets_explicitly_rebuilt_recovery(self):
        result, files, original, rebuilt = self.run_case("missing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(files["image-id"].strip(), rebuilt)
        self.assertEqual(files["original-image-id"].strip(), original)
        self.assertEqual(files["image-id.origin"].strip(), "rebuilt-current-source")
        self.assertEqual(files["calls"].splitlines(), ["BUILD iss-live", "TAG " + rebuilt])

    def test_missing_browser_image_has_its_own_recovery_record(self):
        result, files, _, rebuilt = self.run_case("missing", service="camera-browser")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(files["browser-image-id"].strip(), rebuilt)
        self.assertIn("BUILD camera-browser", files["calls"])

    def test_failures_never_publish_an_unusable_recovery_record(self):
        for mode in ("build_failure", "inspect_failure", "bad_original", "bad_rebuilt", "tag_failure", "tag_failure_original"):
            with self.subTest(mode=mode):
                result, files, _, _ = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("image-id", files)


if __name__ == "__main__":
    unittest.main()
