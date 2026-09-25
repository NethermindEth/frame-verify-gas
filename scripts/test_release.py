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
        self.comment = {"user": {"type": "User", "login": "manusw7"}, "author_association": "MEMBER",
                        "body": "", "html_url": "https://github.com/example/review",
                        "created_at": "2026-09-14T10:00:00Z", "updated_at": "2026-09-14T10:00:00Z"}

    def api(self, path):
        return self.comment if "comments/" in path else self.run

    def gh(self, *args):
        component = args[args.index("--name") + 1]
        destination = Path(args[args.index("--dir") + 1])
        for label in release.package.LABELS:
            if (label == "soispoke") == (component == "soispoke-candidate"):
                shutil.copyfile(self.assets / f"sweep-{label}.tar.gz", destination / f"sweep-{label}.tar.gz")
        return ""

    def prepare(self, output="review", signoff=None, version="v1.0.0", dispatcher="publisher"):
        args = argparse.Namespace(repo="NethermindEth/frame-verify-gas", version=version,
                                  commit="b" * 40, synthetic_run=1, soispoke_run=2,
                                  output=self.root / output, signoff_comment=signoff, dispatcher=dispatcher)
        with patch.object(release, "api", self.api), patch.object(release, "gh", self.gh), contextlib.redirect_stdout(io.StringIO()):
            release.prepare(args)
        return args.output

    def test_named_review_binds_exact_assets_and_records_upstream_commit(self):
        output = self.prepare()
        self.comment["body"] = (output / "SIGNOFF-REQUIRED.txt").read_text()
        signed = self.prepare("signed", 123)
        notes = (signed / "RELEASE-NOTES.md").read_text()
        self.assertIn("manusw7", notes)
        self.assertIn("a" * 40, notes)
        self.assertEqual(len((signed / "SHA256SUMS").read_text().splitlines()), 5)

    def test_rejects_unreviewed_or_changed_assets(self):
        output = self.prepare()
        self.comment["body"] = (output / "SIGNOFF-REQUIRED.txt").read_text()
        with patch.dict(self.comment, {"body": "approved"}):
            with self.assertRaisesRegex(ValueError, "sign-off"):
                self.prepare("body", 123)
        with patch.dict(self.comment["user"], {"login": "someone-else"}):
            with self.assertRaisesRegex(ValueError, "sign-off"):
                self.prepare("unauthorized", 123)
        with patch.dict(self.comment["user"], {"type": "Bot"}):
            with self.assertRaisesRegex(ValueError, "sign-off"):
                self.prepare("bot", 123)
        asset = self.assets / "sweep-250k.tar.gz"
        asset.write_bytes(asset.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "sign-off"):
            self.prepare("changed", 123)

    def test_rejects_edited_or_self_signoff(self):
        output = self.prepare()
        self.comment["body"] = (output / "SIGNOFF-REQUIRED.txt").read_text()
        with patch.dict(self.comment, {"updated_at": "2026-09-14T11:00:00Z"}):
            with self.assertRaisesRegex(ValueError, "sign-off"):
                self.prepare("edited", 123)
        with self.assertRaisesRegex(ValueError, "sign-off"):
            self.prepare("self", 123, dispatcher="Manusw7")
        with self.assertRaisesRegex(ValueError, "--dispatcher"):
            self.prepare("no-dispatcher", 123, dispatcher=None)

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
