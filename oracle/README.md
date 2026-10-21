# PlotLock Oracle

The off-chain half of PlotLock: it evaluates satellite evidence for a plot,
turns it into a verdict (`NoBurn` / `Burned` / `Uncertain`), hashes the
evidence bundle, and signs the verdict for the on-chain contract
(`contracts/PlotLock.sol`, deployed on Polygon Amoy at
`0x0a9B8e718D2cF31cc2ED454045C0151C81A2E2E9`).

## Run it

```bash
python3 -m venv oracle/.venv
oracle/.venv/bin/pip install -r oracle/requirements.txt
cp .env.example .env        # fill in ORACLE_PRIVATE_KEY / ORACLE_ADDRESS
oracle/.venv/bin/uvicorn app:app --app-dir oracle --port 8000   # from repo root
```

The oracle key lives only in the gitignored `.env` (or the process
environment). It is never logged, returned by an endpoint, or committed.

## Endpoints

| Method | Path | Body / params | Returns |
|---|---|---|---|
| GET | `/health` | - | status, oracle address, contract, chain id, whether signing is available |
| GET | `/fixtures` | - | the four demo bundles: ids, labels, expected outcomes |
| GET | `/fixtures/{name}` | `plot-1-clean`, `plot-2-burned`, `plot-3-cloudy`, `plot-4-duplicate` | one full evidence bundle |
| POST | `/evaluate` | `{"bundle": {...}}` | verdict, per-signal breakdown, reasons, `evidence_hash` (no signature) |
| POST | `/sign` | `{"bundle", "plot_id", "season", "nonce", "deadline"?}` | the verdict plus `submit_claim_args`: exactly the arguments `PlotLock.submitClaim` verifies on-chain |
| POST | `/verify` | `{"signed": <a /sign response>, "bundle": {...}}` | whether the signature still matches this bundle (the tamper check) |

`oracle/sign_claim.py` is the same signing flow as a CLI (used by the
Hardhat round-trip test and handy for manual replay).

## The verdict rule (evidence.py - the whole rule, nothing hidden)

Two signals, both required:

- **FIRMS/VIIRS active fire (375 m):** a detection counts when it falls
  inside the plot polygon and its confidence is `n` (nominal) or `h` (high).
- **Sentinel-2 burn scar (dNBR):** positive when mean dNBR >= 0.10 or
  >= 25% of plot pixels have dNBR >= 0.15 (USGS dNBR severity scale).

```
both present + both clean     -> NoBurn     (only verdict that can pay out)
both present + both positive  -> Burned     (a *confirmed* burn)
a signal missing/unavailable  -> Uncertain  (cloud, no pass, feed down)
signals disagree              -> Uncertain
```

Uncertain is a verdict, not an error, and it never pays. `confidence` in
responses is an evidence completeness/agreement score, not a fire
probability.

## Signing convention

Identical to `PlotLock.verdictDigest()`:

```
structHash = keccak256(abi.encode(contract, chainId, plotId, season,
                                  uint8(verdict), evidenceHash, nonce, deadline))
signature  = EIP-191 personal-sign over the RAW structHash
             (the contract applies the prefix; signing the prefixed
             digest instead would double-prefix and never verify)
```

`evidenceHash` is `keccak256` of the canonical evidence bundle (JSON,
sorted keys, compact separators). Mutating any field of a signed bundle
changes the hash, so the signature fails on-chain - the tamper-evidence
property the demo shows via `/verify`.

## Fixtures and provenance (honest version)

The four demo bundles in `fixtures/` are baked in so the demo never
depends on a live API. `fixtures/build_fixtures.py` regenerates them and
documents the full analysis. Summary:

- **Sentinel-2 item IDs, dates and cloud cover are REAL**, listed from
  the Microsoft Planetary Computer STAC API (no key) for tile T43RFP
  over Kaithal, Haryana, Oct-Nov 2025.
- **Plot 1 (clean) is fully measured**: plot-mean NBR from the real
  B08/B12 data, 0.511 (2025-10-20) -> 0.520 (2025-11-14), dNBR -0.009.
- **Plot 3 (cloudy) is fully real**: the only acquisitions in its check
  window (2025-10-26..11-01) are 80.4% and 70.5% cloud, so no scar check
  is possible and the verdict is Uncertain.
- **Plot 2 (burned) is partly mirrored**: item metadata and the pre-fire
  NBR (0.597, measured) are real, but the post-fire scar metrics and the
  FIRMS rows are mirrored to a typical low-severity stubble burn in the
  exact real formats. Why: the real Oct-Nov 2025 analysis of the demo
  area found no field with a persistent scar, and a live FIRMS pull
  needs a NASA FIRMS MAP_KEY this project does not hold. The fixture
  itself carries this labelling - nothing mirrored is passed off as
  measured, and no market statistics are invented anywhere.
- **Plot 4 (duplicate)** is a registration scenario: plot 1's outline
  redrawn ~50 m east still shares 65 of its ~107 H3 res-12 cells
  (~307 m^2 each), so `registerPlot` reverts with `CellAlreadyTaken`.

## Tests

```bash
oracle/.venv/bin/python -m pytest oracle/tests -q   # 18 tests
npx hardhat test                                    # 13 contract + 2 round-trip
```

The Hardhat round-trip suite (`test/OracleSignature.test.js`) has this
Python oracle sign real fixture claims and submits them to a locally
deployed PlotLock: the contract accepts the NoBurn signature (digest
equality with `verdictDigest()` asserted directly) and rejects the same
signature when the evidence hash is tampered with.

## Limitations

- No-detection is not proof of no-burn: FIRMS can miss short fires
  between overpasses, and dNBR cannot fully separate burning from
  harvest/ploughing on its own - which is exactly why both signals must
  agree before anything is attested or rejected as Burned.
- The demo runs on baked fixtures (above). A production deployment
  would pull FIRMS with a MAP_KEY and run the dNBR pipeline live; the
  bundle schema and verdict rule would not change.
- ECDSA oracle signatures are not post-quantum safe; see the security
  note in the main README for the migration posture.
