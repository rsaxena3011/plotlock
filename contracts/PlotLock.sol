// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/// @title PlotLock
/// @notice One on-chain attestation per plot per season, bound to satellite
///         evidence, so the same land can never be claimed twice.
///
///         - Land is registered per season as a set of H3 cell IDs. If any
///           cell overlaps a plot already registered for that season,
///           registration reverts.
///         - One claim per (plot, season): a second claim reverts.
///         - Claims carry an off-chain oracle's verdict, authorised by an
///           EIP-191/ECDSA signature over (plotId, season, verdict,
///           evidenceHash, nonce, deadline) plus this contract and chain id.
///           Replayed nonces, expired deadlines and wrong signers revert.
///         - Only a NoBurn verdict records a payout-eligible attestation.
///           Burned and Uncertain verdicts are recorded as rejections.
contract PlotLock is Ownable {
    enum Verdict {
        NoBurn,
        Burned,
        Uncertain
    }

    struct Plot {
        address owner;
        uint32 season;
        bytes32 cellsHash;
        uint256 cellCount;
        bool exists;
    }

    struct Attestation {
        uint256 plotId;
        uint32 season;
        bytes32 evidenceHash;
        uint256 timestamp;
        address oracle;
    }

    struct Rejection {
        uint256 plotId;
        uint32 season;
        Verdict verdict;
        bytes32 evidenceHash;
        uint256 timestamp;
    }

    /// @notice The off-chain oracle whose signature authorises verdicts.
    address public oracle;

    /// @notice Next plot id to hand out (ids start at 1).
    uint256 public nextPlotId = 1;

    mapping(uint256 => Plot) public plots;
    /// (season, cell) -> taken by a registered plot
    mapping(bytes32 => bool) private _cellTaken;
    /// (plotId, season) -> a claim (any verdict) has been recorded
    mapping(bytes32 => bool) public claimRecorded;
    /// (plotId, season) -> payout-eligible attestation (NoBurn only)
    mapping(bytes32 => Attestation) public attestations;
    /// (plotId, season) -> recorded rejected verdict (Burned / Uncertain)
    mapping(bytes32 => Rejection) public rejectedVerdicts;
    /// oracle nonce -> spent
    mapping(uint256 => bool) public usedNonces;

    event PlotRegistered(
        uint256 indexed plotId,
        address indexed owner,
        uint32 indexed season,
        bytes32 cellsHash,
        uint256 cellCount
    );
    event Attested(
        uint256 indexed plotId,
        uint32 indexed season,
        bytes32 evidenceHash,
        address oracle,
        uint256 timestamp
    );
    event VerdictRejected(
        uint256 indexed plotId,
        uint32 indexed season,
        Verdict verdict,
        bytes32 evidenceHash,
        uint256 timestamp
    );
    event OracleUpdated(address indexed oldOracle, address indexed newOracle);

    error EmptyCellSet();
    error CellAlreadyTaken(uint32 season, uint64 cell);
    error PlotNotFound(uint256 plotId);
    error SeasonMismatch(uint256 plotId, uint32 season);
    error ClaimAlreadyRecorded(uint256 plotId, uint32 season);
    error NonceAlreadyUsed(uint256 nonce);
    error SignatureExpired(uint256 deadline);
    error InvalidOracleSignature();
    error ZeroAddress();

    constructor(address oracle_) Ownable(msg.sender) {
        if (oracle_ == address(0)) revert ZeroAddress();
        oracle = oracle_;
    }

    /// @notice Rotate the oracle key (owner only).
    function setOracle(address newOracle) external onlyOwner {
        if (newOracle == address(0)) revert ZeroAddress();
        emit OracleUpdated(oracle, newOracle);
        oracle = newOracle;
    }

    /// @notice Key for the per-season cell registry.
    function cellKey(uint32 season, uint64 cell) public pure returns (bytes32) {
        return keccak256(abi.encode(season, cell));
    }

    /// @notice Key for the per-(plot, season) claim records.
    function claimKey(uint256 plotId, uint32 season) public pure returns (bytes32) {
        return keccak256(abi.encode(plotId, season));
    }

    /// @notice True if `cell` is already registered to some plot in `season`.
    function isCellTaken(uint32 season, uint64 cell) external view returns (bool) {
        return _cellTaken[cellKey(season, cell)];
    }

    /// @notice Register a plot for a season as a set of H3 cell IDs.
    /// @dev Reverts if the set is empty or ANY cell is already taken in this
    ///      season (by any plot, including a redrawn outline of the same land).
    /// @return plotId The newly assigned plot id.
    function registerPlot(uint32 season, uint64[] calldata cells) external returns (uint256 plotId) {
        if (cells.length == 0) revert EmptyCellSet();
        for (uint256 i = 0; i < cells.length; i++) {
            bytes32 key = cellKey(season, cells[i]);
            if (_cellTaken[key]) revert CellAlreadyTaken(season, cells[i]);
            _cellTaken[key] = true;
        }
        plotId = nextPlotId++;
        bytes32 cellsHash = keccak256(abi.encode(cells));
        plots[plotId] = Plot({
            owner: msg.sender,
            season: season,
            cellsHash: cellsHash,
            cellCount: cells.length,
            exists: true
        });
        emit PlotRegistered(plotId, msg.sender, season, cellsHash, cells.length);
    }

    /// @notice The EIP-191 digest the oracle signs for a claim. Binding the
    ///         contract address and chain id stops cross-contract and
    ///         cross-chain replay of the same signature.
    function verdictDigest(
        uint256 plotId,
        uint32 season,
        Verdict verdict,
        bytes32 evidenceHash,
        uint256 nonce,
        uint256 deadline
    ) public view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                address(this),
                block.chainid,
                plotId,
                season,
                uint8(verdict),
                evidenceHash,
                nonce,
                deadline
            )
        );
        return MessageHashUtils.toEthSignedMessageHash(structHash);
    }

    /// @notice Submit an oracle-signed verdict for a (plot, season).
    /// @dev Reverts on: unknown plot, season mismatch, an already-recorded
    ///      claim for the (plot, season), a replayed nonce, an expired
    ///      deadline, or a signature that does not recover to the oracle.
    ///      Anyone may relay a claim; the oracle signature is the authority.
    function submitClaim(
        uint256 plotId,
        uint32 season,
        Verdict verdict,
        bytes32 evidenceHash,
        uint256 nonce,
        uint256 deadline,
        bytes calldata signature
    ) external {
        Plot storage plot = plots[plotId];
        if (!plot.exists) revert PlotNotFound(plotId);
        if (plot.season != season) revert SeasonMismatch(plotId, season);

        bytes32 key = claimKey(plotId, season);
        if (claimRecorded[key]) revert ClaimAlreadyRecorded(plotId, season);
        if (usedNonces[nonce]) revert NonceAlreadyUsed(nonce);
        if (block.timestamp > deadline) revert SignatureExpired(deadline);

        bytes32 digest = verdictDigest(plotId, season, verdict, evidenceHash, nonce, deadline);
        if (ECDSA.recover(digest, signature) != oracle) revert InvalidOracleSignature();

        usedNonces[nonce] = true;
        claimRecorded[key] = true;

        if (verdict == Verdict.NoBurn) {
            attestations[key] = Attestation({
                plotId: plotId,
                season: season,
                evidenceHash: evidenceHash,
                timestamp: block.timestamp,
                oracle: oracle
            });
            emit Attested(plotId, season, evidenceHash, oracle, block.timestamp);
        } else {
            rejectedVerdicts[key] = Rejection({
                plotId: plotId,
                season: season,
                verdict: verdict,
                evidenceHash: evidenceHash,
                timestamp: block.timestamp
            });
            emit VerdictRejected(plotId, season, verdict, evidenceHash, block.timestamp);
        }
    }

    /// @notice True if a payout-eligible (NoBurn) attestation exists.
    function hasAttestation(uint256 plotId, uint32 season) external view returns (bool) {
        return attestations[claimKey(plotId, season)].timestamp != 0;
    }
}
