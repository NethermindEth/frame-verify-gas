# Groth16 benchmark artifact releases

These are disposable testbed artifacts, not a production trusted setup. Each synthetic
public-input count has its own R1CS, fresh gnark Groth16 setup, proof and Solidity verifier.
Proving keys and setup randomness are never serialized. Regeneration changes the keys;
reproducibility means independently re-running the checks and calibration, not identical bytes.

## Generate candidates

Use Go from `prover/go.mod`, Foundry **v1.7.1** for synthetic artifacts and **v1.8.3** for
soispoke v2, Python 3, and Git. The scripts pin Solidity compilers and settings.

```sh
make synthetic-sweeps
python3 scripts/soispoke.py --output artifacts/sweep-soispoke
python3 scripts/package-sweeps.py --component synthetic
python3 scripts/package-sweeps.py --component soispoke
```

Each output directory contains `verifier.hex` (runtime, not creation bytecode),
`calldata-invalid.hex`, and `gas.txt` (verifier child-call execution gas from the Foundry trace),
plus source and evidence. Valid controls must pass. Invalid synthetic calls use uncompressed
`verifyProof` and negate A's y coordinate while retaining a valid curve point; they must revert
with `ProofInvalid()` after one successful, false four-pair check costing 181,000 gas. That
invalid call is measured with call gas capped at `ceiling - 3000`: the verifier forwards
`gas()` to `ecPairing`, so under the EVM 63/64 rule N is the largest count whose pairing still
completes and returns false within the cap, not the largest whose total gas fits. The
soispoke proof flips compressed `public_inputs[0]` and must return false after pairing. Its coordinate-alias
and infinity controls must fail before any precompile call.

The active campaign points are 100,000, 235,800, 250,000, 300,000, 400,000 and 500,000.
The 100,000 point uses non-Groth16 workloads. The soispoke v2 artifact represents its
235,800 declared profile. Synthetic controls cover 250,000 through 500,000. Historical
236,285 and 352,800 results stay in prior campaign records, not this active matrix.
The Nethermind harness allows 2% drift against isolated verifier gas and checks the fully
paid pairing separately. Never relax that pairing check to accommodate malformed points.

## One version, five sweeps

`Build Groth16 candidates` is manually dispatched independently with `component=synthetic`
and `component=soispoke`. Both runs must use the **same source commit** that will be tagged.
They can run concurrently and upload separate candidate artifacts with a 30-day retention.
They do not tag or publish a release. The release workflow checks that both runs succeeded at
the source commit being published, validates the archive contents and profile provenance, and
records checksums for the five packages.

After both builds succeed, assemble and validate the release bundle with authenticated `gh`:

```sh
python3 scripts/prepare-release.py --version v1.0.0 --commit <full-sha> \
  --synthetic-run <run-id> --soispoke-run <run-id> --output /tmp/groth16-review
```

The new output directory contains five `sweep-*.tar.gz` assets, `SHA256SUMS`, and
`RELEASE-NOTES.md`. The normal PR review covers changes to the pinned sources, generator,
packaging checks, benchmark-only disclosure and license handling. The release workflow repeats
the provenance and archive checks against the candidate runs before publishing.

Dispatch `Publish Groth16 benchmark release` from `main` at the same commit with the version
and both run IDs. It rejects any existing tag or release (including
drafts) for that version, creates the tag and release with all five archives and the manifest
in one step, and verifies the tag points at the dispatched commit. Use a fresh version rather
than replacing published assets in place. Publication runs only in the upstream repository on `main`.

One-time maintainer setup before the first publication:

- Protect `main` so release workflow changes go through review.
- Add a tag ruleset for `v*` restricting creation, update and deletion to that workflow's
  maintainers.

The release is manually dispatched after the normal PR review and successful candidate builds.
No separate per-release comment sign-off or GitHub deployment-environment approval is required.

## Licensing

The upstream repository's Apache-2.0 license does **not** replace the verifier's GPL-3.0
header. The soispoke archive keeps the verifier under GPL-3.0 and bundles its unchanged source,
license text, attribution, build configuration and generation script. This implements source
availability alongside object code as described in [GPLv3 §6(d)](https://www.gnu.org/licenses/gpl.en.html#section6).
These distribution conditions apply independently of the repository's review and release process.

## Downstream acceptance gate

The Nethermind workflow fetches a published release by version, rejects draft/prerelease/invalid
versions, checks SHA256s and verifier plausibility, and extracts outside the checkout.

Acceptance requires an actual `harness=mempool` dispatch with that release version and
`raise_verify_gas_const=500000`, with soispoke v2 and the 250k/300k/400k/500k Groth16 rows present. Local generator
and harness runs are prerequisites, not substitutes for that dispatch.
