"""PlotLock oracle: EIP-191 signing, exactly as contracts/PlotLock.sol checks it.

The contract computes (see `verdictDigest` in PlotLock.sol):

    structHash = keccak256(abi.encode(
        address(this), block.chainid, plotId, season,
        uint8(verdict), evidenceHash, nonce, deadline))
    digest = MessageHashUtils.toEthSignedMessageHash(structHash)   // EIP-191
    ECDSA.recover(digest, signature) == oracle

So the oracle signs the RAW struct hash with an EIP-191 personal-sign
(eth_account's `encode_defunct(primitive=struct_hash)`), which applies the
"\\x19Ethereum Signed Message:\\n32" prefix exactly once. Signing the
already-prefixed digest instead would prefix twice and never verify -
the day-1 Hardhat tests pin this convention.

The oracle private key is read from the environment variable
ORACLE_PRIVATE_KEY (loaded from the repo's gitignored .env when present).
It is never printed, logged, or returned by any function in this module.
"""
from __future__ import annotations

import os
from pathlib import Path

from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

DEFAULT_CONTRACT = "0x0a9B8e718D2cF31cc2ED454045C0151C81A2E2E9"  # Polygon Amoy
DEFAULT_CHAIN_ID = 80002  # Polygon Amoy

_env_loaded = False


def _load_env() -> None:
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        from dotenv import load_dotenv

        repo_root = Path(__file__).resolve().parent.parent
        load_dotenv(repo_root / ".env")
    except Exception:
        pass  # env vars may already be set; .env is a convenience only


def oracle_address() -> str | None:
    _load_env()
    return os.environ.get("ORACLE_ADDRESS") or None


def _oracle_key() -> str:
    _load_env()
    key = os.environ.get("ORACLE_PRIVATE_KEY")
    if not key:
        raise RuntimeError(
            "ORACLE_PRIVATE_KEY is not set (expected in the repo .env, gitignored)"
        )
    return key


def signer_address() -> str:
    """The oracle's public address, derived from the configured key."""
    return Account.from_key(_oracle_key()).address


def contract_address() -> str:
    _load_env()
    return os.environ.get("PLOTLOCK_CONTRACT", DEFAULT_CONTRACT)


def chain_id() -> int:
    _load_env()
    return int(os.environ.get("CHAIN_ID", str(DEFAULT_CHAIN_ID)))


def struct_hash(
    contract: str,
    chain: int,
    plot_id: int,
    season: int,
    verdict_uint: int,
    evidence_hash_hex: str,
    nonce: int,
    deadline: int,
) -> bytes:
    """The raw struct hash the oracle signs (contract applies the prefix)."""
    encoded = abi_encode(
        ["address", "uint256", "uint256", "uint32", "uint8", "bytes32",
         "uint256", "uint256"],
        [contract, chain, plot_id, season, verdict_uint,
         bytes.fromhex(evidence_hash_hex.removeprefix("0x")), nonce, deadline],
    )
    return keccak(encoded)


def digest(
    contract: str,
    chain: int,
    plot_id: int,
    season: int,
    verdict_uint: int,
    evidence_hash_hex: str,
    nonce: int,
    deadline: int,
) -> str:
    """The full EIP-191 digest - identical to the contract's verdictDigest()."""
    sh = struct_hash(contract, chain, plot_id, season, verdict_uint,
                     evidence_hash_hex, nonce, deadline)
    return "0x" + keccak(b"\x19Ethereum Signed Message:\n32" + sh).hex()


def sign_claim(
    plot_id: int,
    season: int,
    verdict_uint: int,
    evidence_hash_hex: str,
    nonce: int,
    deadline: int,
    contract: str | None = None,
    chain: int | None = None,
) -> dict:
    """Sign a claim with the oracle key. Returns everything submitClaim needs."""
    contract = contract or contract_address()
    chain = chain if chain is not None else chain_id()
    sh = struct_hash(contract, chain, plot_id, season, verdict_uint,
                     evidence_hash_hex, nonce, deadline)
    signed = Account.sign_message(encode_defunct(primitive=sh), _oracle_key())
    return {
        "contract": contract,
        "chain_id": chain,
        "plot_id": plot_id,
        "season": season,
        "verdict_uint": verdict_uint,
        "evidence_hash": evidence_hash_hex,
        "nonce": nonce,
        "deadline": deadline,
        "digest": "0x" + keccak(b"\x19Ethereum Signed Message:\n32" + sh).hex(),
        "signature": "0x" + signed.signature.hex(),
        "oracle_address": Account.from_key(_oracle_key()).address,
    }


def recover_signer(
    plot_id: int,
    season: int,
    verdict_uint: int,
    evidence_hash_hex: str,
    nonce: int,
    deadline: int,
    signature_hex: str,
    contract: str | None = None,
    chain: int | None = None,
) -> str:
    """Recover the signer of a claim signature (what the contract checks)."""
    contract = contract or contract_address()
    chain = chain if chain is not None else chain_id()
    sh = struct_hash(contract, chain, plot_id, season, verdict_uint,
                     evidence_hash_hex, nonce, deadline)
    return Account.recover_message(
        encode_defunct(primitive=sh),
        signature=bytes.fromhex(signature_hex.removeprefix("0x")),
    )
