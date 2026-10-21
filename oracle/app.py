"""PlotLock oracle service (FastAPI).

Endpoints
---------
GET  /health            service + oracle identity (never any key material)
GET  /fixtures          the four baked-in demo bundles (ids + expectations)
GET  /fixtures/{name}   one full evidence bundle
POST /evaluate          {bundle} -> verdict + evidence hash (no signature)
POST /sign              {bundle, plot_id, season, nonce, deadline?}
                        -> verdict + evidenceHash + EIP-191 signature,
                           i.e. exactly the arguments PlotLock.submitClaim
                           verifies on-chain
POST /verify            {signed: <the /sign response>, bundle}
                        -> recomputes the evidence hash from the bundle,
                           recovers the signer, and reports whether the
                           signature still matches. Mutating ANY field of
                           the bundle after signing makes this fail: that
                           is the tamper-evidence demo.

Run:  uvicorn app:app --app-dir oracle --port 8000   (from the repo root)
The oracle key comes from ORACLE_PRIVATE_KEY in the repo .env (gitignored).
"""
from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import evidence
import fixtures as fixture_mod
import signing

app = FastAPI(title="PlotLock Oracle", version="0.2.0")


class EvaluateRequest(BaseModel):
    bundle: dict


class SignRequest(BaseModel):
    bundle: dict
    plot_id: int
    season: int
    nonce: int
    deadline: int | None = None  # unix seconds; defaults to now + 1 hour


class VerifyRequest(BaseModel):
    signed: dict = Field(..., description="A previous /sign response object")
    bundle: dict = Field(..., description="The evidence bundle to check (possibly mutated)")


@app.get("/health")
def health() -> dict:
    try:
        addr = signing.signer_address()
        signing_available = True
    except Exception:
        addr = signing.oracle_address()
        signing_available = False
    return {
        "status": "ok",
        "oracle_address": addr,
        "signing_available": signing_available,
        "contract": signing.contract_address(),
        "chain_id": signing.chain_id(),
    }


@app.get("/fixtures")
def list_fixtures() -> list[dict]:
    return fixture_mod.list_fixtures()


@app.get("/fixtures/{name}")
def get_fixture(name: str) -> dict:
    try:
        return fixture_mod.load_fixture(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"unknown fixture: {name}")


@app.post("/evaluate")
def evaluate(req: EvaluateRequest) -> dict:
    return evidence.evaluate(req.bundle)


@app.post("/sign")
def sign(req: SignRequest) -> dict:
    result = evidence.evaluate(req.bundle)
    deadline = req.deadline if req.deadline is not None else int(time.time()) + 3600
    try:
        signed = signing.sign_claim(
            plot_id=req.plot_id,
            season=req.season,
            verdict_uint=result["verdict_uint"],
            evidence_hash_hex=result["evidence_hash"],
            nonce=req.nonce,
            deadline=deadline,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        **result,
        "submit_claim_args": {
            "plotId": req.plot_id,
            "season": req.season,
            "verdict": result["verdict_uint"],
            "evidenceHash": result["evidence_hash"],
            "nonce": req.nonce,
            "deadline": deadline,
            "signature": signed["signature"],
        },
        "digest": signed["digest"],
        "oracle_address": signed["oracle_address"],
        "contract": signed["contract"],
        "chain_id": signed["chain_id"],
    }


@app.post("/verify")
def verify(req: VerifyRequest) -> dict:
    args = req.signed.get("submit_claim_args") or {}
    try:
        plot_id = int(args["plotId"])
        season = int(args["season"])
        verdict_uint = int(args["verdict"])
        claimed_hash = str(args["evidenceHash"])
        nonce = int(args["nonce"])
        deadline = int(args["deadline"])
        signature = str(args["signature"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="signed payload is missing submit_claim_args fields")

    recomputed_hash = evidence.evidence_hash(req.bundle)
    hash_matches = recomputed_hash.lower() == claimed_hash.lower()
    try:
        recovered = signing.recover_signer(
            plot_id, season, verdict_uint, claimed_hash, nonce, deadline, signature,
            contract=req.signed.get("contract"), chain=req.signed.get("chain_id"),
        )
    except Exception as exc:  # malformed signature bytes etc.
        return {"valid": False, "evidence_hash_matches": hash_matches,
                "error": f"signature recovery failed: {exc}"}
    oracle = req.signed.get("oracle_address") or signing.oracle_address()
    signer_matches = oracle is not None and recovered.lower() == oracle.lower()
    return {
        "valid": bool(hash_matches and signer_matches),
        "evidence_hash_matches": hash_matches,
        "signer_matches_oracle": signer_matches,
        "recovered_signer": recovered,
        "oracle_address": oracle,
        "recomputed_evidence_hash": recomputed_hash,
        "claimed_evidence_hash": claimed_hash,
    }
