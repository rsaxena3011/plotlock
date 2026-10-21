const { expect } = require("chai");
const { ethers } = require("hardhat");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

// Round trip: the PYTHON oracle (oracle/sign_claim.py) signs a claim for a
// fixture bundle; this suite submits that signature to a locally deployed
// PlotLock and expects the contract to accept it. This is the cross-language
// proof that oracle/signing.py builds exactly the digest the contract checks
// (verdictDigest equivalence is asserted directly too).
//
// Needs: ORACLE_ADDRESS in .env and the oracle venv (oracle/.venv) or a
// python3 with the oracle deps installed. Skips cleanly otherwise.
describe("PlotLock x Python oracle round trip", function () {
  const SEASON = 2026;
  const repoRoot = path.join(__dirname, "..");
  const venvPython = path.join(repoRoot, "oracle", ".venv", "bin", "python");
  const python = fs.existsSync(venvPython) ? venvPython : "python3";
  const oracleAddress = process.env.ORACLE_ADDRESS;

  let lock, farmer;

  function oracleSign(fixture, plotId, nonce, deadline) {
    const out = execFileSync(
      python,
      [
        path.join(repoRoot, "oracle", "sign_claim.py"),
        "--fixture", fixture,
        "--plot-id", String(plotId),
        "--season", String(SEASON),
        "--nonce", String(nonce),
        "--deadline", String(deadline),
        "--contract", lock.target,
        "--chain-id", "31337",
      ],
      { encoding: "utf8" }
    );
    return JSON.parse(out);
  }

  async function futureDeadline(seconds = 3600) {
    const block = await ethers.provider.getBlock("latest");
    return block.timestamp + seconds;
  }

  beforeEach(async function () {
    if (!oracleAddress) this.skip();
    try {
      execFileSync(python, ["-c", "import eth_account"], { stdio: "pipe" });
    } catch {
      this.skip();
    }
    [, farmer] = await ethers.getSigners();
    const PlotLock = await ethers.getContractFactory("PlotLock");
    lock = await PlotLock.deploy(oracleAddress);
    await lock.waitForDeployment();
  });

  it("accepts a Python-oracle signature end to end (digest equivalence + Attested)", async function () {
    const fixture = JSON.parse(
      fs.readFileSync(path.join(repoRoot, "oracle", "fixtures", "plot-1-clean.json"), "utf8")
    );
    const cells = fixture.plot.h3_cells.slice(0, 12).map(BigInt);
    const tx = await lock.connect(farmer).registerPlot(SEASON, cells);
    const receipt = await tx.wait();
    const ev = receipt.logs
      .map((l) => { try { return lock.interface.parseLog(l); } catch { return null; } })
      .find((e) => e && e.name === "PlotRegistered");
    const plotId = ev.args.plotId;

    const deadline = await futureDeadline();
    const signed = oracleSign("plot-1-clean", plotId, 31337001, deadline);
    expect(signed.oracle_address).to.equal(oracleAddress);
    expect(signed.verdict).to.equal("NoBurn");

    // The digest the Python oracle signed == the contract's verdictDigest.
    const contractDigest = await lock.verdictDigest(
      plotId, SEASON, signed.verdict_uint, signed.evidence_hash, signed.nonce, signed.deadline
    );
    expect(signed.digest).to.equal(contractDigest);

    await expect(
      lock.submitClaim(plotId, SEASON, signed.verdict_uint, signed.evidence_hash,
                       signed.nonce, signed.deadline, signed.signature)
    ).to.emit(lock, "Attested");
    expect(await lock.hasAttestation(plotId, SEASON)).to.equal(true);
  });

  it("rejects the same signature when the evidence hash is tampered with", async function () {
    const fixture = JSON.parse(
      fs.readFileSync(path.join(repoRoot, "oracle", "fixtures", "plot-2-burned.json"), "utf8")
    );
    const cells = fixture.plot.h3_cells.slice(0, 12).map(BigInt);
    await lock.connect(farmer).registerPlot(SEASON, cells);

    const deadline = await futureDeadline();
    const signed = oracleSign("plot-2-burned", 1, 31337002, deadline);
    expect(signed.verdict).to.equal("Burned");

    // Flip one hex char of the evidence hash: the recorded report no longer
    // matches what the oracle signed (the tamper-evidence property).
    const tamperedHash = signed.evidence_hash.slice(0, -1) +
      (signed.evidence_hash.endsWith("0") ? "1" : "0");
    await expect(
      lock.submitClaim(1, SEASON, signed.verdict_uint, tamperedHash,
                       signed.nonce, signed.deadline, signed.signature)
    ).to.be.revertedWithCustomError(lock, "InvalidOracleSignature");
  });
});
