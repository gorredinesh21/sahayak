/* Sahayak — Paytm-clone app (vanilla ES modules, no build step) */
const $ = (sel, el = document) => el.querySelector(sel);
const screen = $("#screen");
const statusbar = $("#statusbar");

const state = {
  me: null,
  history: [],
  scenario: "auto",           // dev drawer override
  prefill: null,              // {vpa, amount_paise} for the Mode C shortcut
  demoCases: [],
};

/* ---------------------------------------------------------------- helpers */
const RUPEE_FMT = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const fmt = (paise) => {
  const v = paise / 100;
  return v % 1 === 0 ? RUPEE_FMT.format(v) : RUPEE_FMT.format(v.toFixed(2));
};
const TOKEN_KEY = "sahayak_token";
/* Token storage: cookie first (this webview can drop localStorage between
   navigations), localStorage as a secondary mirror. */
let MEM_TOKEN = "";          // this webview drops localStorage AND cookies set
const setToken = (t) => {    // client-side; server also sets its own cookie.
  MEM_TOKEN = t;
  try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { /* fine */ }
};
const clearToken = () => {
  MEM_TOKEN = "";
  try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* fine */ }
  fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
};
const getToken = () => {
  if (MEM_TOKEN) return MEM_TOKEN;         // live session in this page
  try { return localStorage.getItem(TOKEN_KEY) || ""; }
  catch (e) { return ""; }
};
const fetchWrap = fetch; // the server cookie rides along automatically

const api = async (path, opts) => {
  const tokenUsed = getToken();
  const r = await fetch(path, opts && {
    ...opts, headers: {
      "Content-Type": "application/json",
      "x-sahayak-token": tokenUsed,
      ...(opts.headers || {}),
    },
  });
  if (r.status === 401 && !path.includes("/auth/")) {
    if (getToken() === tokenUsed) {      // no newer login happened meanwhile
      clearToken();
      renderLogin("Session expired — please log in again");
    }
    throw new Error("session expired");
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* keep */ }
    throw new Error(msg);
  }
  return r.json();
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; $("#phone").appendChild(t); }
  t.textContent = msg; t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2200);
}
function humanTime(iso) {
  const d = new Date(iso), now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yest = new Date(now - 864e5).toDateString() === d.toDateString();
  const t = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  return sameDay ? `Today, ${t}` : yest ? `Yesterday, ${t}` :
    d.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) + `, ${t}`;
}
const statusChip = (s) =>
  s === "SUCCESS" ? `<span class="st-chip ok">✓ SUCCESS</span>` :
  s === "PENDING" ? `<span class="st-chip wt">● PENDING</span>` :
                    `<span class="st-chip bad">✕ FAILED</span>`;
const setLightBar = (light) => statusbar.classList.toggle("on-light", !!light);

/* clock */
function tickClock() {
  $("#clock").textContent = new Date().toLocaleTimeString("en-IN",
    { hour: "numeric", minute: "2-digit" });
}
setInterval(tickClock, 3e4); tickClock();

/* ---------------------------------------------------------------- icons */
const I = {
  bell: `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#17212B" stroke-width="2" stroke-linecap="round"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>`,
  search: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#5A6B7B" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`,
  scan: `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M3 12h18"/></svg>`,
  phone: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0091C7" stroke-width="1.9" stroke-linecap="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3A19.5 19.5 0 0 1 5.1 13 19.8 19.8 0 0 1 2 4.2 2 2 0 0 1 4 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.2-1.2a2 2 0 0 1 2.1-.5c.9.3 1.9.6 2.8.7A2 2 0 0 1 22 16.9z"/></svg>`,
  at: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0091C7" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/></svg>`,
  book: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0091C7" stroke-width="1.9" stroke-linecap="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></svg>`,
  qr: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#0091C7" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM20 14v.01M14 20v.01M20 20v.01M17.5 17.5h.01"/></svg>`,
  home: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m3 10 9-7 9 7v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`,
  sparkle: `<svg width="19" height="19" viewBox="0 0 24 24" fill="#fff"><path d="M12 2l1.9 5.7L19.6 9.6 13.9 11.5 12 17.2l-1.9-5.7L4.4 9.6l5.7-1.9z"/><circle cx="18.6" cy="17.3" r="2.1"/></svg>`,
  back: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"><path d="M15 5l-7 7 7 7"/></svg>`,
  backDark: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#17212B" stroke-width="2.4" stroke-linecap="round"><path d="M15 5l-7 7 7 7"/></svg>`,
  person: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/></svg>`,
};

/* ================================================================ S1 HOME */
export async function renderHome() {
  setLightBar(true);
  screen.innerHTML = `<div class="screen-panel">
    <div class="home-header">
      <div class="hh-row1">
        <div class="wordmark"><span class="p1">pay</span><span class="p2">tm</span><span>DEMO</span></div>
        <div class="hh-icons">
          <div class="icon-btn">${I.bell}<span class="dot-badge"></span></div>
          <div class="avatar">${esc(state.me.initials)}</div>
        </div>
      </div>
      <div class="search-pill" id="searchPill">${I.search} Search for mobile no., UPI ID, QR</div>
    </div>
    <div class="tiles-card">
      <div class="tile" id="tScan"><div class="tico">${I.scan}</div><div class="tlb">Scan &amp;<br>Pay</div></div>
      <div class="tile" id="tMobile"><div class="tico">${I.phone}</div><div class="tlb">To Mobile<br>Number</div></div>
      <div class="tile" id="tVpa"><div class="tico">${I.at}</div><div class="tlb">To UPI ID<br>/ App</div></div>
      <div class="tile" id="tBook"><div class="tico">${I.book}</div><div class="tlb">Balance &amp;<br>History</div></div>
    </div>
    <div class="pad" style="margin-top:14px">
      <div class="bank-strip" id="bankStrip">
        <div class="bs-bank">🏦</div>
        <div style="flex:1">
          <div style="font-weight:800;font-size:13.5px">Paytm Payments Bank</div>
          <div style="font-family:var(--font-mono);font-size:11px;color:var(--ink-2);margin-top:1px">Savings ••4291</div>
        </div>
        <span style="font-size:12px;font-weight:800;color:var(--cyan-deep)">Check Balance</span>
      </div>
      <div class="bal-reveal" id="balReveal">
        <div class="br-a" id="balAmt"></div>
        <div class="br-s">Available balance · as of now</div>
      </div>
    </div>
    <div class="section-head"><span class="st">Recharge &amp; Pay Bills</span></div>
    <div class="pad"><div class="txn-card" id="billsCard" style="display:flex;flex-wrap:wrap;padding:12px 4px 8px">
      ${[["📱", "Mobile<br>Recharge"], ["📺", "DTH"], ["💡", "Electricity"], ["🏦", "Loan EMI"],
         ["🏠", "Rent"], ["💳", "Credit<br>Card"], ["•••", "More"]]
        .map(([ic, b]) => `<div style="flex:1 1 25%;text-align:center;padding:6px 4px 10px;font-size:10.5px;font-weight:700;color:var(--ink-2)">
          <div style="font-size:20px;margin-bottom:4px">${ic}</div>${b}</div>`).join("")}
    </div></div>
    <div class="section-head"><span class="st">Recent Transactions</span>
      <span class="sa" id="viewAll">View All →</span></div>
    <div class="txn-card" id="recentList"></div>
    <div style="height:20px"></div>
    <div class="bottom-nav">
      <div class="bn-item active" id="bnHome">${I.home}Home</div>
      <div class="bn-item" id="bnBook">${I.book}Balance</div>
      <div class="bn-fab" id="bnFab"><div class="fab">${I.scan}</div></div>
      <div class="bn-item">💳 Cards</div>
      <div class="bn-item" id="bnQr">${I.person}Profile</div>
    </div>
  </div>`;

  const recent = state.history.slice(0, 3);
  $("#recentList").innerHTML = recent.map(txnRowHTML).join("") ||
    `<div style="padding:18px;text-align:center;color:var(--ink-3);font-size:13px">No transactions yet</div>`;
  recent.forEach((t) => $(`#recentList .txn-row[data-id="${t.txn_id}"]`)
    .onclick = () => renderDetail(t.txn_id));

  $("#bankStrip").onclick = async () => {
    const reveal = $("#balReveal");
    if (reveal.classList.contains("show")) { reveal.classList.remove("show"); return; }
    $("#balAmt").textContent = "…";
    reveal.classList.add("show");
    await refresh();
    $("#balAmt").textContent = `₹ ${fmt(state.me.balance_paise)}`;
  };
  $("#tScan").onclick = $("#bnFab").onclick = () => renderPay({ scan: true });
  $("#tVpa").onclick = $("#tMobile").onclick = () => renderPay({});
  $("#tBook").onclick = $("#bnBook").onclick = $("#viewAll").onclick = renderHistory;
  $("#bnHome").onclick = renderHome;
  $("#bnQr").onclick = renderProfile;
  $("#searchPill").onclick = $("#billsCard").onclick = () => toast("Not available in demo");
}

function txnRowHTML(t) {
  const credit = t.entry_type === "credit";
  const icon = credit ? `<div class="tico2 t-s">↓</div>` :
    t.status === "SUCCESS" ? `<div class="tico2 t-s">✓</div>` :
    t.status === "PENDING" ? `<div class="tico2 t-p">●</div>` :
                             `<div class="tico2 t-f">✕</div>`;
  return `<div class="txn-row" data-id="${t.txn_id}">${icon}
    <div class="tmain"><div class="tn">${credit ? "From " : ""}${esc(t.to_name)}</div>
      <div class="ts">${humanTime(t.initiated_at)} · UPI</div></div>
    <div class="amt ${credit ? "pos" : "neg"}">${credit ? "+" : ""}₹ ${fmt(t.amount_paise)}
      <div>${credit ? `<span class="st-chip ok">RECEIVED</span>` : statusChip(t.status)}</div></div>
  </div>`;
}

/* ================================================================ S2 PAY */
export function renderPay(ctx = {}) {
  setLightBar(true);   // white 2025-style screens → dark status icons
  const step = { vpa: "", verified: null, amount: "", pin: "" };
  screen.innerHTML = `<div class="screen-panel" style="background:var(--surface)">
    <div class="pay2-head"><div class="back2" id="pBack">${I.backDark}</div>
      <div class="pt">Pay</div></div>
    <div class="pay-body" id="payBody"></div>
    <div class="keypad2" id="pad" style="display:none"></div>
    <button class="paybtn" id="pCta" style="display:none">Verify</button>
  </div>`;
  $("#pBack").onclick = renderHome;

  const body = $("#payBody"), pad = $("#pad"), cta = $("#pCta");
  const initials = (n) => n.replace(/[^A-Za-z ]/g, "").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase() || "P";

  function drawVPA() {
    screen.scrollTop = 0;   // keep the header visible on step change
    pad.style.display = "none"; cta.style.display = "block";
    cta.textContent = "Verify UPI ID";
    cta.disabled = true;
    body.innerHTML = `
      <div class="payee-block">
        <div class="payee-av">₹</div>
        <div class="payee-name" style="margin-top:16px">Enter UPI ID or number</div>
        <div class="payee-vpa" style="margin-top:8px">Money is sent safely via UPI</div>
      </div>
      <div style="margin:26px 16px 0">
        <input class="vpa-input" id="vpaIn" placeholder="name@bank" autocomplete="off"
          value="${esc(state.prefill?.vpa || "")}">
        ${ctx.error ? `<div style="color:var(--failure);font-size:12.5px;font-weight:700;margin-top:8px">✕ ${esc(ctx.error)}</div>` : ""}
      </div>
      <div style="margin:22px 16px 0;display:flex;gap:10px">
        <button class="qchip" id="goScan">📷 Scan any QR code</button>
        <button class="qchip" id="showMyQr">My QR code</button>
      </div>`;
    const inp = $("#vpaIn"); inp.focus();
    const sync = () => { cta.disabled = !inp.value.trim().includes("@"); };
    inp.oninput = sync; sync();
    cta.onclick = verify;
    inp.onkeydown = (e) => e.key === "Enter" && !cta.disabled && verify();
    $("#goScan").onclick = () => renderScan();
    $("#showMyQr").onclick = renderMyQR;
    async function verify() {
      const v = inp.value.trim();
      cta.disabled = true; cta.textContent = "Verifying…";
      try {
        step.vpa = v;
        step.verified = await api(`/api/beneficiary/resolve?vpa=${encodeURIComponent(v)}`);
        drawAmount();
      } catch (e) {
        renderPay({ ...ctx, error: e.message });
      }
    }
  }

  function drawAmount() {
    screen.scrollTop = 0;   // keep the header visible on step change
    cta.style.display = "block"; pad.style.display = "grid"; cta.disabled = true;
    body.innerHTML = `
      <div class="payee-block">
        <div class="payee-av">${esc(initials(step.verified.name))}</div>
        <div class="payee-name">${esc(step.verified.name)}</div>
        <div class="payee-vpa">${esc(step.vpa)}</div>
        <div class="payee-ok">✓ ${step.verified.kind === "merchant" ? "Verified merchant" : "Verified name"}</div>
      </div>
      <div class="amt2" id="amtD"><span class="cur">₹</span><span id="amtV">0</span><span class="caret"></span></div>
      <div class="note-pill" id="notePill">✎ Add a note</div>`;
    if (state.prefill?.amount_paise) {
      step.amount = String(state.prefill.amount_paise / 100);
      syncAmt();
    }
    const keys = ["1","2","3","4","5","6","7","8","9",".","0","⌫"];
    pad.innerHTML = keys.map((k) =>
      `<div class="key ${k === "⌫" ? "fn" : ""}" data-k="${k}">${k}</div>`).join("");
    pad.querySelectorAll(".key").forEach((el) => el.onclick = () => {
      const k = el.dataset.k;
      if (k === "⌫") step.amount = step.amount.slice(0, -1);
      else if (k === "." && step.amount.includes(".")) return;
      else if (step.amount.replace(".", "").length < 7) step.amount += k;
      syncAmt();
    });
    $("#notePill").onclick = () => toast("Notes not available in demo");
    function syncAmt() {
      $("#amtV").textContent = step.amount || "0";
      const paise = Math.round(parseFloat(step.amount || "0") * 100);
      cta.disabled = !(paise >= 100);
      cta.textContent = cta.disabled ? "Enter amount" : `Pay  ₹ ${step.amount}`;
    }
    cta.onclick = () => { state.prefill = null; drawPIN(); };
  }

  function drawPIN() {
    screen.scrollTop = 0;   // keep the header visible on step change
    cta.style.display = "none"; pad.style.display = "grid";
    body.innerHTML = `
      <div class="pin-head">
        <div class="ph1">Enter UPI PIN</div>
        <div class="ph2">Paying <b>₹ ${fmt(Math.round(parseFloat(step.amount) * 100))}</b> to
          <b>${esc(step.verified.name)}</b></div>
        <div class="ph3">🏦 Paytm Payments Bank ••4291</div>
      </div>
      <div class="pin-dots" id="pd">${[0,1,2,3].map(() => `<span class="pd"></span>`).join("")}</div>
      <div style="text-align:center;color:var(--ink-3);font-size:11px">
        Demo: any 4 digits · "0000" simulates wrong PIN</div>`;
    const keys = ["1","2","3","4","5","6","7","8","9","","0","⌫"];
    pad.innerHTML = keys.map((k) =>
      k ? `<div class="key ${k === "⌫" ? "fn" : ""}" data-k="${k}">${k}</div>`
        : `<div></div>`).join("");
    pad.querySelectorAll(".key").forEach((el) => el.onclick = () => {
      const k = el.dataset.k;
      if (k === "⌫") step.pin = step.pin.slice(0, -1);
      else if (step.pin.length < 4) step.pin += k;
      $("#pd").innerHTML = [0,1,2,3].map((i) =>
        `<span class="pd ${i < step.pin.length ? "filled" : ""}"></span>`).join("");
      if (step.pin.length === 4) setTimeout(submit, 260);
    });
    async function submit() {
      pad.style.display = "none";
      try {
        const r = await api("/api/pay", { method: "POST", body: JSON.stringify({
          vpa: step.vpa, amount_paise: Math.round(parseFloat(step.amount) * 100),
          pin: step.pin, scenario: state.scenario }) });
        renderProcessing(r.txn_id);
      } catch (e) { toast(e.message); drawPIN(); }
    }
  }

  if (ctx.scan) renderScan(); else drawVPA();
}

/* ---------------------------------------------------------------- QR scan */
export async function renderScan() {
  setLightBar(false);
  screen.innerHTML = `<div class="screen-panel">
    <div class="pay-head"><div class="back-btn" id="sBack">${I.back}</div>
      <div class="pt">Scan any QR code</div></div>
    <div class="qr-panel">
      <div class="qr-video-wrap"><video id="v" playsinline muted></video>
        <div class="qr-line"></div></div>
      <div style="font-size:12px;color:var(--ink-3);margin:14px 0;text-align:center" id="sMsg">
        Point at a UPI QR code</div>
      <label class="qchip" style="cursor:pointer">🖼 Pick QR image instead
        <input type="file" accept="image/*" class="hidden-file" id="fIn"></label>
      <button class="qchip" id="sManual">⌨ Type UPI ID instead</button>
    </div></div>`;
  $("#sBack").onclick = () => renderPay({});
  $("#sManual").onclick = () => renderPay({});
  let stream = null, raf = 0, dead = false;

  try { await import("/src/lib/jsQR.min.js"); } catch (e) { /* image path still works */ }
  const jsQR = () => window.jsQR;

  async function startCam() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      const v = $("#v"); v.srcObject = stream; await v.play();
      const cv = document.createElement("canvas");
      const loop = () => {
        if (dead) return;
        if (v.readyState === v.HAVE_ENOUGH_DATA && jsQR()) {
          cv.width = v.videoWidth; cv.height = v.videoHeight;
          const ctx2 = cv.getContext("2d", { willReadFrequently: true });
          ctx2.drawImage(v, 0, 0);
          const img = ctx2.getImageData(0, 0, cv.width, cv.height);
          const code = jsQR()(img.data, cv.width, cv.height);
          if (code) { found(code.data); return; }
        }
        raf = requestAnimationFrame(loop);
      };
      raf = requestAnimationFrame(loop);
    } catch (e) {
      $("#sMsg").textContent = "Camera unavailable — use the image picker below";
    }
  }
  $("#fIn").onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    const img = new Image();
    img.onload = async () => {
      const cv = document.createElement("canvas");
      cv.width = img.width; cv.height = img.height;
      const ctx2 = cv.getContext("2d");
      ctx2.drawImage(img, 0, 0);
      try { await import("/src/lib/jsQR.min.js"); } catch (err) {}
      const code = window.jsQR &&
        window.jsQR(ctx2.getImageData(0, 0, cv.width, cv.height).data, cv.width, cv.height);
      code ? found(code.data) : ($("#sMsg").textContent = "No QR found in that image — try again");
    };
    img.src = URL.createObjectURL(f);
  };
  function found(raw) {
    dead = true; cancelAnimationFrame(raf); stream?.getTracks().forEach((t) => t.stop());
    let vpa = raw;
    try { const u = new URL(raw); vpa = u.searchParams.get("pa") || raw; } catch (e) {}
    renderPay({});                       // fresh pay screen
    setTimeout(async () => {             // auto-verify the scanned VPA
      const inp = $("#vpaIn");
      if (inp) { inp.value = vpa; inp.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" })); }
    }, 60);
  }
  startCam();
}

export async function renderMyQR() {
  setLightBar(false);
  screen.innerHTML = `<div class="screen-panel">
    <div class="pay-head"><div class="back-btn" id="qBack">${I.back}</div>
      <div class="pt">My QR code</div></div>
    <div class="qr-panel">
      <div class="qr-img-card">
        <img src="/api/qr.svg?payload=${encodeURIComponent(state.me.qr_payload)}"
             width="230" height="230" alt="My UPI QR">
        <div style="font-weight:800;margin-top:10px">${esc(state.me.name)}</div>
        <div style="font-family:var(--font-mono);font-size:12px;color:var(--ink-2);margin-top:3px">
          ${esc(state.me.vpa)}</div>
        <div style="font-size:11px;color:var(--ink-3);margin-top:8px">
          Scan to pay me — this QR is real and payable from any UPI app</div>
      </div>
    </div></div>`;
  $("#qBack").onclick = renderHome;
}

/* ============================================================ PROCESSING */
function renderProcessing(txnId) {
  setLightBar(true);
  screen.innerHTML = `<div class="status-panel">
    <div class="st-hero"><div class="spinner"></div>
      <div class="st-title">Processing</div>
      <div class="st-sub">Do not press back. This usually takes a few seconds…</div></div>
  </div>`;
  const t0 = Date.now();
  const iv = setInterval(async () => {
    try {
      const v = await api(`/api/txn/${txnId}`);
      if (!v.processing) { clearInterval(iv); renderStatus(v); }
    } catch (e) {
      if (Date.now() - t0 > 15000) { clearInterval(iv); toast("Payment status unknown"); renderHome(); }
    }
  }, 600);
}

/* ============================================================== S3 STATUS */
function renderStatus(v) {
  setLightBar(true);
  const ok = v.status === "SUCCESS", pend = v.status === "PENDING";
  const hero = ok
    ? `<div class="st-circle okc"><div class="st-inner oki">
         <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"><path d="M4.5 12.5l5 5 10-11"/></svg></div><div class="ring"></div></div>`
    : pend
    ? `<div class="st-circle wtc"><div class="st-inner wti">
         <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 1.8"/></svg></div></div>`
    : `<div class="st-circle badc"><div class="st-inner badi">
         <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></div></div>`;
  const eyebrow = ok ? "PAYMENT SUCCESSFUL" : pend ? "PAYMENT PENDING" : "PAYMENT FAILED";
  const title = ok ? "Payment Successful" : pend ? "Payment Pending" : "Payment Failed";
  const sub = ok
    ? `Paid to ${esc(v.to_name)}`
    : pend
    ? `Usually confirmed within 30 minutes. Money is safe and will be auto-reversed if it fails.`
    : `Money debited but not received by the recipient. It will be auto-reversed within T+1 as per RBI guidelines.`;
  screen.innerHTML = `<div class="status-panel">
    <div class="st-hero">${hero}
      <div class="st-eyebrow" style="color:${ok ? "var(--success)" : pend ? "var(--pending)" : "var(--failure)"}">${eyebrow}</div>
      <div class="st-title">${title}</div>
      <div class="st-amount">₹ ${fmt(v.amount_paise)}</div>
      <div class="st-to">To ${esc(v.to_name)} · <span style="font-family:var(--font-mono);font-size:11px">${esc(v.to_vpa)}</span></div>
    </div>
    ${!ok ? `<div class="st-banner">${pend
      ? "Bank is taking longer than usual (SLA: 30 min). Status will update automatically."
      : "If money is not refunded within 3–5 business days, contact 24×7 Help."}</div>` : ""}
    <div class="receipt">
      <div class="rc-row"><span class="k">UPI Ref No</span><span class="v mono" id="rrnCopy">${esc(v.rrn || "—")}</span></div>
      <div class="rc-row"><span class="k">Date &amp; Time</span><span class="v">${humanTime(v.initiated_at)}</span></div>
      <div class="rc-row"><span class="k">Debited from</span><span class="v">${esc(state.me.bank_display)}</span></div>
      ${!ok && v.app_err_msg ? `<div class="rc-row"><span class="k">Status</span><span class="v" style="color:${pend ? "var(--pending)" : "var(--failure)"}">${esc(v.app_err_msg)}</span></div>` : ""}
    </div>
    <div class="st-actions">
      ${!ok ? `<button class="btn-ai" id="askAI">${I.sparkle}
          <span>Ask Sahayak AI<span class="micro">Resolves in ~2 min · replies in Hindi &amp; English</span></span></button>
        <button class="btn-navy" id="help247">Contact 24×7 Help</button>` : ""}
      <button class="txt-link" id="viewDetail">View transaction details →</button>
      <button class="txt-link" id="doneBtn">Done</button>
    </div></div>`;
  $("#rrnCopy").onclick = () => { navigator.clipboard?.writeText(v.rrn || ""); toast("UPI Ref No copied"); };
  const openAgent = () => renderChat(v.txn_id);
  if (!ok) {
    $("#askAI").onclick = openAgent;
    $("#help247").onclick = () => {           // the human path feels slower
      toast("Connecting to assistant…");
      setTimeout(openAgent, 900);
    };
  }
  $("#viewDetail").onclick = () => renderDetail(v.txn_id);
  $("#doneBtn").onclick = refreshAndHome;
}

async function refreshAndHome() {
  await refresh();
  renderHome();
}
async function refresh() {
  try {
    const [me, list] = await Promise.all([api("/api/me"), api("/api/txn/list?limit=40")]);
    state.me = me; state.history = list.items;
  } catch (e) { /* offline */ }
}

/* =============================================================== S4 DETAIL */
async function renderDetail(txnId) {
  setLightBar(true);
  const v = await api(`/api/txn/${txnId}`);
  screen.innerHTML = `<div class="screen-panel">
    <div class="pay-head" style="background:linear-gradient(160deg,#0E8FDB,#002E6E)">
      <div class="back-btn" id="dBack">${I.back}</div><div class="pt">Transaction details</div></div>
    <div class="st-hero" style="height:190px;background:#fff">
      <div class="st-amount" style="font-size:40px">₹ ${fmt(v.amount_paise)}</div>
      ${statusChip(v.status)}
      <div class="st-to">${esc(v.to_name)}</div></div>
    <div class="receipt">
      <div class="rc-row"><span class="k">UPI Ref No / RRN</span><span class="v mono" id="rrnC2">${esc(v.rrn || "—")}</span></div>
      <div class="rc-row"><span class="k">To VPA</span><span class="v mono" style="font-size:11.5px">${esc(v.to_vpa)}</span></div>
      <div class="rc-row"><span class="k">Date &amp; Time</span><span class="v">${humanTime(v.initiated_at)}</span></div>
      <div class="rc-row"><span class="k">Debited from</span><span class="v">${esc(state.me.bank_display)}</span></div>
      ${v.debit_ts ? `<div class="rc-row"><span class="k">Debited at</span><span class="v">${humanTime(v.debit_ts)}</span></div>` : ""}
      ${v.reversal_initiated_at ? `<div class="rc-row"><span class="k">Reversal initiated</span><span class="v" style="color:var(--pending)">${humanTime(v.reversal_initiated_at)}</span></div>` : ""}
      ${v.reversal_credited_at ? `<div class="rc-row"><span class="k">Reversal credited</span><span class="v" style="color:var(--success)">${humanTime(v.reversal_credited_at)}</span></div>` : ""}
      ${v.fail_code ? `<div class="rc-row"><span class="k">NPCI response code</span><span class="v mono">${esc(v.fail_code)}</span></div>` : ""}
    </div>
    ${v.status !== "SUCCESS" ? `<div class="st-actions">
      <button class="btn-ai" id="askAI2">${I.sparkle}<span>Ask Sahayak AI
        <span class="micro">Payment stuck? Let me handle it</span></span></button></div>` : ""}
    <div style="height:24px"></div></div>`;
  $("#dBack").onclick = renderHome;
  $("#rrnC2").onclick = () => { navigator.clipboard?.writeText(v.rrn || ""); toast("RRN copied"); };
  if (v.status !== "SUCCESS") $("#askAI2").onclick = () => renderChat(txnId);
}

/* ================================================================ S5 CHAT */
/* Customer-facing Sahayak — the REAL AI stack (Gemini on Vertex + backend
   tools + memory), living inside the Paytm app. A button opens it; the
   whole conversation happens here. */
async function renderChat(txnId) {
  setLightBar(false);
  screen.innerHTML = `<div class="chat-panel">
    <div class="chat-head"><div class="back-btn" id="cBack">${I.back}</div>
      <div class="chat-av">🤖</div>
      <div><div class="cn">Sahayak · 24×7 Help</div>
        <div class="cs" id="chatSub">reading your case…</div></div></div>
    <div class="chat-body" id="chatBody"></div>
    <div class="quick" id="quick"></div>
    <div class="chat-in"><input id="chatInput" placeholder="Type your message…">
      <button id="chatSend">Send</button></div>
  </div>`;
  $("#cBack").onclick = renderHome;

  const body = $("#chatBody");
  const add = (html) => { body.insertAdjacentHTML("beforeend", html);
    body.scrollTop = body.scrollHeight; };
  const agentMsg = (html) => add(`<div class="msg agent">${html}</div>`);
  const typing = () => { add(`<div class="typing" id="typ"><i></i><i></i><i></i></div>`);
    body.scrollTop = body.scrollHeight; };
  const killTyping = () => $("#typ")?.remove();

  let caseId = null;
  try {
    const o = await api("/api/saas/agent/open", { method: "POST",
      body: JSON.stringify({ txn_id: txnId }) });
    caseId = o.case_id;
    $("#chatSub").textContent = `case ${caseId.slice(5, 14)} · memory: ${o.memory_mode}`;
    addThink(o.thinking);
    agentMsg(esc(o.opener));
    // convenient starters — but the customer can type anything
    $("#quick").innerHTML =
      `<button class="qchip" data-q="My money was debited but it is not credited">💸 Debited, not credited</button>
       <button class="qchip" data-q="paisa atak gaya hai, kitna time lagega?">🇮🇳 पैसा अटक गया है</button>
       <button class="qchip" data-q="I did not make this payment, is this fraud?">🚨 I didn't make this payment</button>`;
    $("#quick").querySelectorAll("[data-q]").forEach((b) => b.onclick = () => {
      $("#chatInput").value = b.dataset.q; send();
    });
  } catch (e) {
    agentMsg(`⚠️ ${esc(e.message)}`);
  }

  function addThink(steps) {
    if (!steps?.length) return;
    const d = document.createElement("div");
    d.className = "think-card";
    d.innerHTML = `<div class="tc-h">🧠 Sahayak investigated ${steps.length} step(s) ▸</div>
      <div class="tl2">${steps.map((x) => `<div class="tl-row">
        <span class="tn2">${esc(x.tool)}</span><span>${esc(x.detail)}</span></div>`).join("")}</div>`;
    d.onclick = () => d.classList.toggle("open");
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
  }

  async function send() {
    const t = $("#chatInput").value.trim();
    if (!t || !caseId) return;
    $("#chatInput").value = "";
    $("#quick").innerHTML = "";
    add(`<div class="msg user">${esc(t)}</div>`);
    typing();
    $("#chatSend").disabled = true;
    try {
      const r = await api("/api/saas/agent/message", { method: "POST",
        body: JSON.stringify({ case_id: caseId, text: t }) });
      killTyping();
      addThink(r.thinking);
      agentMsg(esc(r.reply));
      $("#chatSub").textContent =
        `case ${caseId.slice(5, 14)} · engine: ${r.engine}`;
    } catch (e) {
      killTyping();
      agentMsg(`⚠️ ${esc(e.message)}`);
    }
    $("#chatSend").disabled = false;
    $("#chatInput").focus();
  }
  $("#chatSend").onclick = send;
  $("#chatInput").onkeydown = (e) => e.key === "Enter" && send();
}

/* =============================================================== S6 PASSBOOK */
function renderHistory() {
  setLightBar(false);
  const groups = {};
  state.history.forEach((t) => {
    const d = new Date(t.initiated_at);
    const now = new Date();
    const key = d.toDateString() === now.toDateString() ? "Today"
      : new Date(now - 864e5).toDateString() === d.toDateString() ? "Yesterday"
      : d.toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
    (groups[key] = groups[key] || []).push(t);
  });
  screen.innerHTML = `<div class="screen-panel">
    <div class="home-header dark">
      <div class="hh-row1"><div class="back-btn" id="hBack">${I.back}</div>
        <div class="wordmark"><b>Balance</b> &amp; History</div>
        <div class="avatar">${esc(state.me.initials)}</div></div>
      <div class="balance-card"><div><div class="cap">UPI BALANCE</div>
        <div class="amt">₹ ${fmt(state.me.balance_paise)}</div>
        <div class="sub">${esc(state.me.bank_display)}</div></div></div>
    </div>
    ${Object.entries(groups).map(([g, items]) => `
      <div class="group-label">${esc(g)}</div>
      <div class="txn-card">${items.map(txnRowHTML).join("")}</div>`).join("") ||
      `<div style="padding:30px;text-align:center;color:var(--ink-3)">No transactions</div>`}
    <div style="height:20px"></div>
    <div class="bottom-nav">
      <div class="bn-item" id="bnH2">${I.home}Home</div>
      <div class="bn-item active">${I.book}Balance</div>
      <div class="bn-fab" id="bnF2"><div class="fab">${I.scan}</div></div>
      <div class="bn-item">💳 Cards</div><div class="bn-item">👤 Profile</div>
    </div></div>`;
  $("#hBack").onclick = $("#bnH2").onclick = renderHome;
  $("#bnF2").onclick = () => renderPay({ scan: true });
  state.history.forEach((t) => $(`.txn-row[data-id="${t.txn_id}"]`)?.addEventListener("click",
    () => renderDetail(t.txn_id)));
}

/* ================================================================ LOGIN */
let loginEpoch = 0;
function renderLogin(err) {
  loginEpoch += 1;
  const myEpoch = loginEpoch;
  setTimeout(() => { if (loginEpoch !== myEpoch) return; }, 0);
  setLightBar(true);
  screen.innerHTML = `<div class="screen-panel" style="background:var(--surface)">
    <div style="display:flex;flex-direction:column;align-items:center;padding:92px 24px 0">
      <div class="wordmark" style="font-size:34px"><span class="p1">pay</span><span class="p2">tm</span></div>
      <div style="font-size:15px;color:var(--ink-2);margin-top:10px;font-weight:600">
        Login to see your balance & transactions</div>
    </div>
    <div style="padding:34px 24px 0">
      <div class="field-lb" style="margin:0 0 6px">Mobile number</div>
      <input class="vpa-input" id="lgMobile" inputmode="numeric" placeholder="98XXXXXXXX"
        autocomplete="off" style="font-family:var(--font-body);font-size:16px">
      <div class="field-lb" style="margin:20px 0 6px">UPI PIN</div>
      <input class="vpa-input" id="lgPin" inputmode="numeric" type="password" maxlength="6"
        placeholder="••••" autocomplete="off" style="font-family:var(--font-body);font-size:16px">
      ${err ? `<div style="color:var(--failure);font-size:12.5px;font-weight:700;margin-top:10px">✕ ${esc(err)}</div>` : ""}
      <button class="paybtn" id="lgBtn" style="width:100%;margin:26px 0 0;display:block">
        🔒 Login Securely</button>
      <div style="margin-top:26px">
        <div class="field-lb" style="margin:0 0 8px">Quick demo login</div>
        <div id="lgProfiles" style="display:flex;flex-direction:column;gap:8px"></div>
      </div>
      <div style="text-align:center;color:var(--ink-3);font-size:11px;margin-top:22px">
        3,001 accounts live in this sandbox · PIN = last 4 digits of the mobile</div>
    </div>
  </div>`;
  const m = $("#lgMobile"), p = $("#lgPin");
  const doLogin = async () => {
    try {
      const r = await api("/api/auth/login", { method: "POST",
        body: JSON.stringify({ mobile: m.value, pin: p.value }) });
      setToken(r.token);
      loginEpoch += 1;                     // cancel any pending login redirect
      state.scenario = "auto";
      await refresh(); renderHome();
      toast(`Welcome, ${r.name.split(" ")[0]} 👋`);
    } catch (e) { renderLogin(e.message); }
  };
  $("#lgBtn").onclick = doLogin;
  p.onkeydown = (e) => e.key === "Enter" && doLogin();
  m.onkeydown = (e) => e.key === "Enter" && p.focus();
  api("/api/auth/profiles").then((r) => {
    $("#lgProfiles").innerHTML = r.items.map((u) =>
      `<div class="qchip" style="text-align:left" data-m="${esc(u.mobile)}" data-p="${esc(u.login_pin)}">
        👤 ${esc(u.name)} · ${esc(u.mobile)}</div>`).join("");
    $("#lgProfiles").querySelectorAll("[data-m]").forEach((b) => b.onclick = () => {
      m.value = b.dataset.m; p.value = b.dataset.p; doLogin();
    });
  }).catch(() => {});
}

/* ============================================================== PROFILE */
function renderProfile() {
  setLightBar(true);
  const me = state.me;
  screen.innerHTML = `<div class="screen-panel" style="background:var(--surface)">
    <div class="pay2-head"><div class="back2" id="prBack">${I.backDark}</div>
      <div class="pt">Profile</div></div>
    <div style="display:flex;flex-direction:column;align-items:center;padding:34px 16px 0">
      <div class="payee-av" style="width:84px;height:84px;font-size:30px">${esc(me.initials)}</div>
      <div style="font-size:20px;font-weight:800;margin-top:14px">${esc(me.name)}</div>
      <div style="font-family:var(--font-mono);font-size:12px;color:var(--ink-2);margin-top:4px">
        ${esc(me.vpa)}</div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <span class="qchip" style="cursor:default">📞 ${esc(me.mobile || "")}</span>
        <span class="qchip" style="cursor:default">🪪 ${esc(me.kyc_tier)} KYC</span>
        <span class="qchip" style="cursor:default">🌐 ${esc(me.preferred_lang)}</span>
      </div>
    </div>
    <div class="receipt" style="margin-top:26px">
      <div class="rc-row"><span class="k">UPI Balance</span>
        <span class="v">₹ ${fmt(me.balance_paise)}</span></div>
      <div class="rc-row"><span class="k">Bank</span>
        <span class="v">${esc(me.bank_display)}</span></div>
    </div>
    <div style="padding:6px 16px">
      <button class="paybtn" id="prQr" style="width:100%;display:block;margin:10px 0">📷 My QR code</button>
      <button class="btn-navy" id="prSwitch" style="width:100%;display:block;margin:10px 0"> Switch User</button>
    </div>
  </div>`;
  $("#prBack").onclick = renderHome;
  $("#prQr").onclick = renderMyQR;
  $("#prSwitch").onclick = () => {
    clearToken();
    renderLogin();
  };
}

/* ============================================================== dev drawer */
function renderDevDrawer() {
  const d = $("#devdrawer");
  const scen = [
    ["auto", "Normal (real probability)"],
    ["success", "Force SUCCESS"],
    ["mode_a", "Force Mode A — fail now (Z5, reversal flying)"],
    ["mode_b_yesterday", "Seed Mode B — pending 31h (yesterday)"],
    ["u30", "Force wrong-PIN decline (U30)"],
  ];
  d.innerHTML = `
    <h4>⚡ Demo controls</h4>
    <div class="sub">scenario for the NEXT payment you make</div>
    ${scen.map(([v, l]) => `<button data-s="${v}" class="${state.scenario === v ? "on" : ""}">${l}</button>`).join("")}
    <div class="sub" style="margin-top:12px">Mode C shortcut</div>
    <button id="devC">Pre-fill ₹19,000 → fraud UPI ID</button>
    <div class="sub" style="margin-top:12px">open agent on seeded cases</div>
    <div id="devCases"></div>
    <div class="warn">Agent replies are scripted previews until the Gemini loop lands (triage verdicts are real).</div>`;
  d.querySelectorAll("[data-s]").forEach((b) => b.onclick = () => {
    state.scenario = b.dataset.s; renderDevDrawer(); toast(`Scenario: ${b.dataset.s}`);
  });
  $("#devC").onclick = () => {
    state.prefill = { vpa: "quickloan.help@ybl", amount_paise: 1900000 };
    d.classList.add("hidden");
    renderPay({});
  };
  api("/api/dev/demo_cases").then((r) => {
    $("#devCases").innerHTML = r.items.map((t) =>
      `<button data-id="${t.txn_id}">🤖 ${t.status} ₹${fmt(t.amount_paise)} → ${esc(t.beneficiary_vpa)}</button>`).join("");
    $("#devCases").querySelectorAll("[data-id]").forEach((b) =>
      b.onclick = () => { d.classList.add("hidden"); renderChat(+b.dataset.id); });
  });
}
$("#devtab").onclick = () => {
  $("#devdrawer").classList.toggle("hidden");
  if (!$("#devdrawer").classList.contains("hidden")) renderDevDrawer();
};

/* ================================================================ bootstrap */
if (window.__sahayakBooted) {
  // a second module instance (watchdog/dynamic import) must not double-boot
} else {
window.__sahayakBooted = true;
(async function init() {
  if (!getToken()) { renderLogin(); return; }
  try {
    await refresh();
    renderHome();
  } catch (e) {
    if (!getToken()) return;
    screen.innerHTML = `<div style="padding:60px 24px;text-align:center;color:var(--ink-2)">
      <div style="font-size:34px">📡</div><h3 style="margin:12px 0 6px">Can't reach the backend</h3>
      <div style="font-size:13px">Start it with:<br><code style="font-family:var(--font-mono)">
      cd backend && uvicorn app:app --port 8000</code><br><br>${esc(e.message)}</div></div>`;
  }
})();
}
