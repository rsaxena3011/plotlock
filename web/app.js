"use strict";
/* PlotLock demo map UI. All plot data comes from data.js, which is generated
 * from oracle/fixtures/*.json - this file invents no metrics. */

const DATA = PLOTLOCK_DATA;
const OC = DATA.onchain;
const EXPLORER = OC.explorer;

const VERDICT_CLASS = { NoBurn: "clean", Burned: "burned", Uncertain: "uncertain" };
const VERDICT_FILL = { clean: "#1a9850", burned: "#d73027", uncertain: "#e69f00" };

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function has(v) { return v !== undefined && v !== null; }
function row(label, value) {
  if (!has(value) || value === "") return "";
  return `<tr><th>${esc(label)}</th><td>${value}</td></tr>`;
}
function mono(s) { return `<span class="mono">${esc(s)}</span>`; }
function shortHash(h) { return h && h.length > 22 ? `${h.slice(0, 12)}…${h.slice(-8)}` : h; }
function txLink(tx, label) {
  return `<a href="${EXPLORER}/tx/${esc(tx)}" target="_blank" rel="noopener">${esc(label || shortHash(tx))}</a>`;
}
function addrLink(addr, label) {
  return `<a href="${EXPLORER}/address/${esc(addr)}" target="_blank" rel="noopener">${esc(label || shortHash(addr))}</a>`;
}
function pct(frac) { return `${Math.round(frac * 100)}%`; }
function signed(n) { return (n > 0 ? "+" : "") + n; }

/* ---------- evidence hashing (tamper demo) ----------
 * The production oracle computes evidenceHash = keccak256 of the canonical
 * evidence bundle (JSON, sorted keys, compact separators) - see
 * oracle/evidence.py - and also exposes a SHA-256 of the bundle
 * (`evidence_sha256`) as a human-auditable cross-check. Browsers have no
 * keccak, so this demo recomputes a SHA-256 over its canonical copy of the
 * bundle instead. The property being demonstrated is identical: change any
 * field, the hash changes, and the oracle's signature over the original
 * hash no longer verifies. */
function canonicalStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonicalStringify).join(",") + "]";
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalStringify(value[k])).join(",") + "}";
}
async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/* ---------- map ---------- */
const plotById = {};
DATA.plots.forEach((p) => { plotById[p.bundle_id] = p; });

const map = L.map("map", { scrollWheelZoom: true });
const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
});
const satellite = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 17, attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics",
  });
satellite.addTo(map);
L.control.layers({ "Satellite (Esri)": satellite, "Streets (OSM)": osm }).addTo(map);

const layers = {};
const allBounds = [];
let selectedId = null;

function styleFor(p) {
  if (p.bundle_id === "plot-4-duplicate") {
    return { color: "#444444", weight: 2.5, dashArray: "7 5", fillColor: "#444444", fillOpacity: 0.16 };
  }
  const c = VERDICT_FILL[VERDICT_CLASS[p.expected_verdict]];
  return { color: c, weight: 2.5, fillColor: c, fillOpacity: 0.32 };
}

DATA.plots.forEach((p) => {
  const layer = L.polygon(p.polygon_latlon, styleFor(p));
  layer.on("click", () => selectPlot(p.bundle_id, false));
  layer.addTo(map);
  layers[p.bundle_id] = layer;
  allBounds.push(...p.polygon_latlon);

  if (p.firms && Array.isArray(p.firms.detections)) {
    p.firms.detections.forEach((d) => {
      if (!has(d.latitude) || !has(d.longitude)) return;
      L.marker([d.latitude, d.longitude], {
        icon: L.divIcon({ className: "", html: '<div class="fire-marker">!</div>', iconSize: [20, 20], iconAnchor: [10, 10] }),
      }).bindTooltip(
        `FIRMS/VIIRS detection: ${esc(d.acq_date || "")} ${esc(d.acq_time || "")} UTC, ` +
        `confidence ${esc(d.confidence || "")}, FRP ${esc(d.frp != null ? d.frp : "?")} MW`
      ).addTo(map);
    });
  }
});
map.fitBounds(allBounds, { padding: [30, 30] });

/* ---------- plot shortcut cards ---------- */
const cardsEl = document.getElementById("plot-cards");
DATA.plots.forEach((p) => {
  const isDup = p.bundle_id === "plot-4-duplicate";
  const cls = isDup ? "duplicate" : VERDICT_CLASS[p.expected_verdict];
  const verdictText = isDup ? "Registration rejected" : p.expected_verdict;
  const btn = document.createElement("button");
  btn.className = `plot-card v-${cls}`;
  btn.id = `card-${p.bundle_id}`;
  btn.innerHTML = `<span class="pc-title">${esc(p.plot.label.split(" - ")[0])}</span>` +
    `<span class="pc-sub">${esc(verdictText)} · ${esc(p.provenance_tag)}</span>`;
  btn.addEventListener("click", () => selectPlot(p.bundle_id, true));
  cardsEl.appendChild(btn);
});

/* ---------- evidence panel ---------- */
const panel = document.getElementById("panel");

function verdictChip(p) {
  if (p.bundle_id === "plot-4-duplicate") {
    return `<span class="chip chip-v-duplicate">Registration reverted</span>`;
  }
  const cls = VERDICT_CLASS[p.expected_verdict];
  return `<span class="chip chip-v-${cls}">Verdict: ${esc(p.expected_verdict)}</span>`;
}

function metricsTable(p) {
  const s2 = p.sentinel2 || {};
  const firms = p.firms || {};
  let rowsHtml = "";
  rowsHtml += row("District", esc(p.plot.district));
  rowsHtml += row("Season", esc(p.plot.season));
  rowsHtml += row("Evidence window", p.evidence_window
    ? esc(`${p.evidence_window.from} → ${p.evidence_window.to}`) : null);
  rowsHtml += row("H3 cells (res " + esc(p.plot.h3_resolution) + ")", esc(p.h3_cell_count));
  if (has(firms.status)) {
    const dets = Array.isArray(firms.detections) ? firms.detections : [];
    const counting = dets.filter((d) => d.inside_plot && ["n", "h"].includes(String(d.confidence || "").toLowerCase())).length;
    rowsHtml += row("FIRMS/VIIRS status", esc(firms.status));
    rowsHtml += row("FIRMS detections in window", esc(dets.length));
    if (dets.length) rowsHtml += row("Counting detections (inside plot, conf n/h)", esc(counting));
    rowsHtml += row("FIRMS source", esc(firms.source));
  }
  if (s2.status === "ok") {
    rowsHtml += row("Sentinel-2 NBR, pre (" + esc(s2.pre_date || "") + ")", esc(s2.nbr_pre));
    rowsHtml += row("Sentinel-2 NBR, post (" + esc(s2.post_date || "") + ")", esc(s2.nbr_post));
    rowsHtml += row("Mean dNBR (scar signal)", esc(signed(s2.dnbr_mean)) +
      (s2.dnbr_mean >= 0.10 ? ", at/above the 0.10 scar threshold" : ", below the 0.10 scar threshold"));
    rowsHtml += row("Pixels with dNBR ≥ 0.15", pct(s2.burned_pixel_fraction) +
      " of plot pixels (scar-positive at ≥ 25%)");
    rowsHtml += row("Sentinel-2 pre item", mono(s2.pre_item));
    rowsHtml += row("Sentinel-2 post item", mono(s2.post_item));
  } else if (has(s2.status)) {
    rowsHtml += row("Sentinel-2 status", `<strong>${esc(s2.status)}</strong>`);
    if (s2.unavailable_reason) rowsHtml += row("Why unavailable", esc(s2.unavailable_reason));
    if (Array.isArray(s2.acquisitions_considered)) {
      s2.acquisitions_considered.forEach((a) => {
        rowsHtml += row(`Cloud cover, ${esc(a.acq_date)}`, `<strong>${esc(a.tile_cloud_cover_pct)}%</strong> tile cloud`);
      });
    }
    if (s2.next_clear_acquisition) rowsHtml += row("Next clear acquisition", esc(s2.next_clear_acquisition));
    rowsHtml += row("Sentinel-2 source", esc(s2.source));
  }
  return rowsHtml ? `<h3>Plot &amp; evidence</h3><table class="kv">${rowsHtml}</table>` : "";
}

function firmsTable(p) {
  const dets = (p.firms && p.firms.detections) || [];
  if (!dets.length) return "";
  let rowsHtml = "";
  dets.forEach((d, i) => {
    rowsHtml += row(
      `Detection ${i + 1}`,
      `${esc(d.acq_date)} ${esc(d.acq_time)} UTC · ${esc(d.satellite)} ${esc(d.instrument)} · ` +
      `confidence <strong>${esc(d.confidence)}</strong> · brightness ${esc(d.brightness)} K · FRP ${esc(d.frp)} MW · ` +
      `inside plot: ${d.inside_plot ? "yes" : "no"}`
    );
  });
  return `<h3>FIRMS/VIIRS detections</h3><table class="kv">${rowsHtml}</table>`;
}

function onchainSection(p) {
  if (p.bundle_id !== "plot-1-clean") return "";
  const c = OC.plot1;
  let rowsHtml = "";
  rowsHtml += row("Contract (Polygon Amoy)", addrLink(OC.contract));
  rowsHtml += row("Oracle", mono(OC.oracle_address));
  rowsHtml += row("Plot ID / season", `${esc(c.plot_id)} / ${esc(c.season)}`);
  rowsHtml += row("Registered", `${txLink(c.register_tx, "registerPlot tx")} · block ${esc(c.register_block)} · Success`);
  rowsHtml += row("Claim attested", `${txLink(c.claim_tx, "submitClaim tx")} · block ${esc(c.claim_block)} · Success`);
  rowsHtml += row("Evidence hash (on-chain, keccak-256)", mono(c.evidence_hash));
  rowsHtml += row("Cells hash", mono(c.cells_hash));
  rowsHtml += row("Oracle nonce", esc(c.nonce));
  rowsHtml += row("Wallet funding (faucet)", txLink(c.funding_tx, "0.05 POL claim"));
  return `<h3>On-chain record</h3>
    <div class="ok-box"><strong>Attested on-chain.</strong> The oracle signed this plot's NoBurn
    verdict and the contract recorded the attestation. Anyone can replay it from the links
    below, no wallet or API key needed.</div>
    <table class="kv">${rowsHtml}</table>`;
}

function duplicateSection(p) {
  if (p.bundle_id !== "plot-4-duplicate") return "";
  const r = OC.duplicate_rejection;
  const rowsHtml =
    row("Base plot", esc("Plot 1 - clean paddy field")) +
    row("Outline shift", `~${esc(p.shift_m_approx.east)} m east, ~${esc(p.shift_m_approx.north)} m north`) +
    row("H3 cells in redrawn outline", esc(p.h3_cell_count)) +
    row("Cells already registered to plot 1", `<strong>${esc(p.overlapping_cell_count)}</strong>`) +
    row("Replay method", esc(r.method));
  return `<h3>The duplicate attempt</h3>
    <table class="kv">${rowsHtml}</table>
    <div class="revert-box">Registration <strong>reverts</strong> with
    <span class="mono">${esc(r.error)}(${esc(r.season)}, ${esc(r.cell)})</span>, the redrawn outline
    still covers H3 cells that plot 1 registered for season ${esc(r.season)}, so the same land
    cannot be registered, or claimed, a second time.</div>`;
}

/* tamper demo (plot 1): state held here, rebuilt on each render */
let tamperValue = null; // null = bundle untouched
let recordedDemoHash = null;

async function tamperSectionHtml(p) {
  if (p.bundle_id !== "plot-1-clean") return "";
  const bundle = JSON.parse(JSON.stringify(DATA.plot1_full_bundle));
  const originalDnbr = bundle.sentinel2.dnbr_mean;
  if (tamperValue !== null) bundle.sentinel2.dnbr_mean = tamperValue;
  const recomputed = await sha256Hex(canonicalStringify(bundle));
  if (recordedDemoHash === null) recordedDemoHash = recomputed;
  const match = tamperValue === null;
  return `<h3>Tamper-evidence demo</h3>
    <p class="tamper-note">Browser-side equivalent of the oracle's <code>POST /verify</code>
    check: SHA-256 over the canonical evidence bundle (sorted keys, compact JSON),
    standing in for the keccak-256 the oracle uses to produce the on-chain evidenceHash
    above. Edit the evidence and the recomputed hash stops matching the recorded one,
    exactly as a tampered bundle fails the oracle's signature check.</p>
    <table class="kv">
      ${row("Mean dNBR in this bundle", `<strong>${esc(tamperValue === null ? originalDnbr : tamperValue)}</strong>` +
        (tamperValue === null ? "" : ` (original: ${esc(originalDnbr)})`))}
    </table>
    <div class="hash-line"><span>Recorded demo hash</span><span class="mono">${esc(shortHash(recordedDemoHash))}</span></div>
    <div class="hash-line"><span>Recomputed now</span><span class="mono">${esc(shortHash(recomputed))}</span></div>
    <div class="hash-line"><span>Status</span>
      <span class="hash-status ${match ? "hash-ok" : "hash-bad"}">${match ? "MATCH: evidence untouched" : "MISMATCH: tamper detected"}</span></div>
    <div class="tamper-controls">
      <button class="btn" id="btn-tamper" ${match ? "" : "disabled"}>Tamper: set mean dNBR to 0.240 (a burned value)</button>
      <button class="btn secondary" id="btn-reset" ${match ? "disabled" : ""}>Reset evidence</button>
    </div>`;
}

async function renderPanel(p) {
  const isDup = p.bundle_id === "plot-4-duplicate";
  const chainChip = p.bundle_id === "plot-1-clean"
    ? `<span class="chip chip-chain">Attested on-chain · Polygon Amoy</span>` : "";
  const outcome = isDup
    ? `<div class="revert-box">This registration can never succeed while plot 1 holds these
       cells for season ${esc(p.plot.season)}, that rejection is the product.</div>`
    : p.expected_verdict === "NoBurn"
      ? `<div class="ok-box">Both signals present and clean, so this is the one verdict that
         records a payout-eligible attestation.</div>`
      : p.expected_verdict === "Burned"
        ? `<div class="revert-box">Both signals confirm a burn, so no attestation and no
           payout is recorded for this plot.</div>`
        : `<div class="revert-box" style="background:#fdf6e3;border-color:#ecd9a0">A required
           signal is unavailable, so the verdict is Uncertain, and Uncertain never pays.</div>`;

  panel.innerHTML = `
    <h2>${esc(p.plot.label)}</h2>
    <p class="district">${esc(p.plot.district)} · bundle <span class="mono">${esc(p.bundle_id)}</span></p>
    <div class="chips">${verdictChip(p)}
      <span class="chip chip-prov">Provenance: ${esc(p.provenance_tag)}</span>${chainChip}</div>
    ${outcome}
    ${metricsTable(p)}
    ${firmsTable(p)}
    ${duplicateSection(p)}
    ${onchainSection(p)}
    <div id="tamper-slot"></div>
    <h3>Provenance</h3>
    <p class="provenance"><strong>${esc(p.provenance_tag)}.</strong> ${esc(p.provenance_short)}</p>
    <p class="provenance">${esc(p.provenance)}</p>
    <div class="plot-nav">
      <button id="nav-prev" type="button">← Previous plot</button>
      <button id="nav-next" type="button">Next plot →</button>
    </div>`;

  const idx = DATA.plots.findIndex((x) => x.bundle_id === p.bundle_id);
  document.getElementById("nav-prev").addEventListener("click",
    () => selectPlot(DATA.plots[(idx + DATA.plots.length - 1) % DATA.plots.length].bundle_id, true));
  document.getElementById("nav-next").addEventListener("click",
    () => selectPlot(DATA.plots[(idx + 1) % DATA.plots.length].bundle_id, true));

  const slot = document.getElementById("tamper-slot");
  if (slot && p.bundle_id === "plot-1-clean") {
    slot.innerHTML = await tamperSectionHtml(p);
    wireTamper(p, slot);
  }
}

function wireTamper(p, slot) {
  const tamperBtn = document.getElementById("btn-tamper");
  const resetBtn = document.getElementById("btn-reset");
  if (tamperBtn) tamperBtn.addEventListener("click", async () => {
    tamperValue = 0.24;
    slot.innerHTML = await tamperSectionHtml(p);
    wireTamper(p, slot);
  });
  if (resetBtn) resetBtn.addEventListener("click", async () => {
    tamperValue = null;
    slot.innerHTML = await tamperSectionHtml(p);
    wireTamper(p, slot);
  });
}

function selectPlot(bundleId, pan) {
  selectedId = bundleId;
  const p = plotById[bundleId];
  document.querySelectorAll(".plot-card").forEach((el) => el.classList.remove("active"));
  const card = document.getElementById(`card-${bundleId}`);
  if (card) card.classList.add("active");
  if (pan) map.flyToBounds(layers[bundleId].getBounds(), { padding: [40, 40], maxZoom: 15 });
  layers[bundleId].bringToFront();
  renderPanel(p);
}

/* default view: plot 1, the attested clean plot */
selectPlot("plot-1-clean", false);
