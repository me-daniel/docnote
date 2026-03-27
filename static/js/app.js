// DoctorTalk frontend — talks to FastAPI backend at /api/*
// No Anthropic API key needed here — all AI calls go through the server

const API = {
  async get(path) {
    const r = await fetch(`/api${path}`);
    if (!r.ok) throw new Error(`GET ${path} failed: ${r.status}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `POST ${path} failed: ${r.status}`);
    }
    return r.json();
  },
};

const THEME_KEY = "doctortalk-theme";
const DEFAULT_ANALYTICS_PATIENT = "Uwe";

function syncThemeBtn() {
  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  const t = document.documentElement.getAttribute("data-theme") || "dark";
  btn.textContent = t === "light" ? "\u{1F319}" : "\u2600";
  const label = t === "light" ? "Switch to dark mode" : "Switch to light mode";
  btn.setAttribute("aria-label", label);
  btn.title = label;
}

function initTheme() {
  const legacy = localStorage.getItem("medbridge-theme");
  if (legacy && !localStorage.getItem(THEME_KEY)) {
    localStorage.setItem(THEME_KEY, legacy);
  }
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") {
    document.documentElement.setAttribute("data-theme", saved);
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
    document.documentElement.setAttribute("data-theme", "light");
  } else {
    document.documentElement.setAttribute("data-theme", "dark");
  }
  syncThemeBtn();
  const btn = document.getElementById("themeToggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || "dark";
      const next = cur === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem(THEME_KEY, next);
      syncThemeBtn();
    });
  }
}

// ── State ──
let curPt = null, wData = [], flagged = [], selfU = 0;
let sessStart = null, hoverStart = {}, hoverTimes = {};
let selLv = 3, autoMode = false, anPt = null;
let pendingText = null, pendingPatientId = null;
const defCache = {};

const LV = {
  1: "Very Easy — Grade 3",
  2: "Easy — Grade 5",
  3: "Normal — Grade 7",
  4: "Advanced — Grade 9",
  5: "Complex — Clinical",
};

const MED = new Set(["cardiomyopathy","ejection","fraction","myocardial","infarction","dyspnea","copd",
  "obstructive","pulmonary","bronchodilator","spirometry","prednisolone","salbutamol","nebulization",
  "amoxicillin","clavulanate","exacerbation","corticosteroid","antibiotic","pulmonology","ventilatory",
  "systolic","diastolic","furosemide","lisinopril","diuretic","echocardiography","hypertension",
  "arrhythmia","atherosclerosis","angioplasty","tachycardia","bradycardia","thrombosis","embolism"]);

// ── Nav ──
function go(v) {
  document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".nav-tab").forEach(x => x.classList.remove("active"));
  document.getElementById(v + "View").classList.add("active");
  ["writer", "patient", "analytics"].forEach((n, i) => {
    if (n === v) document.querySelectorAll(".nav-tab")[i].classList.add("active");
  });
  if (v === "analytics") renderAn();
  if (v === "patient") setupPat();
}

// ── Patient selector ──
async function initPsel() {
  const sel = document.getElementById("psel");
  const patients = await API.get("/patients");
  sel.innerHTML = '<option value="">— Select patient —</option>';
  patients.forEach(p => {
    const o = document.createElement("option");
    o.value = p.id; o.textContent = p.name; sel.appendChild(o);
  });
  if (curPt) sel.value = curPt;
  else {
    const uwe = patients.find(p => p.name === DEFAULT_ANALYTICS_PATIENT);
    if (uwe) {
      sel.value = uwe.id;
      curPt = uwe.id;
      await onPChange();
    }
  }
}

async function addPt() {
  const n = prompt("Patient name:"); if (!n?.trim()) return;
  const p = await API.post("/patients", { name: n.trim() });
  await initPsel();
  document.getElementById("psel").value = p.id;
  onPChange();
}

async function onPChange() {
  curPt = parseInt(document.getElementById("psel").value) || null;
  if (!curPt) {
    document.getElementById("profileCard").innerHTML = '<div style="font-size:11px;color:var(--dm)">Select a patient to load their profile.</div>';
    document.getElementById("chalWrap").style.display = "none";
    document.getElementById("insightWrap").style.display = "none";
    return;
  }
  const p = await API.get(`/patients/${curPt}`);
  renderProfile(p);
  loadChalWords(curPt);
  loadInsight(curPt, p);
}

function renderProfile(p) {
  const lv = p.recommended_level;
  const badges = p.session_count
    ? `<span class="pb lv">Rec. level ${lv}/5</span>`
    : '<span class="pb nw">New patient</span>';
  const flagBadge = p.top_flagged.length
    ? `<span class="pb wn">⚑ ${p.top_flagged.join(", ")}</span>` : "";
  document.getElementById("profileCard").innerHTML = `
    <div class="p-row">
      <div class="p-av">${p.name[0].toUpperCase()}</div>
      <div>
        <div class="p-name">${p.name}</div>
        <div class="p-sub">${p.session_count} session${p.session_count !== 1 ? "s" : ""} · ${p.avg_comprehension != null ? "Avg " + p.avg_comprehension + "% comp." : "No data yet"}</div>
      </div>
    </div>
    <div class="p-badges">${badges}<span class="pb se">${p.session_count} sessions</span>${flagBadge}</div>`;

  if (autoMode) {
    selLv = lv;
    document.getElementById("dsl").value = lv;
    updSl(lv, false);
  }
}

async function loadChalWords(patientId) {
  try {
    const words = await API.get(`/patients/${patientId}/challenging-words`);
    const chalWrap = document.getElementById("chalWrap");
    if (!words.length) { chalWrap.style.display = "none"; return; }
    const max = words[0].score;
    const colors = ["#e03c3c", "#f4894a", "#f4c242", "#52c48a"];
    document.getElementById("chalPanel").innerHTML = words.map((w, i) => {
      const pct = Math.round(w.score / max * 100);
      const c = i === 0 ? colors[0] : i <= 1 ? colors[1] : i <= 3 ? colors[2] : colors[3];
      const badge =
        w.flagged ? '<span class="chal-badge fl">flagged</span>'
        : w.slow_read ? '<span class="chal-badge pr">slow read</span>'
        : "";
      return `<div class="chal-word-row">
        <div class="chal-word" title="${w.word}">${w.word}</div>
        <div class="chal-bar-bg"><div class="chal-bar-fg" style="width:${pct}%;background:${c}"></div></div>
        <div class="chal-badge-cell">${badge}</div>
        <div class="chal-n">${w.score}</div>
      </div>`;
    }).join("");
    chalWrap.style.display = "block";
  } catch { document.getElementById("chalWrap").style.display = "none"; }
}

async function loadInsight(patientId, p) {
  document.getElementById("insightWrap").style.display = "block";
  document.getElementById("insightSpin").style.display = "inline";
  document.getElementById("insightText").textContent = "";
  document.getElementById("predWords").innerHTML = "";
  try {
    const data = await API.post("/patient-insight", { patient_id: patientId });
    document.getElementById("insightText").textContent = data.insight;
    const pw = document.getElementById("predWords");
    if (data.predicted.length) {
      pw.innerHTML = '<div class="pred-lbl">Predicted difficult words:</div>';
      data.predicted.forEach(({ word, prev_flagged }) => {
        pw.innerHTML += `<span class="pred ${prev_flagged ? "pf" : ""}">${prev_flagged ? "⚑ " : ""}${word}</span>`;
      });
    }
  } catch (e) {
    document.getElementById("insightText").textContent = "Could not load patient insight.";
  }
  document.getElementById("insightSpin").style.display = "none";
}

// ── Slider ──
function setMode(mode) {
  autoMode = mode === "auto";
  document.getElementById("autoModeBtn").classList.toggle("active", autoMode);
  document.getElementById("manualModeBtn").classList.toggle("active", !autoMode);
  document.getElementById("dsl").disabled = autoMode;
  document.getElementById("autoReason").style.display = "none";
  if (autoMode && curPt) {
    API.get(`/patients/${curPt}`).then(p => {
      selLv = p.recommended_level;
      document.getElementById("dsl").value = selLv;
      updSl(selLv, false);
      document.getElementById("autoReason").textContent = `Auto-set based on ${p.session_count} sessions (avg ${p.avg_comprehension}% comp.)`;
      document.getElementById("autoReason").style.display = "block";
    });
  }
}
function updSl(v, manual = true) {
  selLv = parseInt(v);
  document.getElementById("slCur").textContent = LV[v];
  if (manual && autoMode) setMode("manual");
}

// ── Writer ──
function loadEx() {
  document.getElementById("medIn").value = `The patient is a 67-year-old male presenting with acute exacerbation of chronic obstructive pulmonary disease (COPD). Spirometry indicates a post-bronchodilator FEV1/FVC ratio of 0.65, consistent with moderate obstructive ventilatory defect. Initiate short-acting beta-2 agonist (salbutamol 2.5mg via nebulization q4h), systemic corticosteroids (prednisolone 40mg PO OD x 5 days), and empiric antibiotic therapy with amoxicillin-clavulanate 875/125mg PO BID for suspected bacterial exacerbation. Monitor SpO2, target 88–92%. Arrange pulmonology follow-up in 2 weeks post-discharge.`;
}

async function doSimplify() {
  const txt = document.getElementById("medIn").value.trim();
  if (!txt) { alert("Enter clinical text first."); return; }

  const btn = document.getElementById("simpBtn");
  btn.disabled = true; btn.innerHTML = "⟳ Processing...";
  document.getElementById("ldS").style.display = "block";
  document.getElementById("outPh").style.color = "";
  ["outPh", "outEd", "appRow", "scRow", "appBanner", "simSec"].forEach(id => {
    document.getElementById(id).style.display = "none";
  });

  try {
    const data = await API.post("/simplify", {
      text: txt,
      difficulty_level: selLv,
      patient_id: curPt || null,
    });
    document.getElementById("ldS").style.display = "none";
    const ed = document.getElementById("outEd");
    ed.value = data.simplified; ed.style.display = "block";

    // Scores
    document.getElementById("grS").textContent = Math.max(0, data.grade_level);
    document.getElementById("grS").className = "sc-v " + (data.grade_level <= 7 ? "good" : data.grade_level <= 10 ? "warn" : "bad");
    document.getElementById("hwS").textContent = data.hard_word_pct + "%";
    document.getElementById("hwS").className = "sc-v " + (data.hard_word_pct <= 15 ? "good" : data.hard_word_pct <= 25 ? "warn" : "bad");
    document.getElementById("scRow").style.display = "flex";

    document.getElementById("simSec").style.display = "block";
    await doCheckSim(txt, data.simplified);
  } catch (e) {
    document.getElementById("ldS").style.display = "none";
    document.getElementById("outPh").style.display = "block";
    document.getElementById("outPh").textContent = "Error: " + e.message;
    document.getElementById("outPh").style.color = "#ff8080";
  }
  btn.disabled = false; btn.innerHTML = "✦ Simplify with AI";
}

async function doCheckSim(orig, simp) {
  const head = document.getElementById("simHead");
  head.className = "sim-head checking";
  document.getElementById("simPct").textContent = "";
  document.getElementById("simVerdictLine").textContent = "";
  document.getElementById("simBar").style.width = "0%";
  document.getElementById("simBody").innerHTML = '<div class="spin-w"><div class="spinner"></div>Analysing sentences via AI...</div>';
  try {
    const data = await API.post("/check-similarity", { original: orig, simplified: simp });
    renderSentenceDiff(data);
  } catch { renderSimErr(); }
}

function renderSentenceDiff(data) {
  const sc = data.overall_score ?? 0;
  const cls = sc >= 85 ? "pass" : sc >= 68 ? "caution" : "fail";
  document.getElementById("simHead").className = "sim-head " + cls;
  document.getElementById("simPct").textContent = sc + "%";
  document.getElementById("simVerdictLine").textContent = data.verdict || "";
  document.getElementById("simHead").querySelector(".sim-label").textContent =
    sc >= 85 ? "✓ Meaning Preserved" : sc >= 68 ? "⚠ Minor Drift" : "✗ Meaning at Risk";
  const bar = document.getElementById("simBar");
  bar.style.width = sc + "%";
  bar.style.background = sc >= 85 ? "var(--dg)" : sc >= 68 ? "var(--dw)" : "#ff6b6b";
  const pairs = data.pairs || [];
  document.getElementById("simBody").innerHTML = pairs.map(p => {
    const sc2 = p.status === "good" ? "diff-good" : p.status === "lost" ? "diff-lost" : "diff-changed";
    const simpHtml = p.simp
      ? `<div class="diff-simp-label">Simplified</div><div class="diff-simp">${p.simp}</div>`
      : `<div class="diff-simp" style="color:#ff8080;font-style:italic">⚠ Not found in simplified version</div>`;
    return `<div class="diff-pair ${sc2}">
      <div class="diff-orig-label">Original</div>
      <div class="diff-orig">${p.orig}</div>
      ${simpHtml}
      ${p.note ? `<div style="font-size:9px;color:var(--dm);margin-top:3px;font-style:italic">${p.note}</div>` : ""}
    </div>`;
  }).join("");
  const ab = document.getElementById("appBtn");
  document.getElementById("appRow").style.display = "flex";
  if (sc < 68) { ab.disabled = true; ab.textContent = "✗ Cannot Approve"; }
  else if (sc < 85) { ab.disabled = false; ab.style.background = "#b86e1a"; ab.textContent = "⚠ Approve with Caution"; }
  else { ab.disabled = false; ab.style.background = ""; ab.textContent = "✓ Approve & Send to Patient"; }
}

function renderSimErr() {
  document.getElementById("simHead").className = "sim-head caution";
  document.getElementById("simHead").querySelector(".sim-label").textContent = "Check unavailable";
  document.getElementById("simBody").innerHTML = '<div style="padding:10px 12px;font-size:11px;color:var(--dm)">Review manually before approving.</div>';
  document.getElementById("appRow").style.display = "flex";
}

function doApprove() {
  const txt = document.getElementById("outEd").value.trim(); if (!txt) return;
  pendingText = txt; pendingPatientId = curPt;
  document.getElementById("appRow").style.display = "none";
  document.getElementById("appBanner").style.display = "block";
  setTimeout(() => go("patient"), 700);
}

// ── Patient ──
function setupPat() {
  if (!pendingText) return;
  const name = document.getElementById("psel").options[document.getElementById("psel").selectedIndex]?.text || "";
  document.getElementById("patGreet").textContent = name && name !== "— Select patient —" ? `Hello, ${name.split(" ")[0]} 👋` : "Hello 👋";
  wData = []; flagged = []; selfU = 0; hoverStart = {}; hoverTimes = {}; sessStart = Date.now();
  document.getElementById("wsState").style.display = "none";
  document.getElementById("wCont").style.display = "block";
  document.getElementById("patHint").style.display = "none";
  document.getElementById("checkupWrap").style.display = "none";
  document.getElementById("tyWrap").style.display = "none";
  renderWs(pendingText);
  simProg();
}

function diffLv(w) {
  const c = w.toLowerCase().replace(/[^a-z]/g, "");
  if (!c || c.length <= 2) return 0;
  if (MED.has(c)) return 4;
  const s = syl(c);
  if (s >= 4) return 3; if (s === 3) return 2; if (s === 2 && c.length > 6) return 1; return 0;
}
function syl(w) {
  w = w.toLowerCase().replace(/[^a-z]/g, "");
  if (!w) return 0; if (w.length <= 3) return 1;
  w = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, "").replace(/^y/, "");
  const m = w.match(/[aeiouy]{1,2}/g); return m ? m.length : 1;
}

function renderWs(text) {
  const cont = document.getElementById("wCont"); cont.innerHTML = "";
  document.getElementById("patHint").style.display = "block";
  text.split(/(\s+)/).forEach(tok => {
    if (/^\s+$/.test(tok)) { cont.appendChild(document.createTextNode(tok)); return; }
    const raw = tok.replace(/[^a-zA-Z]/g, ""), diff = raw ? diffLv(raw) : 0, idx = wData.length;
    wData.push({ word: tok, clean: raw.toLowerCase(), diff, sel: false, idx });
    const span = document.createElement("span");
    span.className = "w" + (diff > 0 ? " d" + diff : "");
    span.dataset.idx = idx; span.textContent = tok;
    const tipLabels = ["", "Easy word", "Moderate word", "Difficult word", "Medical term"];
    if (diff >= 1) span.setAttribute("data-tip", tipLabels[diff]);
    span.addEventListener("click", () => {
      const e = wData[span.dataset.idx];
      e.sel = !e.sel; span.classList.toggle("sel", e.sel);
      if (e.sel && e.clean && !flagged.includes(e.clean)) flagged.push(e.clean);
      else if (!e.sel) flagged = flagged.filter(w => w !== e.clean);
      if (e.sel && e.clean) showDefPopup(e.clean, span);
      else closeDefPopup();
    });
    span.addEventListener("mouseenter", () => { hoverStart[idx] = Date.now(); });
    span.addEventListener("mouseleave", () => {
      if (hoverStart[idx]) { hoverTimes[idx] = (hoverTimes[idx] || 0) + (Date.now() - hoverStart[idx]); delete hoverStart[idx]; }
    });
    cont.appendChild(span);
  });
}

async function showDefPopup(word, anchorEl) {
  const popup = document.getElementById("defPopup");
  document.getElementById("defWord").textContent = word;
  document.getElementById("defPos").textContent = "";
  document.getElementById("defText").innerHTML = '<div class="def-loading"><div class="def-spinner"></div>Looking up...</div>';
  const rect = anchorEl.getBoundingClientRect();
  let top = rect.bottom + 8, left = rect.left;
  if (left + 290 > window.innerWidth) left = window.innerWidth - 298;
  if (top + 160 > window.innerHeight) top = rect.top - 170;
  popup.style.top = top + "px"; popup.style.left = left + "px";
  popup.style.display = "block";
  try {
    if (!defCache[word]) defCache[word] = await API.post("/define", { word });
    const d = defCache[word];
    document.getElementById("defPos").textContent = d.pos || "";
    document.getElementById("defText").textContent = d.plain || "Definition not available.";
  } catch { document.getElementById("defText").textContent = "Definition unavailable."; }
}
function closeDefPopup() { document.getElementById("defPopup").style.display = "none"; }
document.addEventListener("click", e => {
  if (!e.target.closest(".def-popup") && !e.target.closest(".w")) closeDefPopup();
});

function simProg() {
  let p = 0;
  const iv = setInterval(() => {
    p = Math.min(p + Math.random() * 6 + 2, 100);
    if (p >= 100) {
      clearInterval(iv);
      wData.forEach((w, i) => { if (!hoverTimes[i]) hoverTimes[i] = 90 + w.diff * 85 + Math.random() * 110; });
      document.getElementById("checkupWrap").style.display = "block";
    }
  }, 180);
}

function selU(btn, lv) {
  document.querySelectorAll(".copt").forEach(b => b.classList.remove("sel"));
  btn.classList.add("sel"); selfU = lv;
  setTimeout(() => {
    document.getElementById("checkupWrap").style.display = "none";
    document.getElementById("tyWrap").style.display = "block";
    saveSession();
  }, 500);
}

async function saveSession() {
  if (!pendingPatientId) return;
  const rt = Math.round((Date.now() - sessStart) / 1000);
  const hc = wData.filter(w => w.diff >= 3).length;
  const hr = hc / Math.max(wData.filter(w => w.clean).length, 1);
  const sb = selfU ? (selfU - 1) * 9 : 0;
  const comp = Math.round(Math.max(28, Math.min(97, 90 - hr * 95 + sb - flagged.length * 3)));

  const wf = {}, ht = {};
  wData.forEach((w, i) => {
    if (w.diff >= 2 && w.clean) {
      wf[w.clean] = (wf[w.clean] || 0) + 1;
      ht[w.clean] = (ht[w.clean] || 0) + (hoverTimes[i] || 0);
    }
  });

  try {
    await API.post("/sessions", {
      patient_id: pendingPatientId,
      comprehension_score: comp,
      read_time_seconds: rt,
      self_understanding: selfU,
      difficulty_level: selLv,
      flagged_words: [...flagged],
      word_frequencies: wf,
      hover_times: ht,
    });
    pendingText = null; pendingPatientId = null;
  } catch (e) { console.error("Failed to save session:", e); }
}

// ── Analytics ──
let anPtId = null;

async function renderAn() {
  const patients = await API.get("/patients");
  const tabs = document.getElementById("anTabs"); tabs.innerHTML = "";
  if (!patients.length) {
    document.getElementById("anBody").innerHTML = '<div class="no-data"><div class="ei">◎</div>No patients yet.</div>';
    return;
  }
  patients.forEach(p => {
    const b = document.createElement("button");
    b.className = "an-ptab" + (p.id === anPtId ? " active" : "");
    b.textContent = p.name + (p.session_count ? ` (${p.session_count})` : "");
    b.onclick = () => { anPtId = p.id; renderAn(); };
    tabs.appendChild(b);
  });
  if (!anPtId) {
    const uwe = patients.find(p => p.name === DEFAULT_ANALYTICS_PATIENT);
    anPtId = uwe ? uwe.id : patients[0].id;
  }
  renderPtAn(anPtId);
}

async function renderPtAn(pid) {
  const body = document.getElementById("anBody");
  const [p, analytics] = await Promise.all([API.get(`/patients/${pid}`), API.get(`/patients/${pid}/analytics`)]);
  if (!analytics.session_count) {
    body.innerHTML = `<div class="no-data"><div class="ei">◎</div><strong style="color:var(--at)">${p.name}</strong><br>No sessions yet.</div>`;
    return;
  }

  const { avg_comprehension: ac, avg_read_time: at, comprehension_trend: trend,
          recommended_level: lv, flagged_word_freq: topF, word_frequencies: topW,
          hover_times: topH, sessions: ss } = analytics;

  const loopItems = buildFeedbackLoop(ac, trend, topF, ss, lv);

  body.innerHTML = `
  <div class="an-card s2">
    <div class="an-ch"><span class="an-ct">Overview — ${p.name}</span><span style="font-size:8px;color:var(--am);font-family:'DM Mono',monospace">${analytics.session_count} sessions</span></div>
    <div class="an-cb"><div class="an-3met">
      <div class="an-met"><div class="an-mv" style="color:${ac>=75?"#52c48a":ac>=55?"#f4a261":"#ff6b6b"}">${ac}%</div><div class="an-ml">Avg comprehension</div></div>
      <div class="an-met"><div class="an-mv">${at}s</div><div class="an-ml">Avg read time</div></div>
      <div class="an-met"><div class="an-mv" style="color:var(--aa)">${lv}/5</div><div class="an-ml">Rec. level</div></div>
    </div></div>
  </div>
  <div class="an-card s2">
    <div class="an-ch"><span class="an-ct">✦ Feedback loop — what to improve next time</span><span style="font-size:8px;color:${trend>=0?"#52c48a":"#ff6b6b"};font-family:'DM Mono',monospace">${trend>=0?"▲":"▼"} ${Math.abs(trend)}% trend</span></div>
    <div class="an-cb"><div class="feedback-loop">${loopItems}</div></div>
  </div>
  <div class="an-card">
    <div class="an-ch"><span class="an-ct">Comprehension over sessions</span></div>
    <div class="an-cb an-cb-chart"><canvas class="trend" id="trC" height="110"></canvas></div>
  </div>
  <div class="an-card">
    <div class="an-ch"><span class="an-ct">Words patient flagged as difficult</span></div>
    <div class="an-cb an-cb-chart"><div class="freq-list" id="flList">${topF.length?"":"<div style='font-size:10px;color:var(--am)'>No words flagged yet.</div>"}</div></div>
  </div>
  <div class="an-card">
    <div class="an-ch"><span class="an-ct">Fixation time by word</span><span style="font-size:8px;color:var(--am);font-family:'DM Mono',monospace">eye tracking proxy</span></div>
    <div class="an-cb an-cb-chart"><canvas class="hmap" id="hmC" height="85"></canvas></div>
  </div>
  <div class="an-card">
    <div class="an-ch"><span class="an-ct">Session history</span></div>
    <div class="an-cb"><div class="sess-list" id="sesList"></div></div>
  </div>
  <div class="an-card s2">
    <div class="an-ch"><span class="an-ct">✦ AI writing recommendations</span></div>
    <div class="an-cb"><div class="ai-sum" id="aiSum">
      <div class="ai-sum-t">✦ Generating...</div>
      <div class="spin-w"><div class="spinner"></div></div>
    </div></div>
  </div>`;

  setTimeout(() => {
    drawTrend(ss); drawHmap(topH); drawFlagList(topF); drawSessList(ss);
    loadAiSum(pid);
  }, 40);
}

function buildFeedbackLoop(ac, trend, topF, ss, lv) {
  const items = [];
  const topWords = topF.slice(0, 3).map(([w]) => w);
  const lastSelf = ss[ss.length - 1]?.self_understanding || 0;
  const selfLabels = ["", "Not at all", "A little", "Mostly", "Fully"];
  if (ac < 60) items.push({ cls: "bad", text: `Comprehension is low (${ac}%) — use Very Easy or Easy level next time` });
  else if (ac < 75) items.push({ cls: "warn", text: `Comprehension is moderate (${ac}%) — reduce jargon and sentence length` });
  else items.push({ cls: "good", text: `Comprehension is good (${ac}%) — current level is working well` });
  if (trend > 10) items.push({ cls: "good", text: `Improving — comprehension rose ${trend}% across sessions` });
  else if (trend < -10) items.push({ cls: "bad", text: `Declining — comprehension dropped ${Math.abs(trend)}%, reconsider difficulty` });
  if (topWords.length) items.push({ cls: "warn", text: `Avoid or define these words next time: ${topWords.join(", ")}` });
  if (lastSelf <= 2 && lastSelf > 0) items.push({ cls: "bad", text: `Patient self-reported "${selfLabels[lastSelf]}" — use simpler language` });
  else if (lastSelf >= 3) items.push({ cls: "good", text: `Patient self-reported "${selfLabels[lastSelf]}" — maintain this approach` });
  items.push({ cls: "", text: `Recommended level for next message: ${LV[lv]}` });
  return items.map(i => `<div class="fl-item ${i.cls}">${i.text}</div>`).join("");
}

async function loadAiSum(pid) {
  try {
    const data = await API.post("/analytics-summary", { patient_id: pid });
    document.getElementById("aiSum").innerHTML = `
      <div class="ai-sum-t">✦ AI Profile</div>
      <div class="ai-sum-summary">${data.summary}</div>
      ${data.recommendations.map(b => `<div class="sug">${b}</div>`).join("")}`;
  } catch {
    document.getElementById("aiSum").innerHTML = '<div class="ai-sum-t">✦ Summary unavailable</div>';
  }
}

// Shared plot inset with drawHmap (matches Y-axis gutter in drawTrend)
const AN_CHART_PAD = { t: 12, r: 12, b: 20, l: 28 };

function drawTrend(ss) {
  const cv = document.getElementById("trC"); if (!cv) return;
  const dpr = window.devicePixelRatio || 1, W = cv.parentElement.clientWidth;
  cv.width = W * dpr; cv.height = 110 * dpr; cv.style.width = W + "px"; cv.style.height = "110px";
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
  const pad = { ...AN_CHART_PAD }, cw = W - pad.l - pad.r, ch = 110 - pad.t - pad.b;
  const scores = ss.map(s => s.comprehension_score || 0);
  ctx.strokeStyle = "rgba(255,255,255,.05)"; ctx.lineWidth = 0.5;
  [0, 25, 50, 75, 100].forEach(v => {
    const y = pad.t + ch - (v / 100) * ch;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y); ctx.stroke();
    ctx.fillStyle = "rgba(212,208,202,.25)"; ctx.font = "7px DM Mono,monospace"; ctx.textAlign = "right";
    ctx.fillText(v + "%", pad.l - 2, y + 3);
  });
  if (scores.length > 1) {
    const gr = ctx.createLinearGradient(0, pad.t, 0, pad.t + ch);
    gr.addColorStop(0, "rgba(167,139,250,.25)"); gr.addColorStop(1, "rgba(167,139,250,.02)");
    ctx.beginPath();
    scores.forEach((s, i) => { const x = pad.l + (i / (scores.length - 1)) * cw, y = pad.t + ch - (s / 100) * ch; i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
    ctx.lineTo(pad.l + cw, pad.t + ch); ctx.lineTo(pad.l, pad.t + ch); ctx.closePath(); ctx.fillStyle = gr; ctx.fill();
    ctx.beginPath(); ctx.strokeStyle = "#a78bfa"; ctx.lineWidth = 1.5;
    scores.forEach((s, i) => { const x = pad.l + (i / (scores.length - 1)) * cw, y = pad.t + ch - (s / 100) * ch; i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); }); ctx.stroke();
    scores.forEach((s, i) => { const x = pad.l + (i / (scores.length - 1)) * cw, y = pad.t + ch - (s / 100) * ch; ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fillStyle = s >= 75 ? "#52c48a" : s >= 55 ? "#f4a261" : "#ff6b6b"; ctx.fill(); });
  }
  ctx.fillStyle = "rgba(212,208,202,.25)"; ctx.font = "7px DM Mono,monospace"; ctx.textAlign = "center";
  ss.forEach((s, i) => { const x = scores.length === 1 ? pad.l + cw / 2 : pad.l + (i / (scores.length - 1)) * cw; ctx.fillText("S" + (i + 1), x, 110 - pad.b + 11); });
}

function drawHmap(topH) {
  const cv = document.getElementById("hmC"); if (!cv || !topH.length) return;
  const dpr = window.devicePixelRatio || 1, W = cv.parentElement.clientWidth;
  cv.width = W * dpr; cv.height = 85 * dpr; cv.style.width = W + "px"; cv.style.height = "85px";
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
  const padL = AN_CHART_PAD.l, padR = AN_CHART_PAD.r;
  ctx.fillStyle = "rgba(255,255,255,.02)"; ctx.fillRect(0, 0, W, 85);
  const max = topH[0][1], n = topH.length, gap = 3;
  const innerW = W - padL - padR - (n - 1) * gap;
  const bw = Math.max(4, Math.floor(innerW / n));
  topH.forEach(([w, t], i) => {
    const x = padL + i * (bw + gap), int = t / max, bh = 10 + int * 55;
    ctx.fillStyle = `rgba(${Math.round(int*210)},${Math.round((1-int)*150)},70,${0.4+int*.5})`;
    ctx.beginPath(); ctx.roundRect(x, 85 - bh - 16, bw, bh, 2); ctx.fill();
    ctx.fillStyle = "rgba(212,208,202,.5)"; ctx.font = "7px DM Mono,monospace"; ctx.textAlign = "center";
    ctx.fillText(w.length > 9 ? w.slice(0, 8) + "…" : w, x + bw / 2, 83);
    ctx.fillStyle = "rgba(212,208,202,.3)"; ctx.font = "6px DM Mono,monospace";
    ctx.fillText(Math.round(t / 100) / 10 + "s", x + bw / 2, 85 - bh - 19);
  });
}

function drawFlagList(topF) {
  const list = document.getElementById("flList"); if (!list || !topF.length) return;
  const max = topF[0][1], cs = ["#e03c3c", "#f4894a", "#f4c242", "#52c48a"];
  list.innerHTML = topF.map(([w, n], i) => {
    const pct = Math.round(n / max * 100), c = i === 0 ? cs[0] : i <= 1 ? cs[1] : i <= 3 ? cs[2] : cs[3];
    return `<div class="fr-row"><div class="fr-dot" style="background:${c}"></div><div class="fr-word">${w}</div><div class="fr-bg"><div class="fr-fg" style="width:${pct}%;background:${c}"></div></div><div class="fr-flag">✦</div><div class="fr-n">×${n}</div></div>`;
  }).join("");
}

function drawSessList(ss) {
  const list = document.getElementById("sesList"); if (!list) return;
  const lbs = ["", "Not at all", "A little", "Mostly", "Fully"];
  list.innerHTML = [...ss].reverse().map((s, i) => {
    const n = ss.length - i, c = s.comprehension_score >= 75 ? "#52c48a" : s.comprehension_score >= 55 ? "#f4a261" : "#ff6b6b";
    return `<div class="sess-r"><div class="sess-n">S${n}</div><div class="sess-d">${s.date} · ${s.read_time_seconds}s · Lv${s.difficulty_level} · ${lbs[s.self_understanding] || "—"}</div><div class="sess-s" style="color:${c}">${s.comprehension_score}%</div></div>`;
  }).join("");
}

// ── Init ──
(async function init() {
  initTheme();
  await initPsel();
})();
