"""PlotLock oracle tests.

Run:  oracle/.venv/bin/python -m pytest oracle/tests -q   (from repo root)

Covered:
  * the verdict rule across the four fixtures + synthetic edge cases
    (missing signal, conflicting signals, low-confidence FIRMS rows)
  * canonical evidence hashing (key-order stable; any mutation rehashes)
  * the EIP-191 signature round trip against the contract's digest
    construction, including a known-answer digest captured from the
    oracle itself (the authoritative cross-check against the compiled
    contract is test/OracleSignature.test.js in the Hardhat suite)
  * the tamper property through the HTTP API: mutate one field of a
    signed bundle and verification fails
"""
from __future__ import annotations

import copy
import os

import pytest
from fastapi.testclient import TestClient

import evidence
import fixtures as fixture_mod
import signing
from app import app

client = TestClient(app)

# Known-answer vector, captured 2026-10-21 from oracle/sign_claim.py for
# fixture plot-1-clean with plot_id=1, season=2026, nonce=9001,
# deadline=1792554656, contract/chain = the deployed Amoy defaults.
KAT_EVIDENCE_HASH = "0xdfd977ee33546023db59ed8a918e83a269ce5d39cf4d3021959b497eb0636e1f"
KAT_DIGEST = "0xf8f3267a7fa192bdde643a0e4921797bbb64c6f600f80d82351cdd567b7f7198"


def bundle(name: str) -> dict:
    return fixture_mod.load_fixture(name)


# ---------------------------------------------------------------- verdicts

@pytest.mark.parametrize("name,expected", [
    ("plot-1-clean", "NoBurn"),
    ("plot-2-burned", "Burned"),
    ("plot-3-cloudy", "Uncertain"),
])
def test_fixture_verdicts(name, expected):
    result = evidence.evaluate(bundle(name))
    assert result["verdict"] == expected
    assert result["verdict_uint"] == evidence.VERDICT_BY_NAME[expected]


def test_missing_firms_signal_is_uncertain():
    b = bundle("plot-1-clean")
    b["firms"] = {"status": "unavailable", "detections": []}
    assert evidence.evaluate(b)["verdict"] == "Uncertain"


def test_missing_scar_signal_is_uncertain_even_with_firms_hit():
    b = bundle("plot-2-burned")
    b["sentinel2"] = {"status": "unavailable", "unavailable_reason": "cloud"}
    assert evidence.evaluate(b)["verdict"] == "Uncertain"


def test_conflicting_signals_are_uncertain():
    firms_only = bundle("plot-1-clean")
    firms_only["firms"] = copy.deepcopy(bundle("plot-2-burned")["firms"])
    assert evidence.evaluate(firms_only)["verdict"] == "Uncertain"

    scar_only = bundle("plot-1-clean")
    scar_only["sentinel2"] = copy.deepcopy(bundle("plot-2-burned")["sentinel2"])
    assert evidence.evaluate(scar_only)["verdict"] == "Uncertain"


def test_low_confidence_firms_rows_do_not_count():
    b = bundle("plot-1-clean")
    row = copy.deepcopy(bundle("plot-2-burned")["firms"]["detections"][0])
    row["confidence"] = "l"  # low confidence: must not count as a hit
    b["firms"] = {"status": "ok", "detections": [row]}
    assert evidence.evaluate(b)["verdict"] == "NoBurn"


def test_firms_detection_outside_plot_does_not_count():
    b = bundle("plot-1-clean")
    row = copy.deepcopy(bundle("plot-2-burned")["firms"]["detections"][0])
    row["inside_plot"] = False
    b["firms"] = {"status": "ok", "detections": [row]}
    assert evidence.evaluate(b)["verdict"] == "NoBurn"


def test_duplicate_fixture_overlaps_plot1_cells():
    p1 = set(bundle("plot-1-clean")["plot"]["h3_cells"])
    p4 = bundle("plot-4-duplicate")
    overlap = p1 & set(p4["plot"]["h3_cells"])
    assert len(overlap) == p4["overlapping_cell_count"] > 0
    assert p4["expected_registration"] == "revert: CellAlreadyTaken"


# ----------------------------------------------------------------- hashing

def test_evidence_hash_is_key_order_stable():
    b = bundle("plot-2-burned")
    shuffled = {k: b[k] for k in reversed(list(b.keys()))}
    assert evidence.evidence_hash(b) == evidence.evidence_hash(shuffled)


def test_any_mutation_changes_evidence_hash():
    b = bundle("plot-2-burned")
    before = evidence.evidence_hash(b)
    b["firms"]["detections"][0]["frp"] = 99.9
    assert evidence.evidence_hash(b) != before


# ----------------------------------------------------------------- signing

def _signing_available() -> bool:
    try:
        signing.signer_address()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _signing_available(),
                    reason="ORACLE_PRIVATE_KEY not configured in .env")
def test_digest_known_answer():
    b = bundle("plot-1-clean")
    assert evidence.evidence_hash(b) == KAT_EVIDENCE_HASH
    d = signing.digest(signing.DEFAULT_CONTRACT, signing.DEFAULT_CHAIN_ID,
                       1, 2026, 0, KAT_EVIDENCE_HASH, 9001, 1792554656)
    assert d == KAT_DIGEST


@pytest.mark.skipif(not _signing_available(),
                    reason="ORACLE_PRIVATE_KEY not configured in .env")
def test_signature_round_trip_recovers_oracle():
    signed = signing.sign_claim(7, 2026, 1, evidence.evidence_hash(bundle("plot-2-burned")),
                                nonce=424242, deadline=1792554656)
    recovered = signing.recover_signer(7, 2026, 1, signed["evidence_hash"],
                                       424242, 1792554656, signed["signature"])
    assert recovered.lower() == signed["oracle_address"].lower()
    if os.environ.get("ORACLE_ADDRESS"):
        assert recovered.lower() == os.environ["ORACLE_ADDRESS"].lower()


# --------------------------------------------------------------------- API

def test_api_health_and_fixtures():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    r = client.get("/fixtures")
    assert r.status_code == 200 and len(r.json()) == 4
    assert client.get("/fixtures/nope").status_code == 404


@pytest.mark.parametrize("name,expected", [
    ("plot-1-clean", "NoBurn"), ("plot-2-burned", "Burned"),
    ("plot-3-cloudy", "Uncertain"),
])
def test_api_evaluate(name, expected):
    r = client.post("/evaluate", json={"bundle": bundle(name)})
    assert r.status_code == 200
    assert r.json()["verdict"] == expected


@pytest.mark.skipif(not _signing_available(),
                    reason="ORACLE_PRIVATE_KEY not configured in .env")
def test_api_sign_verify_and_tamper():
    b = bundle("plot-2-burned")
    r = client.post("/sign", json={"bundle": b, "plot_id": 2, "season": 2026,
                                   "nonce": 777, "deadline": 1792554656})
    assert r.status_code == 200
    signed = r.json()
    args = signed["submit_claim_args"]
    assert args["verdict"] == 1  # Burned
    assert args["evidenceHash"] == signed["evidence_hash"]

    ok = client.post("/verify", json={"signed": signed, "bundle": b})
    assert ok.status_code == 200 and ok.json()["valid"] is True

    # Tamper: change one recorded report field after signing.
    tampered = copy.deepcopy(b)
    tampered["firms"]["detections"][1]["frp"] = 0.5
    bad = client.post("/verify", json={"signed": signed, "bundle": tampered})
    body = bad.json()
    assert body["valid"] is False
    assert body["evidence_hash_matches"] is False
    assert body["recomputed_evidence_hash"] != body["claimed_evidence_hash"]
