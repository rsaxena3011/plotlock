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
   already registered for that season, registration **reverts** — redrawing
   the outline a few metres over does not help.
2. **One claim per (plot, season).** A second claim for the same plot and
   season **reverts**.
3. **Oracle-signed verdicts.** An off-chain oracle reviews satellite evidence
   (NASA FIRMS/VIIRS fire detections + Sentinel-2 burn-scar imagery) and signs
   a verdict: `NoBurn`, `Burned`, or `Uncertain`. The contract verifies the
   EIP-191/ECDSA signature, a fresh nonce, and a deadline before recording
   anything. Only `NoBurn` records a payout-eligible attestation; `Burned`
   and `Uncertain` are recorded as rejected verdicts. No clear evidence means
   nothing is paid — uncertainty is a verdict, not a failure.

An honest note: absence of a satellite fire detection does **not** prove a
field did not burn (fires can fall between overpasses or under cloud).
PlotLock supports evidence review; it does not certify carbon credits.

## Architecture

- `contracts/PlotLock.sol` — the registry and attestation contract
  (Solidity, OpenZeppelin `Ownable` / `ECDSA` / `MessageHashUtils`).
  Deployed on **Polygon Amoy testnet**.
- **Oracle (off-chain, in progress)** — FastAPI service that evaluates
  FIRMS/VIIRS + Sentinel-2 evidence (fixture set baked in so the demo never
  depends on a live API), classifies burned / no-burn / uncertain with a
  confidence score, and signs verdicts with a server-side key. Keys never
  reach the browser.
- **Map UI (in progress)** — one Leaflet page showing the demo plots,
  verdicts, and block-explorer links so anyone can replay the story on-chain
  with no wallet and no API key.

## How to replay on testnet

_(Placeholder — contract address, explorer links, and the step-by-step
replay of the four demo plots land here after testnet deployment.)_

## Development

```bash
npm install
npx hardhat test        # full suite: every revert path is tested
npx hardhat run scripts/deploy.js --network amoy   # needs a funded .env
```

Copy `.env.example` to `.env` and fill in testnet-only keys. Never commit
`.env`.

## License

MIT — see [LICENSE](LICENSE).
