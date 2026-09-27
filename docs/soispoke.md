# Pinned soispoke v2 verifier fixture

## Pin and profile

- Upstream: `soispoke/minimal-shielded-pool` at `6dedda193bf09c9d80cd89b3dc23eccf580d1026`.
- Profile: `position-notes-v2`.
- Declared budget: **235,800 gas**, split into 225,000 VERIFY, 8,000 recent-root, and 2,800 signature.
- Test-only setup: one phase-2 contribution, no independent verification. Never use to secure value.
- All manifest artifacts and the public smoke fixture are independently SHA256-pinned by `scripts/soispoke.py`.

## Gas scopes

| Measurement | Gas | Scope |
| --- | ---: | --- |
| Isolated verifier, valid proof | 202,307 | Direct `verifyProof` call; one 181,000-gas pairing |
| Isolated verifier, mutated public input | 202,307 | Full pairing, returns `false`; this is `gas.txt` |
| VERIFY frame maximum in upstream manifest and local native replay | 210,166 | Pool VERIFY frame, including frame-level work |
| Full validation prefix in local native replay | 218,545 | VERIFY frame + recent-root frame + signature |
| Coordinate alias / infinity controls | 441 / 763 | Early rejection; no pairing |

The isolated verifier artifact does not include the pool dispatcher, recent-root frame, or transaction signature.
Do not substitute its `gas.txt` value for the full-prefix measurement.

The generated proof uses three compressed public inputs derived from the ten statement words and `beta`,
matching the upstream canonical test. The invalid artifact toggles one compressed input. Both the valid and
invalid calls complete the pairing. Alias and infinity cases confirm the cheaper early-exit paths are distinct.

## Reproduce

```sh
FORGE=/path/to/forge CAST=/path/to/cast \
  python3 scripts/soispoke.py --output artifacts/sweep-soispoke
python3 scripts/package-sweeps.py --component soispoke
```

The pinned compiler profile is solc 0.8.30, optimizer 5,000 runs, via-IR, Osaka EVM. Soispoke artifacts
use Foundry v1.8.3. The archive includes runtime bytecode, exact calldata, traces, provenance, the testbed
manifest, corresponding verifier source, license, and attribution. It excludes proving/setup material and
private-key fields from the upstream wallet fixture.

The verifier source is marked GPL-3.0. The upstream repository's Apache-2.0 license does not replace that
license. A named human maintainer with crypto and licensing context must review the exact release assets.
Automated tests and agent review do not provide that approval.

The v1.0.0 benchmark release has a recorded sign-off for its exact manifest and assets. That sign-off does
not carry forward to this v2 profile. The v2 release remains pending the same named human review and exact
asset sign-off.
