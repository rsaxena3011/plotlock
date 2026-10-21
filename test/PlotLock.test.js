const { expect } = require("chai");
const { ethers } = require("hardhat");

const SEASON = 2026; // Kharif 2026 as an opaque season id
const OTHER_SEASON = 2027;
const Verdict = { NoBurn: 0, Burned: 1, Uncertain: 2 };

describe("PlotLock", function () {
  let lock, owner, oracle, farmer, stranger;
  let evidenceHash;

  beforeEach(async function () {
    [owner, oracle, farmer, stranger] = await ethers.getSigners();
    const PlotLock = await ethers.getContractFactory("PlotLock");
    lock = await PlotLock.deploy(oracle.address);
    await lock.waitForDeployment();
    evidenceHash = ethers.keccak256(ethers.toUtf8Bytes("firms+sentinel2 evidence bundle #1"));
  });

  async function signClaim(signer, plotId, season, verdict, evHash, nonce, deadline) {
    // Mirror the oracle: build the raw struct hash, then EIP-191 sign it.
    // (lock.verdictDigest returns the already-prefixed hash; signing THAT
    // with signMessage would prefix twice and never verify.)
    const { chainId } = await ethers.provider.getNetwork();
    const structHash = ethers.keccak256(
      ethers.AbiCoder.defaultAbiCoder().encode(
        ["address", "uint256", "uint256", "uint32", "uint8", "bytes32", "uint256", "uint256"],
        [await lock.getAddress(), chainId, plotId, season, verdict, evHash, nonce, deadline]
      )
    );
    return signer.signMessage(ethers.getBytes(structHash));
  }

  async function futureDeadline(seconds = 3600) {
    const block = await ethers.provider.getBlock("latest");
    return block.timestamp + seconds;
  }

  async function registerAs(farmerSigner, season, cells) {
    const tx = await lock.connect(farmerSigner).registerPlot(season, cells);
    const receipt = await tx.wait();
    // plotId is the first topic-free return; read it from nextPlotId delta via event
    const ev = receipt.logs
      .map((l) => {
        try { return lock.interface.parseLog(l); } catch { return null; }
      })
      .find((e) => e && e.name === "PlotRegistered");
    return ev.args.plotId;
  }

  it("registers a plot and records a NoBurn attestation", async function () {
    const plotId = await registerAs(farmer, SEASON, [1001, 1002, 1003]);
    expect(await lock.isCellTaken(SEASON, 1002)).to.equal(true);

    const deadline = await futureDeadline();
    const sig = await signClaim(oracle, plotId, SEASON, Verdict.NoBurn, evidenceHash, 1, deadline);
    await expect(lock.submitClaim(plotId, SEASON, Verdict.NoBurn, evidenceHash, 1, deadline, sig))
      .to.emit(lock, "Attested");

    expect(await lock.hasAttestation(plotId, SEASON)).to.equal(true);
    const key = await lock.claimKey(plotId, SEASON);
    const att = await lock.attestations(key);
    expect(att.evidenceHash).to.equal(evidenceHash);
    expect(att.oracle).to.equal(oracle.address);
  });

  it("emits PlotRegistered and Attested events", async function () {
    await expect(lock.connect(farmer).registerPlot(SEASON, [2001]))
      .to.emit(lock, "PlotRegistered");
    const deadline = await futureDeadline();
    const sig = await signClaim(oracle, 1, SEASON, Verdict.NoBurn, evidenceHash, 7, deadline);
    await expect(lock.submitClaim(1, SEASON, Verdict.NoBurn, evidenceHash, 7, deadline, sig))
      .to.emit(lock, "Attested");
  });

  it("reverts on a second claim for the same (plot, season)", async function () {
    const plotId = await registerAs(farmer, SEASON, [3001, 3002]);
    const deadline = await futureDeadline();
    const sig1 = await signClaim(oracle, plotId, SEASON, Verdict.NoBurn, evidenceHash, 11, deadline);
    await lock.submitClaim(plotId, SEASON, Verdict.NoBurn, evidenceHash, 11, deadline, sig1);

    const sig2 = await signClaim(oracle, plotId, SEASON, Verdict.NoBurn, evidenceHash, 12, deadline);
    await expect(
      lock.submitClaim(plotId, SEASON, Verdict.NoBurn, evidenceHash, 12, deadline, sig2)
    ).to.be.revertedWithCustomError(lock, "ClaimAlreadyRecorded");
  });

  it("reverts registration when cells overlap an existing plot in the same season", async function () {
    await registerAs(farmer, SEASON, [4001, 4002, 4003]);
    // A redrawn outline shifted a few metres still shares cell 4003.
    await expect(lock.connect(stranger).registerPlot(SEASON, [4003, 4004]))
      .to.be.revertedWithCustomError(lock, "CellAlreadyTaken");
  });

  it("allows non-overlapping registration in the same season", async function () {
    await registerAs(farmer, SEASON, [5001, 5002]);
    const plotId2 = await registerAs(stranger, SEASON, [5003, 5004]);
    expect(plotId2).to.equal(2n);
    expect(await lock.isCellTaken(SEASON, 5004)).to.equal(true);
  });

  it("allows the same cells in a different season", async function () {
    await registerAs(farmer, SEASON, [6001]);
    const plotId = await registerAs(farmer, OTHER_SEASON, [6001]);
    expect(plotId).to.equal(2n);
  });

  it("records a Burned verdict with no attestation", async function () {
    const plotId = await registerAs(farmer, SEASON, [7001]);
    const deadline = await futureDeadline();
    const sig = await signClaim(oracle, plotId, SEASON, Verdict.Burned, evidenceHash, 21, deadline);
    await expect(lock.submitClaim(plotId, SEASON, Verdict.Burned, evidenceHash, 21, deadline, sig))
      .to.emit(lock, "VerdictRejected");

    expect(await lock.hasAttestation(plotId, SEASON)).to.equal(false);
    const key = await lock.claimKey(plotId, SEASON);
    const rej = await lock.rejectedVerdicts(key);
    expect(rej.verdict).to.equal(Verdict.Burned);
    expect(rej.evidenceHash).to.equal(evidenceHash);
  });

  it("records an Uncertain verdict with no attestation", async function () {
    const plotId = await registerAs(farmer, SEASON, [8001]);
    const deadline = await futureDeadline();
    const sig = await signClaim(oracle, plotId, SEASON, Verdict.Uncertain, evidenceHash, 22, deadline);
    await lock.submitClaim(plotId, SEASON, Verdict.Uncertain, evidenceHash, 22, deadline, sig);

    expect(await lock.hasAttestation(plotId, SEASON)).to.equal(false);
    const key = await lock.claimKey(plotId, SEASON);
    const rej = await lock.rejectedVerdicts(key);
    expect(rej.verdict).to.equal(Verdict.Uncertain);
  });

  it("reverts when the signature is from the wrong signer", async function () {
    const plotId = await registerAs(farmer, SEASON, [9001]);
    const deadline = await futureDeadline();
    const badSig = await signClaim(stranger, plotId, SEASON, Verdict.NoBurn, evidenceHash, 31, deadline);
    await expect(
      lock.submitClaim(plotId, SEASON, Verdict.NoBurn, evidenceHash, 31, deadline, badSig)
    ).to.be.revertedWithCustomError(lock, "InvalidOracleSignature");
  });

  it("reverts when a nonce is replayed", async function () {
    const plotA = await registerAs(farmer, SEASON, [10001]);
    const plotB = await registerAs(farmer, SEASON, [10002]);
    const deadline = await futureDeadline();
    const sigA = await signClaim(oracle, plotA, SEASON, Verdict.NoBurn, evidenceHash, 41, deadline);
    await lock.submitClaim(plotA, SEASON, Verdict.NoBurn, evidenceHash, 41, deadline, sigA);

    // The oracle's signature for plot B is valid, but the nonce is spent.
    const sigB = await signClaim(oracle, plotB, SEASON, Verdict.NoBurn, evidenceHash, 41, deadline);
    await expect(
      lock.submitClaim(plotB, SEASON, Verdict.NoBurn, evidenceHash, 41, deadline, sigB)
    ).to.be.revertedWithCustomError(lock, "NonceAlreadyUsed");
  });

  it("reverts when the deadline has expired", async function () {
    const plotId = await registerAs(farmer, SEASON, [11001]);
    const block = await ethers.provider.getBlock("latest");
    const expired = block.timestamp - 5;
    const sig = await signClaim(oracle, plotId, SEASON, Verdict.NoBurn, evidenceHash, 51, expired);
    await expect(
      lock.submitClaim(plotId, SEASON, Verdict.NoBurn, evidenceHash, 51, expired, sig)
    ).to.be.revertedWithCustomError(lock, "SignatureExpired");
  });

  it("reverts a claim for an unknown plot and for a season mismatch", async function () {
    const deadline = await futureDeadline();
    const sig = await signClaim(oracle, 99, SEASON, Verdict.NoBurn, evidenceHash, 61, deadline);
    await expect(
      lock.submitClaim(99, SEASON, Verdict.NoBurn, evidenceHash, 61, deadline, sig)
    ).to.be.revertedWithCustomError(lock, "PlotNotFound");

    const plotId = await registerAs(farmer, SEASON, [12001]);
    const sig2 = await signClaim(oracle, plotId, OTHER_SEASON, Verdict.NoBurn, evidenceHash, 62, deadline);
    await expect(
      lock.submitClaim(plotId, OTHER_SEASON, Verdict.NoBurn, evidenceHash, 62, deadline, sig2)
    ).to.be.revertedWithCustomError(lock, "SeasonMismatch");
  });

  it("reverts registration with an empty cell set", async function () {
    await expect(lock.registerPlot(SEASON, []))
      .to.be.revertedWithCustomError(lock, "EmptyCellSet");
  });
});
