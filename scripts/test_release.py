import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("release", Path(__file__).with_name("prepare-release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        for label in release.package.LABELS:
            files = ["verifier.hex", "calldata-invalid.hex", "gas.txt"]
            if label == "soispoke":
                files += ["provenance.json", "activation_manifest.testbed.json", "trace.txt", "source/src/Groth16Verifier.sol",
                          "source/COPYING", "source/LICENSE.upstream-Apache-2.0",
                          "source/README.md", "source/foundry.toml", "source/scripts/soispoke.py", "source/scripts/licenses/GPL-3.0.txt", "source/LICENSE.pipeline-MIT",
                          "source/test/Fixture.t.sol", "source/NOTICE", "source/upstream-foundry.toml", "source/tooling/patch_verifier.py"]
            else:
                files += ["README.txt", "Verifier.sol", "proof.json", "metadata.json", "trace-valid.txt", "trace-invalid.txt"]
            manifest_data = json.dumps({
                "production": False,
                "ceremony": {"phase2_contributions": 1, "independent_verification": None},
                "profile": {"required_verify_budget": 235800, "verify_frame_gas": 225000,
                            "recent_root_frame_gas": 8000, "signature_gas": 2800},
            }).encode()
            with tarfile.open(self.assets / f"sweep-{label}.tar.gz", "w:gz") as archive:
                for filename in files:
                    if filename == "provenance.json":
                        data = json.dumps({
                            "commit": "a" * 40,
                            "profile": "position-notes-v2",
                            "test_only": True,
                            "declared_budget_gas": 235800,
                            "declared_verify_frame_gas": 225000,
                            "declared_recent_root_frame_gas": 8000,
                            "declared_signature_gas": 2800,
                            "measurements": {"input": {"gas": 202307}},
                            "input_sha256": {
                                "activation_manifest.testbed.json": hashlib.sha256(manifest_data).hexdigest(),
                                "contracts/src/Groth16Verifier.sol": hashlib.sha256(b"evidence").hexdigest(),
                                "contracts/foundry.toml": hashlib.sha256(b"evidence").hexdigest(),
                                "tooling/patch_verifier.py": hashlib.sha256(b"evidence").hexdigest(),
                                "LICENSE": hashlib.sha256(b"evidence").hexdigest(),
                                "NOTICE": hashlib.sha256(b"evidence").hexdigest(),
                            },
                        }).encode()
                    elif filename == "activation_manifest.testbed.json":
                        data = manifest_data
                    elif filename == "gas.txt" and label == "soispoke":
                        data = b"202307"
                    else:
                        data = b"evidence"
                    member = tarfile.TarInfo(f"sweep-{label}/{filename}")
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        self.run = {"conclusion": "success", "event": "workflow_dispatch", "head_sha": "b" * 40,
                    "head_repository": {"full_name": "NethermindEth/frame-verify-gas"},
                    "path": ".github/workflows/build-groth16-candidates.yml"}
    def api(self, path):
        return self.run

    def gh(self, *args):
        component = args[args.index("--name") + 1]
        destination = Path(args[args.index("--dir") + 1])
        for label in release.package.LABELS:
            if (label == "soispoke") == (component == "soispoke-candidate"):
                shutil.copyfile(self.assets / f"sweep-{label}.tar.gz", destination / f"sweep-{label}.tar.gz")
        return ""

    def prepare(self, output="review", version="v1.0.0"):
        args = argparse.Namespace(repo="NethermindEth/frame-verify-gas", version=version,
                                  commit="b" * 40, synthetic_run=1, soispoke_run=2,
                                  output=self.root / output)
        with patch.object(release, "api", self.api), patch.object(release, "gh", self.gh), contextlib.redirect_stdout(io.StringIO()):
            release.prepare(args)
        return args.output

    def test_prepares_release_notes_from_pinned_candidate_runs(self):
        output = self.prepare()
        notes = (output / "RELEASE-NOTES.md").read_text()
        self.assertIn("Source commit: " + "b" * 40, notes)
        self.assertIn("a" * 40, notes)
        self.assertIn("Synthetic build: https://github.com/NethermindEth/frame-verify-gas/actions/runs/1", notes)
        self.assertIn("Soispoke build: https://github.com/NethermindEth/frame-verify-gas/actions/runs/2", notes)
        self.assertIn("SHA256SUMS SHA256:", notes)
        self.assertEqual(len((output / "SHA256SUMS").read_text().splitlines()), 5)
        self.assertFalse((output / "SIGNOFF-REQUIRED.txt").exists())

    def test_rejects_wrong_candidate_provenance(self):
        for field, value in (("head_sha", "c" * 40), ("conclusion", "failure"),
                             ("event", "pull_request"), ("path", "different.yml")):
            with self.subTest(field=field), patch.dict(self.run, {field: value}):
                with self.assertRaisesRegex(ValueError, "successful candidate"):
                    self.prepare(field)

    def test_rejects_missing_corresponding_source_and_unsafe_archive(self):
        for index, filename in enumerate(("sweep-soispoke/verifier.hex", "../escape", "sweep-soispoke/./alias", ".")):
            with tarfile.open(self.assets / "sweep-soispoke.tar.gz", "w:gz") as archive:
                member = tarfile.TarInfo(filename)
                archive.addfile(member, io.BytesIO())
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.prepare(f"bad-{index}")

    def test_rejects_invalid_version_before_download(self):
        for version in ("latest", "v01.2.3", "v1.2.3-rc1", "../v1.2.3"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "version"):
                self.prepare(version=version)


if __name__ == "__main__":
    unittest.main()
