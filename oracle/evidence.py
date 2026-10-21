"""PlotLock oracle: evidence evaluation and canonical evidence hashing.

The verdict rule is deliberately small, deterministic and readable. It is
the whole point of the product, so it lives in one place:

    NoBurn    - BOTH signals present and BOTH clean.
    Burned    - BOTH signals present and BOTH positive (a *confirmed* burn:
                a FIRMS/VIIRS active-fire detection inside the plot during
                the evidence window AND a Sentinel-2 burn scar).
    Uncertain - anything else: a signal is missing/unavailable (cloud,
                no acquisition, feed down) or the two signals disagree.
                Uncertain never pays out.

Thresholds (documented, from the USGS dNBR severity scale):
    - a scar is positive when mean dNBR >= 0.10 OR >= 25% of plot pixels
      have pixel-level dNBR >= 0.15.
    - a FIRMS detection counts when confidence is 'n' (nominal) or 'h'
      (high) and the detection is inside the plot polygon.

`confidence` in the result is an *evidence completeness/agreement* score
in [0, 1], not a probability that a fire did or did not happen.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Verdict enum order MUST match contracts/PlotLock.sol (NoBurn, Burned, Uncertain)
VERDICT_NOBURN = 0
VERDICT_BURNED = 1
VERDICT_UNCERTAIN = 2
VERDICT_NAMES = {0: "NoBurn", 1: "Burned", 2: "Uncertain"}
VERDICT_BY_NAME = {v: k for k, v in VERDICT_NAMES.items()}

DNBR_MEAN_THRESHOLD = 0.10
DNBR_PIXEL_THRESHOLD = 0.15
BURNED_PIXEL_FRACTION_THRESHOLD = 0.25
FIRMS_COUNTING_CONFIDENCE = {"n", "h"}


def canonical_bundle_bytes(bundle: dict[str, Any]) -> bytes:
    """Canonical byte form of an evidence bundle (stable across key order)."""
    return json.dumps(
        bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def evidence_hash(bundle: dict[str, Any]) -> str:
    """bytes32 evidence hash: keccak-256 of the canonical bundle bytes.

    Any change to any field of the bundle after signing changes this hash,
    which makes the oracle signature over the old hash fail on-chain.
    That is the tamper-evidence property the demo relies on.
    """
    from eth_utils import keccak

    return "0x" + keccak(canonical_bundle_bytes(bundle)).hex()


def sha256_hex(bundle: dict[str, Any]) -> str:
    """SHA-256 of the same canonical bytes (human-auditable cross-check)."""
    return hashlib.sha256(canonical_bundle_bytes(bundle)).hexdigest()


def _firms_signal(bundle: dict[str, Any]) -> dict[str, Any]:
    firms = bundle.get("firms") or {}
    if firms.get("status") != "ok":
        return {"present": False, "positive": False,
                "detail": "FIRMS evidence unavailable "
                          f"(status={firms.get('status', 'missing')})"}
    hits = [
        d for d in firms.get("detections", [])
        if d.get("inside_plot") and str(d.get("confidence", "")).lower()
        in FIRMS_COUNTING_CONFIDENCE
    ]
    return {
        "present": True,
        "positive": len(hits) > 0,
        "detections_total": len(firms.get("detections", [])),
        "detections_counting": len(hits),
        "detail": (f"{len(hits)} counting FIRMS detection(s) inside the plot"
                   if hits else "no counting FIRMS detections inside the plot"),
    }


def _sentinel2_signal(bundle: dict[str, Any]) -> dict[str, Any]:
    s2 = bundle.get("sentinel2") or {}
    if s2.get("status") != "ok":
        reason = s2.get("unavailable_reason", s2.get("status", "missing"))
        return {"present": False, "positive": False,
                "detail": f"Sentinel-2 scar check unavailable ({reason})"}
    dnbr = s2.get("dnbr_mean")
    frac = s2.get("burned_pixel_fraction")
    if dnbr is None or frac is None:
        return {"present": False, "positive": False,
                "detail": "Sentinel-2 scar check incomplete (missing dNBR)"}
    positive = dnbr >= DNBR_MEAN_THRESHOLD or frac >= BURNED_PIXEL_FRACTION_THRESHOLD
    return {
        "present": True,
        "positive": positive,
        "dnbr_mean": dnbr,
        "burned_pixel_fraction": frac,
        "detail": (f"dNBR mean {dnbr}, burned-pixel fraction {frac} -> "
                   + ("scar present" if positive else "no scar")),
    }


def evaluate(bundle: dict[str, Any]) -> dict[str, Any]:
    """Evaluate an evidence bundle to a verdict. Pure and deterministic."""
    firms = _firms_signal(bundle)
    scar = _sentinel2_signal(bundle)
    reasons: list[str] = [f"FIRMS: {firms['detail']}", f"Sentinel-2: {scar['detail']}"]

    if not firms["present"] or not scar["present"]:
        verdict = VERDICT_UNCERTAIN
        confidence = 0.30
        reasons.append("A required signal is missing -> Uncertain (never pays).")
    elif firms["positive"] and scar["positive"]:
        verdict = VERDICT_BURNED
        confidence = 0.95
        reasons.append("Both signals confirm a burn -> Burned.")
    elif not firms["positive"] and not scar["positive"]:
        verdict = VERDICT_NOBURN
        confidence = 0.90
        reasons.append("Both signals present and clean -> NoBurn.")
    else:
        verdict = VERDICT_UNCERTAIN
        confidence = 0.50
        reasons.append("Signals disagree -> Uncertain (never pays).")

    return {
        "verdict": VERDICT_NAMES[verdict],
        "verdict_uint": verdict,
        "confidence": confidence,
        "signals": {"firms": firms, "sentinel2": scar},
        "reasons": reasons,
        "evidence_hash": evidence_hash(bundle),
        "evidence_sha256": sha256_hex(bundle),
    }
