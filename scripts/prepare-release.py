#!/usr/bin/env python3
"""Validate and assemble successful candidate runs without rebuilding their artifacts."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tarfile

spec = importlib.util.spec_from_file_location("package", Path(__file__).with_name("package-sweeps.py"))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)

def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def api(path):
    return json.loads(gh("api", path))


def prepare(args):
    if not re.fullmatch(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", args.version):
        raise ValueError("expected version vMAJOR.MINOR.PATCH without prerelease suffix")
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("expected full candidate commit SHA")
    args.output.mkdir(parents=True, exist_ok=False)
    for component, run_id in (("synthetic", args.synthetic_run), ("soispoke", args.soispoke_run)):
        run = api(f"repos/{args.repo}/actions/runs/{run_id}")
        if (run["conclusion"] != "success" or run["event"] != "workflow_dispatch"
                or run["head_sha"] != args.commit or run["head_repository"]["full_name"] != args.repo
                or run["path"] != ".github/workflows/build-groth16-candidates.yml"):
            raise ValueError(f"{component} run must be a successful candidate build of {args.repo}@{args.commit}")
        gh("run", "download", str(run_id), "--repo", args.repo,
           "--name", f"{component}-candidate", "--dir", str(args.output))
    expected = {f"sweep-{label}.tar.gz" for label in package.LABELS}
    if {p.name for p in args.output.iterdir()} != expected:
        raise ValueError("candidate assets must contain exactly five sweep archives")
    for label in package.LABELS:
        with tarfile.open(args.output / f"sweep-{label}.tar.gz") as archive:
            names = set()
            total = 0
            for member in archive:
                name = Path(member.name)
                total += member.size
                if (not member.isfile() or name.is_absolute() or str(name) != member.name or ".." in name.parts
                        or not name.parts or name.parts[0] != f"sweep-{label}" or member.name in names
                        or total > 32 * 1024 * 1024):
                    raise ValueError(f"unsafe archive member: {member.name}")
                names.add(member.name)
            required_files = ["verifier.hex", "calldata-invalid.hex", "gas.txt"]
            if label == "soispoke":
                required_files += ["provenance.json", "activation_manifest.testbed.json", "trace.txt", "source/src/Groth16Verifier.sol",
                                   "source/COPYING", "source/LICENSE.upstream-Apache-2.0",
                                   "source/README.md", "source/foundry.toml", "source/scripts/soispoke.py", "source/scripts/licenses/GPL-3.0.txt", "source/LICENSE.pipeline-MIT",
                                   "source/test/Fixture.t.sol", "source/NOTICE", "source/upstream-foundry.toml", "source/tooling/patch_verifier.py"]
            else:
                required_files += ["README.txt", "Verifier.sol", "proof.json", "metadata.json",
                                   "trace-valid.txt", "trace-invalid.txt"]
            for required in required_files:
                if f"sweep-{label}/{required}" not in names:
                    raise ValueError(f"missing {required} in {label}")
    digest = package.manifest(args.output)
    with tarfile.open(args.output / "sweep-soispoke.tar.gz") as archive:
        provenance = json.load(archive.extractfile("sweep-soispoke/provenance.json"))
        manifest = json.load(archive.extractfile("sweep-soispoke/activation_manifest.testbed.json"))
        measured_gas = int(archive.extractfile("sweep-soispoke/gas.txt").read())
    upstream_commit = provenance["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", upstream_commit):
        raise ValueError("missing pinned soispoke commit")
    if (provenance.get("profile") != "position-notes-v2" or provenance.get("test_only") is not True
            or any(provenance.get(key) != value for key, value in package.SOISPOKE_PROFILE.items()
                   if key.startswith("declared_"))
            or provenance.get("measurements", {}).get("input", {}).get("gas") != measured_gas):
        raise ValueError("soispoke candidate is not the pinned, measured position-notes-v2 profile")
    if (manifest.get("production") is not False
            or manifest.get("ceremony", {}).get("phase2_contributions") != 1
            or manifest.get("ceremony", {}).get("independent_verification") is not None
            or any(manifest.get("profile", {}).get(key) != value for key, value in package.SOISPOKE_PROFILE.items()
                   if not key.startswith("declared_"))):
        raise ValueError("soispoke manifest no longer identifies the pinned test-only profile")
    pinned_hashes = provenance.get("input_sha256", {})
    with tarfile.open(args.output / "sweep-soispoke.tar.gz") as archive:
        for upstream_path, packaged_path in (
                ("activation_manifest.testbed.json", "sweep-soispoke/activation_manifest.testbed.json"),
                ("contracts/src/Groth16Verifier.sol", "sweep-soispoke/source/src/Groth16Verifier.sol"),
                ("contracts/foundry.toml", "sweep-soispoke/source/upstream-foundry.toml"),
                ("tooling/patch_verifier.py", "sweep-soispoke/source/tooling/patch_verifier.py"),
                ("LICENSE", "sweep-soispoke/source/LICENSE.upstream-Apache-2.0"),
                ("NOTICE", "sweep-soispoke/source/NOTICE")):
            if hashlib.sha256(archive.extractfile(packaged_path).read()).hexdigest() != pinned_hashes.get(upstream_path):
                raise ValueError(f"packaged source does not match pinned input {upstream_path}")
    notes = ("Benchmark-only disposable Groth16 setups; never use for production funds.\n"
             "The soispoke position-notes-v2 setup has one phase-2 contribution and no independent verification.\n\n"
             f"Source commit: {args.commit}\n"
             f"Pinned soispoke source: https://github.com/soispoke/minimal-shielded-pool/tree/{upstream_commit}\n"
             f"Synthetic build: https://github.com/{args.repo}/actions/runs/{args.synthetic_run}\n"
             f"Soispoke build: https://github.com/{args.repo}/actions/runs/{args.soispoke_run}\n\n"
             f"SHA256SUMS SHA256: `{digest}`\n\n"
             "The soispoke archive includes the pinned upstream commit, GPL-3.0 verifier source, "
             "license, attribution, build settings and measured gas reconciliation.\n")
    (args.output / "RELEASE-NOTES.md").write_text(notes)
    print(f"Prepared {args.version} from {args.commit}; SHA256SUMS SHA256: {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="NethermindEth/frame-verify-gas")
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--synthetic-run", required=True, type=int)
    parser.add_argument("--soispoke-run", required=True, type=int)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args())
