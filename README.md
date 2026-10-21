# PlotLock

One on-chain attestation per plot per season, bound to satellite evidence, so the same land can never be claimed twice.

**Track:** Climate Data & Environmental Monitoring (IEEE ClimateChain Global Hackathon)

## What it does

Land managers claim seasonal incentives (for example, residue-management
payments for NOT burning crop stubble) once per plot per season. Today nothing
stops the same land being claimed twice under a slightly redrawn outline, and
nothing binds a "this field did not burn" claim to checkable evidence.

PlotLock fixes both:

1. **H3 cell land registry.** A plot is registered for a season as a set of
   H3 cell IDs (small map cells, ~300 m across). If any cell overlaps a plot
   already registered for that season, registration **reverts**: redrawing
   the outline a few metres over does not help.
2. **One claim per (plot, season).** A second claim for the same plot and
   season **reverts**.
3. **Oracle-signed verdicts.** An off-chain oracle reviews satellite evidence
   (NASA FIRMS/VIIRS fire detections + Sentinel-2 burn-scar imagery) and signs
   a verdict: `NoBurn`, `Burned`, or `Uncertain`. The contract verifies the
   EIP-191/ECDSA signature, a fresh nonce, and a deadline before recording
   anything. Only `NoBurn` records a payout-eligible attestation; `Burned`
   and `Uncertain` are recorded as rejected verdicts. No clear evidence means
   nothing is paid: uncertainty is a verdict, not a failure.

An honest note: absence of a satellite fire detection does **not** prove a
field did not burn (fires can fall between overpasses or under cloud).
PlotLock supports evidence review; it does not certify carbon credits.

## Architecture

- `contracts/PlotLock.sol`: the registry and attestation contract
  (Solidity, OpenZeppelin `Ownable` / `ECDSA` / `MessageHashUtils`).
  Deployed on **Polygon Amoy testnet**.
- **Oracle (off-chain)**: FastAPI service (`oracle/`) that evaluates
  FIRMS/VIIRS + Sentinel-2 evidence (fixture set baked in so the demo never
  depends on a live API; Sentinel-2 item data and the clean/cloudy analyses
  are real Planetary Computer measurements, the burned plot's scar/FIRMS
  rows are labelled as mirrored - see `oracle/README.md`), applies the
  two-signal verdict rule (both signals must agree; missing or conflicting
  evidence is `Uncertain` and never pays), and signs verdicts with a
  server-side key. Keys never reach the browser.
- **Map UI (`web/`)**: one Leaflet page showing the four demo plots,
  verdicts, evidence panels and block-explorer links so anyone can replay
  the story on-chain with no wallet and no API key.

## How to replay on testnet

The contract is live on Polygon Amoy (see Deployment status below). Open
the contract on the explorer:
https://amoy.polygonscan.com/address/0x0a9B8e718D2cF31cc2ED454045C0151C81A2E2E9

End-to-end replay for plot 1 (clean Kaithal fixture, 108 H3 cells,
season 2026), executed 2026-10-21 from a throwaway testnet wallet
(`0xAA966583E057407EFe716602205F07d8BcCA9248`):

1. **Fund the wallet**: 0.05 POL claimed from the OpenFaucet browser
   faucet (tx `0xb6f0e99da0fde7b43dbfe5cbc0d1ff41e5bc13e6e09fd62cbe13fc1db0251999`,
   block 50734342, Success):
   https://amoy.polygonscan.com/tx/0xb6f0e99da0fde7b43dbfe5cbc0d1ff41e5bc13e6e09fd62cbe13fc1db0251999
2. **registerPlot**: plot 1 registered with the full 108-cell list
   (tx `0x63f95f8ce8d2525e777f675ca0a88ad10c2d3412313b5ed442c26e047b9068d1`,
   block 50734458, Success; cellsHash
   `0x32078d7e101bf24e75759d99c055e77601a5e13777490ae772a671ab2a7fe1e9`):
   https://amoy.polygonscan.com/tx/0x63f95f8ce8d2525e777f675ca0a88ad10c2d3412313b5ed442c26e047b9068d1
3. **Oracle sign**: the FastAPI oracle evaluated the clean fixture as
   `NoBurn`, signed the claim bundle
   (evidenceHash `0xdfd977ee33546023db59ed8a918e83a269ce5d39cf4d3021959b497eb0636e1f`,
   nonce 1792557109), and `/verify` confirmed the signature against the
   unmutated bundle.
4. **submitClaim**: relayed with the oracle-signed args; the on-chain
   `verdictDigest()` matched the oracle digest before broadcast
   (tx `0x9ff4ce38ec4c8205601a3071ee57e927227254bf9b57fd1bb42537ba631cc75a`,
   block 50734558, Success):
   https://amoy.polygonscan.com/tx/0x9ff4ce38ec4c8205601a3071ee57e927227254bf9b57fd1bb42537ba631cc75a
5. **Duplicate rejection**: a read-only `eth_call` re-registering the
   overlapping plot 4 fixture (65 cells overlap plot 1) reverts with
   `CellAlreadyTaken(2026, 631578613631690240)`; no gas spent.

On-chain read-back after step 4 (`hasAttestation(1, 2026)` is true):
plotId 1, season 2026, evidenceHash
`0xdfd977ee33546023db59ed8a918e83a269ce5d39cf4d3021959b497eb0636e1f`,
oracle `0x392595bb13Bb4E5696709bd2d6ED6d59AbC94b17`, timestamp 1792557120.
The remaining demo plots (burned, cloudy, duplicate) are fixture-side:
their evidence, verdicts and the duplicate rejection are presented in
the map UI (`web/`), which reads the same fixture bundles the oracle
evaluates.

## Map UI

`web/` is a dependency-light static page (plain HTML/CSS/JS + Leaflet from
a CDN, no build step): the four demo plots on one map over Kaithal,
Haryana, coloured by verdict, each opening an evidence panel with the
fixture's FIRMS/Sentinel-2 metrics, its provenance label (real vs partly
mirrored), and, for plot 1, the live on-chain record with explorer
links. Plot 4's panel shows the `CellAlreadyTaken` duplicate rejection,
and plot 1's panel carries a tamper-evidence demo: mutate the evidence
and the recomputed bundle hash stops matching, the browser-side
equivalent of the oracle's `/verify` check.

Run it from the repository root:

```bash
python3 -m http.server 8000
# open http://localhost:8000/web/
```

`web/data.js` is generated from `oracle/fixtures/*.json`: every metric
on the page is read from the fixture files; regenerate it instead of
hand-editing numbers.

## Deployment status: DEPLOYED to Polygon Amoy (2026-10-21)

PlotLock is live on the Polygon Amoy testnet (chainId 80002):

- **Contract:** `0x0a9B8e718D2cF31cc2ED454045C0151C81A2E2E9`
  https://amoy.polygonscan.com/address/0x0a9B8e718D2cF31cc2ED454045C0151C81A2E2E9
- **Deploy transaction:** `0x4cd6c0ad8425e4b0ac2e1cf5ebe77d9a0f82f24535cd3be546ef71c269984367`
  (block 50727423, status success)
  https://amoy.polygonscan.com/tx/0x4cd6c0ad8425e4b0ac2e1cf5ebe77d9a0f82f24535cd3be546ef71c269984367
- **Deployer:** `0xAA966583E057407EFe716602205F07d8BcCA9248`
- **Oracle (verified on-chain via `oracle()`):** `0x392595bb13Bb4E5696709bd2d6ED6d59AbC94b17`
- **RPC endpoint used:** `https://polygon-amoy-bor-rpc.publicnode.com`
  (the old `rpc-amoy.polygon.technology` hostname no longer resolves; the
  config default and `.env.example` now point at the publicnode endpoint)
- **Date:** 2026-10-21

The deployer was funded with 0.05 test POL from a browser faucet claim
(tx `0xdc6c0ca0ee94c631b3389652fbe22a1b22815b7316a245e5149193f1f2b9a751`)
and the deploy ran from a machine with working RPC egress, because the
build VM's egress proxy holds JSON-RPC POSTs. Wallets are throwaway
testnet wallets; keys live only in a local, gitignored `.env` and are
never committed. Contract source is VERIFIED: Sourcify reports an exact
match (creation and runtime bytecode, match id 56648646, verified
2026-10-21), and the PolygonScan address page shows "Source Code
Verified" with the full PlotLock source. (The direct PolygonScan verify
form is behind a Cloudflare check that rejects this build network, so
verification was routed through Sourcify, which forwarded it to the
Etherscan backend.)

## Development

```bash
npm install
npx hardhat test        # contract suite + Python-oracle signature round trip
oracle/.venv/bin/pip install -r oracle/requirements.txt
oracle/.venv/bin/python -m pytest oracle/tests -q   # oracle suite
npx hardhat run scripts/deploy.js --network amoy   # needs a funded .env
```

Copy `.env.example` to `.env` and fill in testnet-only keys. Never commit
`.env`.

## License

MIT, see [LICENSE](LICENSE).
