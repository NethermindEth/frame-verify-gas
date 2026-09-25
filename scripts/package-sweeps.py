#!/usr/bin/env python3
"""Package measured sweeps; never publish proving keys or symlinks."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

SYNTHETIC_LABELS = ("250k", "300k", "400k", "500k")
SOISPOKE_LABELS = ("soispoke",)
LABELS = SYNTHETIC_LABELS + SOISPOKE_LABELS


def validate(root):
    for name in ("verifier.hex", "calldata-invalid.hex"):
        value = (root / name).read_text().strip().removeprefix("0x")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", value):
            raise ValueError(f"{root / name}: expected nonempty, byte-aligned hex")
        if name == "verifier.hex" and not 1000 <= len(value) // 2 <= 24576:
            raise ValueError(f"{root}: implausible verifier size")
    if root.name == "sweep-soispoke":
        provenance = json.loads((root / "provenance.json").read_text())
        manifest_path = root / "activation_manifest.testbed.json"
        manifest = json.loads(manifest_path.read_text())
        pinned_hashes = provenance.get("input_sha256", {})
        if (provenance.get("profile") != "position-notes-v2" or provenance.get("test_only") is not True
                or provenance.get("declared_budget_gas") != 235800
                or provenance.get("declared_verify_frame_gas") != 225000
                or provenance.get("declared_recent_root_frame_gas") != 8000
                or provenance.get("declared_signature_gas") != 2800):
            raise ValueError(f"{root}: unexpected soispoke profile provenance")
        if (manifest.get("production") is not False
                or manifest.get("ceremony", {}).get("phase2_contributions") != 1
                or manifest.get("ceremony", {}).get("independent_verification") is not None
                or manifest.get("profile", {}).get("required_verify_budget") != 235800
                or manifest.get("profile", {}).get("verify_frame_gas") != 225000
                or manifest.get("profile", {}).get("recent_root_frame_gas") != 8000
                or manifest.get("profile", {}).get("signature_gas") != 2800):
            raise ValueError(f"{root}: test-only setup or declared budget does not match the pinned profile")
        for upstream_path, packaged_path in (
                ("activation_manifest.testbed.json", manifest_path),
                ("contracts/src/Groth16Verifier.sol", root / "source/src/Groth16Verifier.sol"),
                ("contracts/foundry.toml", root / "source/upstream-foundry.toml"),
                ("tooling/patch_verifier.py", root / "source/tooling/patch_verifier.py"),
                ("LICENSE", root / "source/LICENSE.upstream-Apache-2.0"),
                ("NOTICE", root / "source/NOTICE")):
            if hashlib.sha256(packaged_path.read_bytes()).hexdigest() != pinned_hashes.get(upstream_path):
                raise ValueError(f"{root}: packaged source does not match pinned input {upstream_path}")
        measured_gas = int((root / "gas.txt").read_text().strip())
        if provenance.get("measurements", {}).get("input", {}).get("gas") != measured_gas:
            raise ValueError(f"{root}: gas.txt disagrees with the measured invalid-input trace")
    else:
        metadata = json.loads((root / "metadata.json").read_text())
        warning = "never use to secure value"
        if warning not in metadata.get("WARNING", "") or warning not in (root / "README.txt").read_text():
            raise ValueError(f"{root}: missing benchmark-only setup warning")
    ceiling = {"sweep-250k": 250000, "sweep-300k": 300000, "sweep-400k": 400000,
               "sweep-500k": 500000, "sweep-soispoke": 235800}[root.name]
    if not 150000 < int((root / "gas.txt").read_text().strip()) <= ceiling:
        raise ValueError(f"{root}: implausible measured execution gas")


def package(root, output, labels):
    output.mkdir(parents=True, exist_ok=True)
    for label in labels:
        sweep = root / f"sweep-{label}"
        validate(sweep)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(sweep.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"symlink forbidden: {path}")
                if path.is_dir():
                    continue
                if {"out", "cache"}.intersection(path.relative_to(sweep).parts):
                    raise ValueError(f"compiler build output must not be packaged: {path}")
                if path.suffix in (".key", ".zkey", ".r1cs", ".wasm"):
                    raise ValueError(f"setup/build material must not be packaged: {path}")
                data = path.read_bytes()
                info = tarfile.TarInfo(str(path.relative_to(root)))
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
        (output / f"sweep-{label}.tar.gz").write_bytes(gzip.compress(buffer.getvalue(), mtime=0))


def manifest(output):
    paths = [output / f"sweep-{label}.tar.gz" for label in LABELS]
    result = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in paths)
    (output / "SHA256SUMS").write_text(result)
    return hashlib.sha256(result.encode()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--component", choices=("synthetic", "soispoke"), required=True)
    args = parser.parse_args()
    package(args.root, args.output, SYNTHETIC_LABELS if args.component == "synthetic" else SOISPOKE_LABELS)
