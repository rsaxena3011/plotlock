// PlotLock deploy script - Polygon Amoy testnet only.
// Usage: npx hardhat run scripts/deploy.js --network amoy
// Requires in .env: DEPLOYER_PRIVATE_KEY (funded with testnet MATIC),
// ORACLE_ADDRESS. Prints the contract address and explorer link.
require("dotenv").config();
const { ethers } = require("hardhat");

async function main() {
  const oracleAddress = process.env.ORACLE_ADDRESS;
  if (!oracleAddress) {
    throw new Error("Missing ORACLE_ADDRESS in .env - cannot deploy without the oracle address.");
  }
  const [deployer] = await ethers.getSigners();
  const balance = await ethers.provider.getBalance(deployer.address);
  console.log("Deployer:", deployer.address);
  console.log("Balance:", ethers.formatEther(balance), "MATIC");
  if (balance === 0n) {
    throw new Error(
      "Deployer wallet has 0 testnet MATIC. Fund it from a Polygon Amoy faucet, then re-run. Deployment NOT attempted."
    );
  }

  const PlotLock = await ethers.getContractFactory("PlotLock");
  const lock = await PlotLock.deploy(oracleAddress);
  await lock.waitForDeployment();
  const address = await lock.getAddress();
  console.log("PlotLock deployed to:", address);
  console.log("Oracle:", oracleAddress);
  console.log("Explorer:", `https://amoy.polygonscan.com/address/${address}`);
  console.log(
    "Verify source with: npx hardhat verify --network amoy",
    address,
    oracleAddress
  );
}

main().catch((err) => {
  console.error(err.message || err);
  process.exitCode = 1;
});
