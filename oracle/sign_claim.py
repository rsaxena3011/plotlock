#!/usr/bin/env python3
"""Sign one fixture bundle as an on-chain claim and print the result as JSON.

Used by the Hardhat round-trip test (test/OracleSignature.test.js) and by
anyone replaying the demo by hand. The oracle key is read from the repo
.env (gitignored) via oracle/signing.py and is never printed.

Usage:
  python3 sign_claim.py --fixture plot-1-clean --plot-id 1 --season 2026 \
      --nonce 1 [--deadline <unix>] [--contract 0x...] [--chain-id 80002]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence
import fixtures as fixture_mod
import signing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--plot-id", type=int, required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--nonce", type=int, required=True)
    ap.add_argument("--deadline", type=int, default=None)
    ap.add_argument("--contract", default=None)
    ap.add_argument("--chain-id", type=int, default=None)
    args = ap.parse_args()

    bundle = fixture_mod.load_fixture(args.fixture)
    result = evidence.evaluate(bundle)
    deadline = args.deadline if args.deadline is not None else int(time.time()) + 3600
    signed = signing.sign_claim(
        plot_id=args.plot_id,
        season=args.season,
        verdict_uint=result["verdict_uint"],
        evidence_hash_hex=result["evidence_hash"],
        nonce=args.nonce,
        deadline=deadline,
        contract=args.contract,
        chain=args.chain_id,
    )
    print(json.dumps({
        "bundle_id": bundle["bundle_id"],
        "verdict": result["verdict"],
        "verdict_uint": result["verdict_uint"],
        "evidence_hash": result["evidence_hash"],
        "plot_id": args.plot_id,
        "season": args.season,
        "nonce": args.nonce,
        "deadline": deadline,
        "signature": signed["signature"],
        "digest": signed["digest"],
        "oracle_address": signed["oracle_address"],
        "contract": signed["contract"],
        "chain_id": signed["chain_id"],
    }))


if __name__ == "__main__":
    main()
