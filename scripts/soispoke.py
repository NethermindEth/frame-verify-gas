#!/usr/bin/env python3
"""Extract the pinned position-notes-v2 fixture; never use a floating ref."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PIN = "6dedda193bf09c9d80cd89b3dc23eccf580d1026"
UPSTREAM = "https://github.com/soispoke/minimal-shielded-pool.git"
FOUNDRY_VERSION = "1.8.3"
HASHES = {
    "build/spend.r1cs": "e2f6fc89bc0e478231935d7dab10fb07316f2c6dab4303e95da1a390ce84f9bf",
    "build/spend_final.zkey": "587c048b06d68c61dcb0a9a57b51229def97b219b11827042f4a8faa49499376",
    "build/spend_js/spend.wasm": "9066dcaae1f8a215fc5adb0bfdf6c1e117fbcb09e22e5a80df33aa582346c1db",
    "circuits/spend.circom": "97c24b754549fd576c1e3d1e70345eba5570143895a0a9cceeb7e22176cdf8af",
    "contracts/foundry.toml": "af279592ce45b3be466ff10f0d20c4b3107ba47776259a738176fc789d59b817",
    "contracts/src/Groth16Verifier.sol": "5bcda629ac9fa4317d52aef102281b12419c1c385abfe0fa991c5ed22e906676",
    "contracts/src/PoseidonT3.sol": "f353af63ac124e51a37e78dc5278bcb2e93c19e44aa8dd13a4ecb4c54212720b",
    "contracts/src/PoseidonT4.sol": "2384b8f71a2ed09f3b16c6b0d135bedcd293cb1c862e8a3c893d0ac79eae0960",
    "contracts/src/ShieldedPoolLogic.sol": "fa9d7b1fc5fdca83c3a78cdd81cd3856dbfc9e18d20095054c22c6c248ad753b",
    "devnet/ShieldedPoolDispatcher.yul": "32e4701834435d2157cdb1acda219fa16957b5e7b3abae64eede7f2ddd29ea60",
    "devnet/build/shielded_pool_dispatcher_init.hex": "8339dab370f7fc24a7584d48d08df7bd21296b6840a4bc66fbb8165ea35e1bf4",
    "devnet/frametx.py": "ac008480a576bae7543287f7488afb93c1b12c1cdf103f95e0f933b68823d459",
    "devnet/gas_profile.py": "4771bc7e251a14cc2a0ea806c0d804d6eae8cfdeec11cce8d42aab6c0fd2755a",
    "devnet/pool_frametx.py": "63455698703111fb1a1becfeaa00456ed8080cb0945c8c49aae7c82ef69ee232",
    "tooling/check_gas_profile.py": "e0a9679d2ed26e20103775808d7b2df5b24e0f52db9241e1de0e50609a71531a",
    "wallet/smoke_fixture.json": "2902461e563ba0b55221494f9f65a4296ed8c8711a15dddac488f8471c98de7a",
    "contracts/test/VerifierCanonical.t.sol": "d74393e8d722aee36f6dc43a2e3188accfc8615a91bca4c7d7b1319d48b02b08",
    "tooling/patch_verifier.py": "8359d3364ad219c98d1c81b40cfef90501363d746375a1cc091f6f9cfc938fa7",
    "activation_manifest.testbed.json": "4ee84a445a107d244029625c2c46946458fd842a2c3354a78bbe43d3f67bfd56",
    "LICENSE": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    "NOTICE": "c82d7a1cd702d4d091fc8459a4eb407d19cec08c14d97ba20c928ad154ebe04c",
}
# Byte-exact https://www.gnu.org/licenses/gpl-3.0.txt
GPL_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
CONFIG = '''[profile.default]
src = "src"
test = "test"
libs = []
solc_version = "0.8.30"
optimizer = true
optimizer_runs = 5000
via_ir = true
evm_version = "osaka"
'''


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed: {args!r}\n{result.stdout}")
    return result.stdout


def verify_source(source):
    if run("git", "rev-parse", "HEAD", cwd=source).strip() != PIN:
        raise ValueError("upstream checkout is not the reviewed commit")
    for name, expected in HASHES.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"independently pinned SHA256 mismatch: {name}")
    manifest = json.loads((source / "activation_manifest.testbed.json").read_text())
    for name, expected in HASHES.items():
        if name in manifest["artifacts"] and manifest["artifacts"][name] != expected:
            raise ValueError(f"upstream manifest disagrees with our pin: {name}")
    if manifest.get("production") is not False:
        raise ValueError("the pinned profile is not explicitly marked test-only")
    ceremony = manifest.get("ceremony", {})
    if ceremony.get("phase2_contributions") != 1 or ceremony.get("independent_verification") is not None:
        raise ValueError("the pinned disposable setup ceremony changed; review before packaging")
    profile = manifest.get("profile", {})
    expected_profile = {
        "wire_profile": "position-notes-v2",
        "pool_profile": "position-notes-v2",
        "verify_frame_gas": 225000,
        "recent_root_frame_gas": 8000,
        "signature_gas": 2800,
        "required_verify_budget": 235800,
        "post_pr_12279_max_observed_verify_execution_gas": 210166,
        "max_observed_recent_root_frame_gas": 5579,
    }
    for name, expected in expected_profile.items():
        if profile.get(name) != expected:
            raise ValueError(f"pinned profile {name} is {profile.get(name)!r}, expected {expected!r}")
    return manifest


def calldata(source, cast):
    transfer = json.loads((source / "wallet/smoke_fixture.json").read_text())["transfer"]
    proof = transfer["proof"]
    signals = [int(transfer[k], 0) if isinstance(transfer[k], str) and transfer[k].startswith("0x") else int(transfer[k])
               for k in ("nf1", "nf2", "out_cm1", "out_cm2", "root", "domain", "public_amount", "fee", "recipient", "authorizer")]
    beta = int(transfer["beta"], 0)
    alpha = int(run(cast, "keccak", "0x" + "".join(f"{word:064x}" for word in signals)).strip(), 16)
    field_modulus = 21888242871839275222246405745257275088548364400416034343698204186575808495617
    alpha %= field_modulus
    sigma = (alpha + beta) % field_modulus
    gamma = 0
    for signal in reversed(signals):
        gamma = (gamma * sigma + signal) % field_modulus
    public_inputs = [beta, gamma, alpha]
    proof_words = proof["pA"] + proof["pB"][0] + proof["pB"][1] + proof["pC"]
    values = [int(x, 0) for x in proof_words] + public_inputs
    variants = {"valid": values.copy(), "input": values.copy(), "alias": values.copy(), "infinity": values.copy()}
    # Input mutation reaches pairing and returns false. Noncanonical coordinates
    # and infinity remain controls for the verifier's early-rejection path.
    variants["input"][8] ^= 1
    variants["alias"][1] += 21888242871839275222246405745257275088696311157297823662689037894645226208583
    variants["infinity"][:2] = [0, 0]
    selector = run(cast, "sig", "verifyProof(uint256[2],uint256[2][2],uint256[2],uint256[3])").strip().removeprefix("0x")
    return {k: selector + "".join(f"{v:064x}" for v in words) for k, words in variants.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/sweep-soispoke"))
    parser.add_argument("--upstream", type=Path, help="optional existing checkout (still SHA/hash checked)")
    args = parser.parse_args()
    forge = os.environ.get("FORGE", "forge")
    cast = os.environ.get("CAST", "cast")
    version = run(forge, "--version")
    if version.splitlines()[0].strip() != f"forge Version: {FOUNDRY_VERSION}":
        raise ValueError(f"Foundry v{FOUNDRY_VERSION} is required for reproducible traces")
    if args.output.exists():
        raise ValueError("output already exists; choose a fresh output directory")
    with tempfile.TemporaryDirectory(prefix="soispoke-") as tmp:
        tmp = Path(tmp)
        source = args.upstream.resolve() if args.upstream else tmp / "upstream"
        if not args.upstream:
            run("git", "init", str(source))
            run("git", "fetch", "--depth=1", UPSTREAM, PIN, cwd=source)
            run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
        manifest = verify_source(source)
        project = tmp / "project"
        (project / "src").mkdir(parents=True)
        (project / "test").mkdir()
        shutil.copyfile(source / "contracts/src/Groth16Verifier.sol", project / "src/Groth16Verifier.sol")
        (project / "foundry.toml").write_text(CONFIG)
        calls = calldata(source, cast)
        test = '// SPDX-License-Identifier: MIT\npragma solidity ^0.8.30;\nimport {Groth16Verifier} from "../src/Groth16Verifier.sol";\ncontract FixtureTest {\nevent GasBracket(uint256 used);\nGroth16Verifier verifier;\nfunction setUp() public { verifier = new Groth16Verifier(); }\n'
        for name, data in calls.items():
            expected = "true" if name == "valid" else "false"
            test += f'function test_{name}() public {{ bytes memory data = hex"{data}"; uint256 beforeGas = gasleft(); (bool ok, bytes memory result) = address(verifier).staticcall(data); uint256 used = beforeGas - gasleft(); emit GasBracket(used); require(ok && result.length == 32 && abi.decode(result, (bool)) == {expected}, "unexpected verification result"); }}\n'
        test += "}\n"
        (project / "test/Fixture.t.sol").write_text(test)
        trace = run(forge, "test", "--root", str(project), "-vvvv", "--color", "never")
        measurements = {}
        for name in calls:
            block = trace.split(f"FixtureTest::test_{name}()", 1)[1].split("[PASS]", 1)[0]
            match = re.search(r"\[(\d+)\] Groth16Verifier::verifyProof", block)
            if not match:
                raise ValueError(f"missing verifier execution trace for {name}")
            pairings = len(re.findall(r"PRECOMPILES::ecpairing", block, re.IGNORECASE))
            expected_pairings = int(name in ("valid", "input"))
            if pairings != expected_pairings:
                raise ValueError(f"{name}: expected {expected_pairings} pairing calls, got {pairings}")
            if not expected_pairings and "PRECOMPILES::" in block:
                raise ValueError(f"{name}: early exit must not call any precompile")
            if expected_pairings and not re.search(r"\[181000\] PRECOMPILES::ecpairing", block, re.IGNORECASE):
                raise ValueError("four-pair BN254 pairing did not consume 181000 gas")
            bracket = re.search(r"GasBracket\(used: (\d+)", block)
            # Includes the cold verifier-address SLOAD, cold account access,
            # STATICCALL and Solidity returndata bookkeeping, unlike child gas.
            if not bracket or not int(match[1]) <= int(bracket[1]) < int(match[1]) + 6000:
                raise ValueError("gasleft cross-check disagrees with child execution trace")
            measurements[name] = {"gas": int(match[1]), "pairing_calls": pairings, "gasleft_bracket": int(bracket[1])}
        if measurements["valid"]["gas"] != measurements["input"]["gas"]:
            raise ValueError("valid and bit-flipped proof execution gas differ; investigate")
        runtime = run(forge, "inspect", "--root", str(project), "Groth16Verifier", "deployedBytecode").strip()
        artifact = json.loads((project / "out/Groth16Verifier.sol/Groth16Verifier.json").read_text())
        if runtime.removeprefix("0x") != artifact["deployedBytecode"]["object"].removeprefix("0x"):
            raise ValueError("runtime bytecode extraction cross-check failed")
        output = args.output
        output.mkdir(parents=True)
        (output / "verifier.hex").write_text(runtime + "\n")
        (output / "calldata-invalid.hex").write_text("0x" + calls["input"] + "\n")
        (output / "gas.txt").write_text(str(measurements["input"]["gas"]) + "\n")
        (output / "trace.txt").write_text(trace)
        profile = manifest["profile"]
        provenance = {
            "upstream": UPSTREAM,
            "commit": PIN,
            "input_sha256": HASHES,
            "foundry": version.strip(),
            "compiler": "0.8.30",
            "optimizer_runs": 5000,
            "via_ir": True,
            "evm_version": "osaka",
            "profile": "position-notes-v2",
            "test_only": True,
            "declared_budget_gas": profile["required_verify_budget"],
            "declared_verify_frame_gas": profile["verify_frame_gas"],
            "declared_recent_root_frame_gas": profile["recent_root_frame_gas"],
            "declared_signature_gas": profile["signature_gas"],
            "upstream_max_observed_verify_frame_gas": profile["post_pr_12279_max_observed_verify_execution_gas"],
            "upstream_max_observed_recent_root_gas": profile["max_observed_recent_root_frame_gas"],
            "measurement_scope": "isolated verifier call; excludes pool dispatcher, recent-root frame and transaction signature",
            "mutation": "public_inputs[0] ^= 1",
            "ceremony": manifest["ceremony"],
            "measurements": measurements,
        }
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        shutil.copyfile(source / "activation_manifest.testbed.json", output / "activation_manifest.testbed.json")
        gpl = Path(__file__).parent / "licenses/GPL-3.0.txt"
        if hashlib.sha256(gpl.read_bytes()).hexdigest() != GPL_SHA256:
            raise ValueError("bundled GPL-3.0 text is not the canonical gpl-3.0.txt")
        corresponding = output / "source"
        shutil.copytree(project / "src", corresponding / "src")
        shutil.copytree(project / "test", corresponding / "test")
        shutil.copyfile(project / "foundry.toml", corresponding / "foundry.toml")
        shutil.copyfile(gpl, corresponding / "COPYING")
        shutil.copyfile(source / "LICENSE", corresponding / "LICENSE.upstream-Apache-2.0")
        shutil.copyfile(source / "NOTICE", corresponding / "NOTICE")
        shutil.copyfile(source / "contracts/foundry.toml", corresponding / "upstream-foundry.toml")
        (corresponding / "tooling").mkdir()
        shutil.copyfile(source / "tooling/patch_verifier.py", corresponding / "tooling/patch_verifier.py")
        (corresponding / "scripts/licenses").mkdir(parents=True)
        shutil.copyfile(Path(__file__), corresponding / "scripts/soispoke.py")
        shutil.copyfile(Path(__file__).parent / "licenses/GPL-3.0.txt", corresponding / "scripts/licenses/GPL-3.0.txt")
        pipeline_root = Path(__file__).parent.parent
        pipeline_license = pipeline_root / "LICENSE"
        if not pipeline_license.exists():
            pipeline_license = pipeline_root / "LICENSE.pipeline-MIT"
        shutil.copyfile(pipeline_license, corresponding / "LICENSE.pipeline-MIT")
        (corresponding / "README.md").write_text(f"# Corresponding verifier source\n\nUpstream: {UPSTREAM} at `{PIN}`.\n\n`src/Groth16Verifier.sol` is redistributed without modification. It is labelled\nGPL-3.0 by its SPDX tag and header notice (Copyright 2021 0KIMS association);\nsee COPYING. Upstream notices are included in NOTICE. The repository-wide\nApache-2.0 license does not replace this file's GPL terms.\n\nRebuild the runtime with Foundry v{FOUNDRY_VERSION}: `forge inspect\nGroth16Verifier deployedBytecode`. Reproduce the valid and invalid pairing\nchecks with `forge test -vvvv`. Solc and compiler flags are pinned in\nfoundry.toml. The test contains only public proof and input data.\n\nThis is a benchmark-only profile. Its setup has one phase-2 contribution and\nno independent verification. Never use it to secure value. The artifact's\n`gas.txt` measures the isolated verifier call, not the full pool validation\nprefix. Source, notices, and bytecode must be distributed together.\n")
        print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
