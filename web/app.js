/* Atif Assistant PWA client */

const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const mic = document.getElementById("mic");
const statusline = document.getElementById("statusline");
const dot = document.getElementById("dot");

let session = localStorage.getItem("atif-assistant.session") || null;

// Apply the cached theme before first paint to avoid a flash of dark on light.
if (localStorage.getItem("atif-assistant.theme") === "light") {
  document.documentElement.setAttribute("data-theme", "light");
}

const ROUTE_LABEL = {
  ask: "ANSWERED",
  challenge: "CHALLENGED",
  decide: "DECIDED",
};

/* ------------------------------------------------------------ rendering */

function addUser(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble"></div>`;
  el.querySelector(".bubble").textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

function labelize(text) {
  // NOTE: with a global regex, String.match() returns only full matches and
  // capture groups come back undefined. exec() is required to read m[1].
  const re = /\[(FACT|INFERENCE|ASSUMPTION|UNKNOWN|PREDICTION)\]/gi;
  const lines = text.split("\n");
  const out = [];
  let labelled = false;

  lines.forEach((line, i) => {
    re.lastIndex = 0;
    const m = re.exec(line);
    if (!m || !m[1]) {
      // Preserve unlabelled text so nothing is silently dropped.
      if (line.trim()) out.push(document.createTextNode(line));
      return;
    }
    labelled = true;
    if (i > 0) out.push(document.createElement("br"));
    const span = document.createElement("span");
    span.className = `lbl ${m[1].toUpperCase()}`;
    span.textContent = m[1].toUpperCase();
    out.push(span);
    out.push(document.createTextNode(line.replace(re, "").trim()));
  });

  // If the model ignored the label format entirely, fall back to plain text
  // so the user still sees the answer.
  if (!labelled) out.length = 0, out.push(document.createTextNode(text));
  return out;
}

function addBot(res) {
  const el = document.createElement("div");
  el.className = "msg bot";
  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (res.route) showRoute(res.route);

  const parts = labelize(res.text);
  if (parts.length) parts.forEach((p) => bubble.appendChild(p));
  else bubble.textContent = res.text;

  const meta = document.createElement("div");
  meta.className = "meta";

  const chip = (cls, text) => {
    const c = document.createElement("span");
    c.className = `chip ${cls}`;
    c.textContent = text;
    return c;
  };

  if (res.rumination) meta.appendChild(chip("rum", "RUMINATION RISK"));
  if (res.professional_risk?.length) meta.appendChild(chip("prof", "NEEDS PROFESSIONAL"));
  for (const p of res.patterns || []) {
    meta.appendChild(chip("pat", `PATTERN: ${p.name}`));
  }
  for (const c of res.critique || []) {
    meta.appendChild(chip("crit", "SELF-AUDIT"));
  }
  if (res.intent && !res.intent.startsWith("UNCLEAR")) {
    meta.appendChild(chip("int", res.intent.split(" - ")[0]));
  }
  if (res.asked_count > 1) {
    meta.appendChild(chip("repeat", `ASKED ${res.asked_count}x`));
  }
  if (res.memories_used) meta.appendChild(chip("", `MEMORY: ${res.memories_used}`));
  if (res.provider) meta.appendChild(chip("", res.provider.toUpperCase()));

  el.appendChild(bubble);
  if (meta.childNodes.length) el.appendChild(meta);

  for (const w of res.warnings || []) {
    const b = document.createElement("div");
    b.className = "brake";
    b.textContent = w;
    el.appendChild(b);
  }

  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

function addTyping() {
  const el = document.createElement("div");
  el.className = "msg bot";
  el.id = "typing";
  el.innerHTML = `<div class="bubble typing"><span>.</span><span>.</span><span>.</span></div>`;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

function removeTyping() {
  document.getElementById("typing")?.remove();
}

/* ------------------------------------------------------------- requests */

async function ask(question, opts = {}) {
  addUser(question);
  addTyping();
  sendBtn.disabled = true;
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        session,
        lang: settings.lang,
        detail: settings.detail,
      }),
    });
    if (!res.ok) throw new Error(`server returned ${res.status}`);
    const data = await res.json();
    removeTyping();
    addBot(data);
    if (!opts.suppressSpeak && settings.speak === "on" && data.text) {
      speak(data.text);
    }
    if (data.session) {
      session = data.session;
      localStorage.setItem("atif-assistant.session", session);
    }
    // Learning runs server-side after the reply is sent, so the response no
    // longer carries `learned`. Poll once after a short delay instead.
    if (data.learned?.length) {
      refreshLearned();
    } else {
      setTimeout(refreshLearnedIfAny, 2500);
    }
    return data;
  } catch (e) {
    removeTyping();
    const detail = e instanceof SyntaxError
      ? "Malformed response from server."
      : String(e.message || e);
    addBot({ text: `Request failed: ${detail}`, warnings: [] });
    return null;
  } finally {
    sendBtn.disabled = false;
  }
}

/* ------------------------------------------------------------ route strip */

const routeBox = document.getElementById("route");
const routeMode = document.getElementById("route-mode");
const routeWhy = document.getElementById("route-why");

function showRoute(route) {
  routeBox.hidden = false;
  routeMode.textContent = ROUTE_LABEL[route.mode] || route.mode.toUpperCase();
  routeMode.className = `route-mode ${route.mode}`;
  routeWhy.textContent = route.reason || "";
}

/* ---------------------------------------------------------------- wiring */

sendBtn.addEventListener("click", () => {
  const raw = input.value.trim();
  if (!raw) return;
  input.value = "";
  input.style.height = "auto";
  ask(raw);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
});

/* memory sheet */
const sheet = document.getElementById("memory-sheet");
const memq = document.getElementById("memq");
const memResults = document.getElementById("mem-results");

document.getElementById("btn-memory").addEventListener("click", async () => {
  sheet.hidden = false;
  if (!memResults.childNodes.length) await searchMemory("");
  memq.focus();
});
document.getElementById("close-memory").addEventListener("click", () => (sheet.hidden = true));

async function searchMemory(q) {
  const r = await fetch(`/api/memory?q=${encodeURIComponent(q)}&limit=25`);
  const { results } = await r.json();
  memResults.innerHTML = "";
  if (!results.length) {
    memResults.innerHTML = `<div class="mrow"><div class="t">No matching memory.</div></div>`;
    return;
  }
  for (const m of results) {
    const row = document.createElement("div");
    row.className = "mrow";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = (m.kind || "fact").toUpperCase() + (m.confidence != null ? ` · ${Number(m.confidence).toFixed(2)}` : "");
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = m.text || m.title || m.summary || "";
    const meta = document.createElement("div");
    meta.className = "m";
    meta.textContent = m.source || "";
    row.append(k, t, meta);
    memResults.appendChild(row);
  }
}

let memTimer;
memq.addEventListener("input", () => {
  clearTimeout(memTimer);
  memTimer = setTimeout(() => searchMemory(memq.value.trim()), 200);
});

/* insights sheet */
const iSheet = document.getElementById("insights-sheet");
const iBody = document.getElementById("insights-body");

document.getElementById("btn-insights").addEventListener("click", async () => {
  iSheet.hidden = false;
  iBody.textContent = "loading...";
  try {
    const d = await (await fetch("/api/insights")).json();
    iBody.innerHTML = "";

    if (d.reading) {
      const r = document.createElement("div");
      r.className = "iread";
      r.textContent = d.reading;
      iBody.appendChild(r);
    }

    if (d.distribution?.length) {
      const h = document.createElement("div");
      h.className = "ihead";
      h.textContent = `${d.total} questions total`;
      iBody.appendChild(h);
      for (const row of d.distribution) {
        const r = document.createElement("div");
        r.className = "mrow";
        const t = document.createElement("div");
        t.className = "t";
        t.textContent = `${row.class} — ${row.count}`;
        r.appendChild(t);
        iBody.appendChild(r);
      }
    }

    if (d.contradictions?.length) {
      const h = document.createElement("div");
      h.className = "ihead";
      h.textContent = "CONFLICTING MEMORY";
      iBody.appendChild(h);
      for (const c of d.contradictions) {
        const r = document.createElement("div");
        r.className = "mrow";
        const t = document.createElement("div");
        t.className = "t";
        t.textContent = `${c.subject}: "${c.a}" vs "${c.b}"`;
        r.appendChild(t);
        iBody.appendChild(r);
      }
    }
    await renderPlaces(iBody);
    if (!iBody.childNodes.length) iBody.textContent = "No history yet.";
  } catch {
    iBody.textContent = "Could not load insights.";
  }
});
document.getElementById("close-insights").addEventListener("click", () => (iSheet.hidden = true));

function sectionHead(text) {
  const h = document.createElement("div");
  h.className = "ihead";
  h.textContent = text;
  return h;
}

async function renderPlaces(box) {
  let places = [];
  let routines = [];
  try {
    ({ places } = await (await fetch("/api/places")).json());
    ({ routines } = await (await fetch("/api/routines")).json());
  } catch {
    return;
  }
  if (!places.length && !routines.length) return;

  box.appendChild(sectionHead("PLACES (observed visits only)"));

  const derive = document.createElement("button");
  derive.className = "ghost small";
  derive.textContent = "DERIVE ROUTINES";
  derive.addEventListener("click", async () => {
    derive.disabled = true;
    await fetch("/api/routines/derive", { method: "POST" });
    box.innerHTML = "";
    await renderPlaces(box);
  });
  box.appendChild(derive);

  for (const p of places) {
    const row = document.createElement("div");
    row.className = "mrow";
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = p.name || "(unnamed place)";
    const m = document.createElement("div");
    m.className = "m";
    m.textContent = `${p.kind || "unknown"} · ${p.visits || 0} visits`;
    row.append(t, m);

    const wrap = document.createElement("div");
    wrap.className = "resolve-row";
    const input = document.createElement("input");
    input.placeholder = "name this place";
    input.value = p.name || "";
    const btn = document.createElement("button");
    btn.className = "ghost small";
    btn.textContent = "NAME";
    btn.addEventListener("click", async () => {
      const name = input.value.trim();
      if (!name) {
        input.focus();
        return;
      }
      btn.disabled = true;
      const res = await fetch(`/api/places/${p.id}/name`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      btn.disabled = false;
      if (res.ok) {
        t.textContent = name;
        btn.textContent = "SAVED";
      } else {
        btn.textContent = "FAILED";
      }
    });
    wrap.append(input, btn);
    row.appendChild(wrap);
    box.appendChild(row);
  }

  box.appendChild(sectionHead("ROUTINES (candidates, not certainties)"));
  if (!routines.length) {
    const r = document.createElement("div");
    r.className = "mrow";
    r.textContent = "No routines derived yet.";
    box.appendChild(r);
    return;
  }
  for (const r of routines) {
    const row = document.createElement("div");
    row.className = "mrow";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = `${r.weekday || "?"} · ${r.hour_bucket != null ? `${r.hour_bucket}:00` : "?"} · ${r.status}`;
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = r.name || r.place_id;
    const m = document.createElement("div");
    m.className = "m";
    m.textContent = `${r.observations || 0} observations · confidence ${Number(r.confidence || 0).toFixed(2)}`;
    row.append(k, t, m);
    box.appendChild(row);
  }
}

/* decision ledger */
const dSheet = document.getElementById("decisions-sheet");
const dBody = document.getElementById("decisions-body");
const dForm = document.getElementById("decision-form");

function decisionCard(d, due) {
  const row = document.createElement("div");
  row.className = due ? "mrow due" : "mrow";

  const k = document.createElement("div");
  k.className = "k";
  const conf = d.confidence != null ? ` conf ${d.confidence}` : "";
  if (due) {
    k.textContent = `REVIEW DUE ${d.review_date}${conf}`;
  } else {
    k.textContent = d.review_date
      ? `review ${d.review_date}${conf}`
      : `no review date${conf}`;
  }
  row.appendChild(k);

  const topic = document.createElement("div");
  topic.className = "t";
  topic.textContent = d.topic || "(untitled)";
  row.appendChild(topic);

  const what = document.createElement("div");
  what.className = "m";
  what.textContent = d.decision || "";
  row.appendChild(what);

  if (d.prediction) {
    const p = document.createElement("div");
    p.className = "m";
    // Kept verbatim as typed. No model rewrites a prediction after the fact,
    // because the point of the prediction is that it was made in advance.
    p.textContent = `predicted: ${d.prediction}`;
    row.appendChild(p);
  }

  const wrap = document.createElement("div");
  wrap.className = "resolve-row";
  const input = document.createElement("input");
  input.placeholder = "what actually happened";
  const btn = document.createElement("button");
  btn.className = "ghost small";
  btn.textContent = "RESOLVE";
  btn.addEventListener("click", async () => {
    const text = input.value.trim();
    if (!text) {
      input.focus();
      return;
    }
    btn.disabled = true;
    const res = await fetch(`/api/decisions/${d.id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actual_outcome: text }),
    });
    btn.disabled = false;
    if (!res.ok) {
      btn.textContent = "FAILED";
      return;
    }
    row.remove();
    if (!dBody.querySelector(".mrow")) {
      dBody.textContent = "Nothing open.";
    }
  });
  wrap.append(input, btn);
  row.appendChild(wrap);
  return row;
}

async function loadDecisions() {
  dBody.textContent = "loading...";
  try {
    const { due = [], open = [] } = await (await fetch("/api/decisions")).json();
    dBody.innerHTML = "";

    const dueIds = new Set(due.map((d) => d.id));
    const rest = open.filter((d) => !dueIds.has(d.id));

    if (due.length) {
      const h = document.createElement("div");
      h.className = "ihead";
      h.textContent = `DUE FOR REVIEW - ${due.length}`;
      dBody.appendChild(h);
      for (const d of due) dBody.appendChild(decisionCard(d, true));
    }
    if (rest.length) {
      const h = document.createElement("div");
      h.className = "ihead";
      h.textContent = `OPEN - ${rest.length}`;
      dBody.appendChild(h);
      for (const d of rest) dBody.appendChild(decisionCard(d, false));
    }
    if (!dBody.childNodes.length) dBody.textContent = "Nothing open.";
  } catch {
    dBody.textContent = "Could not load decisions.";
  }
}

document.getElementById("btn-decisions").addEventListener("click", () => {
  dSheet.hidden = false;
  loadDecisions();
});
document.getElementById("close-decisions").addEventListener("click", () => {
  dSheet.hidden = true;
});
document.getElementById("toggle-log").addEventListener("click", () => {
  dForm.hidden = !dForm.hidden;
});
document.getElementById("cancel-log").addEventListener("click", () => {
  dForm.hidden = true;
  dForm.reset();
});
dForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(dForm));
  const conf = f.confidence === "" ? null : Number(f.confidence);
  if (conf != null && (Number.isNaN(conf) || conf < 0 || conf > 1)) {
    return;
  }
  const save = document.getElementById("save-decision");
  save.disabled = true;
  await fetch("/api/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: f.topic,
      decision: f.decision,
      prediction: f.prediction || null,
      confidence: conf,
      review_date: f.review_date || null,
    }),
  });
  save.disabled = false;
  dForm.reset();
  dForm.hidden = true;
  loadDecisions();
});

/* learned facts sheet */
const lSheet = document.getElementById("learned-sheet");
const lBody = document.getElementById("learned-body");

async function refreshLearned() {
  let candidates = [];
  try {
    ({ candidates } = await (await fetch("/api/learned")).json());
  } catch {
    return; // non-critical
  }
  if (!candidates?.length) return;
  lSheet.hidden = false;
  lBody.innerHTML = "";
  for (const c of candidates) {
    const row = document.createElement("div");
    row.className = "mrow";
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = c.text;
    const btns = document.createElement("div");
    btns.className = "m";
    for (const [label, act] of [["APPROVE", "approve"], ["REJECT", "reject"]]) {
      const b = document.createElement("button");
      b.className = "ghost small";
      b.textContent = label;
      b.addEventListener("click", async () => {
        await fetch(`/api/learned/${c.id}/${act}`, { method: "POST" });
        row.remove();
        if (!lBody.childNodes.length) lSheet.hidden = true;
      });
      btns.appendChild(b);
    }
    row.append(t, btns);
    lBody.appendChild(row);
  }
}

/* Poll for background-extracted candidates without blocking the reply. */
async function refreshLearnedIfAny() {
  try {
    const { candidates } = await (await fetch("/api/learned")).json();
    if (candidates?.length) refreshLearned();
  } catch {
    /* non-critical */
  }
}
document.getElementById("close-learned").addEventListener("click", () => (lSheet.hidden = true));

/* ------------------------------------------------------------- settings */

const settings = {
  lang: "en",
  speak: "off",
  voice: "",
  stt: "en-US",
  detail: "normal",
  accent: "",
  theme: "dark",
};

function applyAccent(color) {
  if (color) document.documentElement.style.setProperty("--acc", color);
  else document.documentElement.style.removeProperty("--acc");
}

function applyTheme(theme) {
  if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  try {
    localStorage.setItem("atif-assistant.theme", theme);
  } catch {
    /* non-critical */
  }
}

const STRINGS = {
  en: {
    placeholder: "Ask. Atif Assistant decides how to answer.",
    related: "What is this file related to? (e.g. resume, project, note)",
    uploading: "Uploading...",
    uploaded: "Saved to memory.",
    uploadFailed: "Upload failed.",
    saved: "Settings saved.",
  },
  ur: {
    placeholder: "پوچھیں۔ عاطف اسسٹنٹ خود جواب دے گا۔",
    related: "یہ فائل کس بارے میں ہے؟ (مثلاً ریزیومے، پروجیکٹ، نوٹ)",
    uploading: "اپ لوڈ ہو رہا ہے...",
    uploaded: "یادداشت میں محفوظ ہو گیا۔",
    uploadFailed: "اپ لوڈ ناکام۔",
    saved: "سیٹنگز محفوظ ہو گئیں۔",
  },
};

async function loadSettings() {
  try {
    const saved = await (await fetch("/api/settings")).json();
    for (const k of Object.keys(settings)) {
      if (saved[k] != null && saved[k] !== "") settings[k] = saved[k];
    }
  } catch {
    /* defaults are fine */
  }
  applyLang(settings.lang);
  applyAccent(settings.accent);
  applyTheme(settings.theme);
}

function applyLang(code) {
  const ur = code === "ur";
  document.documentElement.lang = ur ? "ur" : "en";
  document.documentElement.dir = ur ? "rtl" : "ltr";
  const s = STRINGS[ur ? "ur" : "en"];
  input.placeholder = s.placeholder;
  const rel = document.getElementById("upload-related");
  if (rel) rel.placeholder = s.related;
}

async function saveSettings() {
  const payload = {
    lang: settings.lang,
    speak: settings.speak,
    voice: settings.voice,
    stt: settings.stt,
    detail: settings.detail,
    accent: settings.accent,
    theme: settings.theme,
  };
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    /* non-critical */
  }
}

/* ---------------------------------------------------------------- speech */

let voices = [];

function loadVoices() {
  if (!("speechSynthesis" in window)) return;
  voices = window.speechSynthesis.getVoices();
  const sel = document.getElementById("set-voice");
  if (!sel) return;
  sel.innerHTML = "";
  const pref = settings.lang === "ur" ? "ur" : "en";
  const sorted = [...voices].sort((a) => (a.lang || "").startsWith(pref) ? -1 : 1);
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = "Automatic";
  sel.appendChild(opt0);
  for (const v of sorted) {
    const o = document.createElement("option");
    o.value = v.name;
    o.textContent = `${v.name} (${v.lang})`;
    sel.appendChild(o);
  }
  if (settings.voice && voices.some((v) => v.name === settings.voice)) {
    sel.value = settings.voice;
  }
}

// Some browsers populate the voice list asynchronously.
if ("speechSynthesis" in window) {
  try { window.speechSynthesis.onvoiceschanged = loadVoices; } catch { /* ignore */ }
}

// The spoken language follows the reply language, not the microphone language.
// A microphone set to English while the answer is Urdu must still be spoken
// with an Urdu voice.
function speechLang() {
  return settings.lang === "ur" ? "ur-PK" : "en-US";
}

function pickVoice(lang) {
  const pref = lang.slice(0, 2);
  const chosen = settings.voice && voices.find((v) => v.name === settings.voice);
  return (
    chosen ||
    voices.find((v) => (v.lang || "").replace("_", "-").startsWith(lang)) ||
    voices.find((v) => (v.lang || "").replace("_", "-").startsWith(pref)) ||
    null
  );
}

function hasVoiceFor(lang) {
  const pref = lang.slice(0, 2);
  return voices.some((v) => (v.lang || "").replace("_", "-").startsWith(pref));
}

function speak(text, opts = {}) {
  if (!opts.force && settings.speak !== "on") return;
  if (!text) return;
  const clean = String(text).replace(/\[(FACT|INFERENCE|ASSUMPTION|UNKNOWN|PREDICTION)\]/gi, "");
  if (!clean.trim()) {
    if (opts.onEnd) opts.onEnd();
    return;
  }

  // onEnd must fire exactly once, whichever engine finishes first.
  let ended = false;
  const done = () => {
    if (ended) return;
    ended = true;
    if (opts.onEnd) opts.onEnd();
  };

  // Inside the Android app, prefer the native text-to-speech engine. WebView
  // does not implement the Web Speech API. There is no completion callback in
  // the bridge, so estimate from the word count.
  const lang = speechLang();
  if (window.AndroidVoice && typeof window.AndroidVoice.speak === "function") {
    try {
      window.AndroidVoice.speak(clean, lang);
      const words = clean.split(/\s+/).filter(Boolean).length;
      const estimate = Math.min(Math.max(words * 380, 1200), 30000);
      setTimeout(done, estimate);
      return;
    } catch {
      /* fall through to the web engine */
    }
  }

  if (!("speechSynthesis" in window)) {
    done();
    return;
  }
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(clean);
    const match = pickVoice(lang);
    if (match) u.voice = match;
    u.lang = lang;
    u.onend = done;
    u.onerror = done;
    window.speechSynthesis.speak(u);
  } catch {
    /* speech is best-effort */
    done();
  }
}

/* ------------------------------------------------------------ speech input */

let recognizer = null;
let listening = false;

function setupRecognizer() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.continuous = false;
  r.interimResults = false;
  r.maxAlternatives = 1;
  r.onresult = (e) => {
    const text = e.results[0][0].transcript;
    input.value = text;
    input.focus();
  };
  r.onend = () => {
    listening = false;
    mic?.classList.remove("active");
  };
  r.onerror = r.onend;
  return r;
}

function toggleMic() {
  const btn = mic;

  // Inside the Android app, use the native recognizer via the JS bridge.
  if (window.AndroidVoice && typeof window.AndroidVoice.listen === "function") {
    if (listening) {
      listening = false;
      btn?.classList.remove("active");
      return;
    }
    listening = true;
    btn?.classList.add("active");
    window.onAndroidSpeechResult = (text) => {
      listening = false;
      btn?.classList.remove("active");
      if (text) {
        input.value = text;
        input.focus();
      }
    };
    try {
      window.AndroidVoice.listen(settings.stt);
    } catch {
      listening = false;
      btn?.classList.remove("active");
    }
    return;
  }

  if (!recognizer) recognizer = setupRecognizer();
  if (!recognizer) {
    alert("Speech recognition is not supported in this browser.");
    return;
  }
  if (listening) {
    recognizer.stop();
    return;
  }
  recognizer.lang = settings.stt;
  try {
    recognizer.start();
    listening = true;
    btn?.classList.add("active");
  } catch {
    listening = false;
  }
}

/* ------------------------------------------------------------- voice call */

const callSheet = document.getElementById("call-sheet");
const callStateEl = document.getElementById("call-state");
const callTranscriptEl = document.getElementById("call-transcript");
const callHeardEl = document.getElementById("call-heard");
const callOrb = document.getElementById("call-orb");

const CALL_LABEL = { listening: "LISTENING", thinking: "THINKING", speaking: "SPEAKING" };
let callActive = false;
let callPhase = "idle"; // listening | thinking | speaking
let callRecognizer = null;
let callGotResult = false;
let callRetry = null;
let callResumeTimer = null;
let callErrorStreak = 0;

function callSupported() {
  return Boolean(
    (window.SpeechRecognition || window.webkitSpeechRecognition) ||
      (window.AndroidVoice && typeof window.AndroidVoice.listen === "function")
  );
}

function callSetPhase(phase) {
  callPhase = phase;
  callSheet.classList.remove("listening", "thinking", "speaking");
  callSheet.classList.add(phase);
  callStateEl.textContent = CALL_LABEL[phase] || "";
}

// Re-open the mic once, debounced, so a cancelled utterance's onend and an
// explicit barge-in don't start two recognizers at the same time.
function callResume() {
  if (!callActive) return;
  clearTimeout(callResumeTimer);
  callResumeTimer = setTimeout(() => {
    if (callActive && callPhase !== "listening") callListen();
  }, 250);
}

function stopCallRecognition() {
  clearTimeout(callRetry);
  if (callRecognizer) {
    try {
      callRecognizer.onend = null;
      callRecognizer.onerror = null;
      callRecognizer.abort();
    } catch {
      /* already stopped */
    }
    callRecognizer = null;
  }
}

function startCall() {
  if (callActive) return;
  if (!callSupported()) {
    alert(
      "Voice calls need speech recognition, which this browser does not " +
        "support. On phones, open the app over HTTPS (or localhost) in Chrome, " +
        "Edge or Safari and allow the microphone."
    );
    return;
  }
  callErrorStreak = 0;
  // The one-shot mic and the call must never run together.
  if (listening && recognizer) {
    try { recognizer.stop(); } catch { /* ignore */ }
  }
  try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch { /* ignore */ }
  callActive = true;
  callTranscriptEl.textContent = "";
  callHeardEl.textContent = "";
  callSheet.hidden = false;
  callListen();
}

function endCall() {
  callActive = false;
  callPhase = "idle";
  clearTimeout(callResumeTimer);
  stopCallRecognition();
  try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch { /* ignore */ }
  if (window.AndroidVoice && typeof window.AndroidVoice.stop === "function") {
    try { window.AndroidVoice.stop(); } catch { /* ignore */ }
  }
  callSheet.hidden = true;
}

function callListen() {
  if (!callActive) return;
  clearTimeout(callRetry);
  callGotResult = false;
  callSetPhase("listening");
  callTranscriptEl.textContent = "";
  callHeardEl.textContent = "";

  // Inside the Android app use the native recognizer via the JS bridge. It is
  // single-shot, so we re-arm it after every turn.
  if (window.AndroidVoice && typeof window.AndroidVoice.listen === "function") {
    window.onAndroidSpeechResult = (text) => {
      if (!callActive) return;
      const said = (text || "").trim();
      if (said) callSubmit(said);
      else callListen();
    };
    try {
      window.AndroidVoice.listen(settings.stt);
    } catch {
      callRetry = setTimeout(callListen, 400);
    }
    return;
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let r;
  try {
    r = new SR();
  } catch {
    endCall();
    return;
  }
  callRecognizer = r;
  r.lang = settings.stt;
  r.continuous = false;
  r.interimResults = true;
  r.maxAlternatives = 1;

  r.onresult = (e) => {
    let interim = "";
    let finalText = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) finalText += res[0].transcript;
      else interim += res[0].transcript;
    }
    callHeardEl.textContent = (finalText + interim).trim();
    if (finalText.trim()) {
      callGotResult = true;
      callErrorStreak = 0;
      stopCallRecognition();
      callSubmit(finalText.trim());
    }
  };
  r.onerror = (e) => {
    if (!callActive) return;
    const err = e.error || "unknown";
    // Silence and our own aborts are normal; onend re-arms the mic.
    if (err === "no-speech" || err === "aborted") return;
    if (err === "not-allowed" || err === "service-not-allowed") {
      callTranscriptEl.textContent = "Microphone permission is required for a call.";
      endCall();
      return;
    }
    // "network" and a missing language pack can be transient; retry a few
    // times, then stop with a visible reason instead of looping forever.
    if ((err === "network" || err === "language-not-supported") && callErrorStreak < 3) {
      callErrorStreak += 1;
      callTranscriptEl.textContent = `Retrying the microphone (${callErrorStreak}/3)...`;
      return;
    }
    callTranscriptEl.textContent =
      err === "language-not-supported"
        ? "This browser cannot recognise that language. Set MICROPHONE LANGUAGE to one it supports."
        : `Speech recognition stopped: ${err}.`;
    endCall();
  };
  r.onend = () => {
    if (!callActive || callGotResult) return;
    if (callPhase === "listening") callRetry = setTimeout(callListen, 350);
  };

  try {
    r.start();
  } catch {
    callRetry = setTimeout(callListen, 400);
  }
}

async function callSubmit(text) {
  if (!callActive) return;
  stopCallRecognition();
  callTranscriptEl.textContent = text;
  callHeardEl.textContent = "";
  callSetPhase("thinking");

  const data = await ask(text, { suppressSpeak: true });
  if (!callActive) return;
  if (!data || !data.text) {
    callResume();
    return;
  }
  callSetPhase("speaking");
  const lang = speechLang();
  if ("speechSynthesis" in window && voices.length && !hasVoiceFor(lang)) {
    callHeardEl.textContent = lang.startsWith("ur")
      ? "No Urdu voice is installed on this device; install one for clearer speech."
      : "No matching voice found; using the default.";
  }
  speak(data.text, { force: true, onEnd: callResume });
}

document.getElementById("btn-call").addEventListener("click", startCall);
document.getElementById("end-call").addEventListener("click", endCall);
// Tap the orb to barge in while the answer is being spoken.
callOrb.addEventListener("click", () => {
  if (callActive && callPhase === "speaking") {
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch { /* ignore */ }
    callResume();
  }
});

/* --------------------------------------------------------------- uploads */

const uSheet = document.getElementById("upload-sheet");

document.getElementById("btn-upload").addEventListener("click", () => {
  uSheet.hidden = false;
});
document.getElementById("close-upload").addEventListener("click", () => {
  uSheet.hidden = true;
});

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const s = String(reader.result);
      resolve(s.slice(s.indexOf(",") + 1));
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function uploadFile() {
  const fileEl = document.getElementById("upload-file");
  const relatedEl = document.getElementById("upload-related");
  const statusEl = document.getElementById("upload-status");
  const file = fileEl?.files?.[0];
  const s = STRINGS[settings.lang === "ur" ? "ur" : "en"];
  if (!file) {
    fileEl?.focus();
    return;
  }
  statusEl.textContent = s.uploading;
  try {
    const content_b64 = await fileToBase64(file);
    const res = await fetch("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content_b64,
        related_to: relatedEl?.value.trim() || null,
      }),
    });
    if (!res.ok) throw new Error();
    statusEl.textContent = s.uploaded;
    fileEl.value = "";
    if (relatedEl) relatedEl.value = "";
  } catch {
    statusEl.textContent = s.uploadFailed;
  }
}

document.getElementById("do-upload").addEventListener("click", uploadFile);

function humanSize(n) {
  if (n == null) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = Number(n);
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

async function loadLibrary() {
  const box = document.getElementById("upload-library");
  if (!box) return;
  box.innerHTML = "loading...";
  try {
    const { media = [] } = await (await fetch("/api/media?limit=50")).json();
    box.innerHTML = "";
    if (!media.length) {
      box.textContent = "No files uploaded yet.";
      return;
    }
    for (const m of media) {
      let meta = {};
      try {
        meta = m.meta ? JSON.parse(m.meta) : {};
      } catch {
        meta = {};
      }
      const row = document.createElement("div");
      row.className = "mrow";
      const k = document.createElement("div");
      k.className = "k";
      k.textContent = `${(m.kind || "file").toUpperCase()} · ${humanSize(meta.size)}`;
      const t = document.createElement("div");
      t.className = "t";
      t.textContent = meta.filename || m.path || "(file)";
      const d = document.createElement("div");
      d.className = "m";
      d.textContent = [m.tags ? `related to: ${m.tags}` : "", m.created_at || ""]
        .filter(Boolean)
        .join(" · ");
      row.append(k, t, d);
      box.appendChild(row);
    }
  } catch {
    box.textContent = "Could not load files.";
  }
}

document.getElementById("toggle-library").addEventListener("click", () => {
  const box = document.getElementById("upload-library");
  if (!box) return;
  box.hidden = !box.hidden;
  if (!box.hidden) loadLibrary();
});

/* ------------------------------------------------------------ settings ui */

const setSheet = document.getElementById("settings-sheet");
const setLang = document.getElementById("set-lang");
const setSpeak = document.getElementById("set-speak");
const setVoice = document.getElementById("set-voice");
const setStt = document.getElementById("set-stt");
const setDetail = document.getElementById("set-detail");
const settingsStatus = document.getElementById("settings-status");

function syncSettingsForm() {
  if (setLang) setLang.value = settings.lang;
  if (setSpeak) setSpeak.value = settings.speak;
  if (setStt) setStt.value = settings.stt;
  if (setDetail) setDetail.value = settings.detail;
  const setAccentEl = document.getElementById("set-accent");
  if (setAccentEl) setAccentEl.value = settings.accent;
  const setThemeEl = document.getElementById("set-theme");
  if (setThemeEl) setThemeEl.value = settings.theme;
  if (setVoice) {
    loadVoices();
    setVoice.value = settings.voice || "";
  }
}

document.getElementById("btn-settings").addEventListener("click", () => {
  syncSettingsForm();
  loadProviders();
  uSheet.hidden = true;
  document.getElementById("settings-sheet").hidden = false;
});
document.getElementById("close-settings").addEventListener("click", () => {
  document.getElementById("settings-sheet").hidden = true;
});

if (setLang) {
  setLang.addEventListener("change", () => {
    settings.lang = setLang.value;
    applyLang(settings.lang);
    loadVoices();
  });
}
if (setSpeak) setSpeak.addEventListener("change", () => (settings.speak = setSpeak.value));
if (setStt) setStt.addEventListener("change", () => (settings.stt = setStt.value));
if (setDetail) setDetail.addEventListener("change", () => (settings.detail = setDetail.value));
if (setVoice) setVoice.addEventListener("change", () => (settings.voice = setVoice.value));
{
  const setAccentEl = document.getElementById("set-accent");
  if (setAccentEl) {
    setAccentEl.addEventListener("change", () => {
      settings.accent = setAccentEl.value;
      applyAccent(settings.accent);
    });
  }
  const setThemeEl = document.getElementById("set-theme");
  if (setThemeEl) {
    setThemeEl.addEventListener("change", () => {
      settings.theme = setThemeEl.value;
      applyTheme(settings.theme);
    });
  }
}

document.getElementById("save-settings").addEventListener("click", async () => {
  await saveSettings();
  const status = document.getElementById("settings-status");
  const s = STRINGS[settings.lang === "ur" ? "ur" : "en"];
  if (status) status.textContent = s.saved;
});

document.getElementById("test-voice").addEventListener("click", () => {
  const was = settings.speak;
  settings.speak = "on";
  speak(
    settings.lang === "ur"
      ? "السلام علیکم، میں عاطف اسسٹنٹ ہوں۔"
      : "This is the Atif Assistant voice."
  );
  settings.speak = was;
});

/* -------------------------------------------------- providers (API keys) */

const providersEl = document.getElementById("providers-list");
const providersStatus = document.getElementById("providers-status");

function providerBadge(state) {
  const b = document.createElement("span");
  b.className = "pbadge";
  b.dataset.role = "badge";
  b.classList.add(state === "ready" ? "pok" : state === "error" ? "pbad" : "punknown");
  b.textContent = state === "ready" ? "READY" : state === "error" ? "ERROR" : "UNKNOWN";
  return b;
}

function renderProvider(p) {
  const card = document.createElement("div");
  card.className = "pcard";
  card.dataset.name = p.name;

  const head = document.createElement("div");
  head.className = "phead";
  const title = document.createElement("strong");
  title.textContent = p.label || p.name;
  head.append(title, providerBadge(p.ready ? "ready" : p.error ? "error" : "unknown"));
  card.appendChild(head);

  const mkRow = (labelText, role, value, placeholder, type) => {
    const row = document.createElement("label");
    row.className = "prow";
    row.textContent = labelText;
    const input = document.createElement("input");
    input.type = type || "text";
    input.dataset.role = role;
    if (type === "password") input.autocomplete = "off";
    if (value != null) input.value = value;
    if (placeholder) input.placeholder = placeholder;
    row.appendChild(input);
    card.appendChild(row);
  };

  mkRow(
    "API key",
    "key",
    "",
    p.key_set ? `saved (${p.key_hint}) — type to replace` : "paste key",
    "password"
  );
  mkRow("Model", "model", p.model || "", "");
  if (p.name === "ollama") mkRow("URL", "url", p.url || "", "");

  const actions = document.createElement("div");
  actions.className = "form-actions";
  const save = document.createElement("button");
  save.className = "ghost small";
  save.textContent = "SAVE";
  const test = document.createElement("button");
  test.className = "ghost small";
  test.textContent = "TEST";
  actions.append(save, test);
  if (p.name !== "ollama") {
    const clear = document.createElement("button");
    clear.className = "ghost small";
    clear.textContent = "CLEAR KEY";
    actions.appendChild(clear);
    clear.addEventListener("click", () => clearProviderKey(card));
  }
  card.appendChild(actions);

  const note = document.createElement("div");
  note.className = "hint";
  note.dataset.role = "note";
  if (!p.key_set && p.name !== "ollama") note.textContent = "no key set";
  card.appendChild(note);

  save.addEventListener("click", () => saveProvider(card));
  test.addEventListener("click", () => testProvider(card));
  return card;
}

async function loadProviders() {
  if (!providersEl) return;
  try {
    const data = await (await fetch("/api/providers")).json();
    providersEl.innerHTML = "";
    for (const p of data.providers) providersEl.appendChild(renderProvider(p));
  } catch {
    providersEl.textContent = "Could not load providers.";
  }
}

function providerPayload(card) {
  const get = (role) => card.querySelector(`[data-role="${role}"]`);
  const payload = {};
  const key = get("key");
  // An empty key field means "leave the stored key alone"; use CLEAR to remove.
  if (key && key.value.trim()) payload.api_key = key.value.trim();
  // Model/url are sent even when empty, so clearing the field reverts to the
  // provider default instead of pinning an empty model.
  const model = get("model");
  if (model) payload.model = model.value;
  const url = get("url");
  if (url) payload.url = url.value;
  return payload;
}

function setCardBadge(card, state, text) {
  const badge = card.querySelector('[data-role="badge"]');
  if (!badge) return;
  badge.className = "pbadge " + (state === "ready" ? "pok" : state === "error" ? "pbad" : "punknown");
  badge.textContent = text || (state === "ready" ? "READY" : state === "error" ? "ERROR" : "UNKNOWN");
}

async function saveProvider(card) {
  const name = card.dataset.name;
  const note = card.querySelector('[data-role="note"]');
  if (note) note.textContent = "Saving…";
  try {
    const res = await fetch(`/api/providers/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(providerPayload(card)),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || "save failed");
    const key = card.querySelector('[data-role="key"]');
    if (key) key.value = "";
    if (note) note.textContent = "Saved.";
    await loadProviders();
  } catch (err) {
    if (note) note.textContent = `Save failed: ${err.message}`;
  }
}

async function clearProviderKey(card) {
  const name = card.dataset.name;
  const note = card.querySelector('[data-role="note"]');
  if (note) note.textContent = "Clearing key…";
  try {
    const res = await fetch(`/api/providers/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_key: true }),
    });
    if (!res.ok) throw new Error("clear failed");
    await loadProviders();
  } catch (err) {
    if (note) note.textContent = `Clear failed: ${err.message}`;
  }
}

async function testProvider(card) {
  const name = card.dataset.name;
  const note = card.querySelector('[data-role="note"]');
  if (note) note.textContent = "Testing…";
  setCardBadge(card, "unknown", "…");
  try {
    const res = await fetch(`/api/providers/${name}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(providerPayload(card)),
    });
    const body = await res.json();
    if (body.ready) {
      setCardBadge(card, "ready", "READY");
      if (note) note.textContent = `OK · ${body.model} · ${body.latency_ms} ms`;
    } else {
      setCardBadge(card, "error", "ERROR");
      if (note) note.textContent = body.error || "not ready";
    }
  } catch (err) {
    setCardBadge(card, "error", "ERROR");
    if (note) note.textContent = err.message;
  }
}

async function testAllProviders() {
  if (!providersStatus) return;
  providersStatus.textContent = "Testing all providers…";
  try {
    const res = await fetch("/api/providers/test", { method: "POST" });
    const data = await res.json();
    let ready = 0;
    const results = data.results || [];
    for (const r of results) {
      const card = providersEl.querySelector(`[data-name="${r.provider}"]`);
      if (card) {
        setCardBadge(card, r.ready ? "ready" : "error", r.ready ? "READY" : "ERROR");
        const note = card.querySelector('[data-role="note"]');
        if (note) {
          note.textContent = r.ready
            ? `OK · ${r.model} · ${r.latency_ms} ms`
            : r.error || "not ready";
        }
      }
      if (r.ready) ready += 1;
    }
    providersStatus.textContent = `${ready} of ${results.length} providers ready.`;
  } catch (err) {
    providersStatus.textContent = `Test failed: ${err.message}`;
  }
}

if (providersEl) {
  const testAll = document.getElementById("test-all-providers");
  if (testAll) testAll.addEventListener("click", testAllProviders);
}

mic.addEventListener("click", toggleMic);

if ("speechSynthesis" in window) {
  window.speechSynthesis.onvoiceschanged = loadVoices;
}

/* -------------------------------------------------------------- backup */

const backupStatus = document.getElementById("backup-status");

document.getElementById("export-backup").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = "/api/export";
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  if (backupStatus) backupStatus.textContent = "Export started.";
});

document.getElementById("import-backup-btn").addEventListener("click", () => {
  document.getElementById("import-backup").click();
});

document.getElementById("import-backup").addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  if (backupStatus) backupStatus.textContent = "Importing...";
  try {
    const payload = JSON.parse(await file.text());
    const res = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || "import failed");
    const a = body.added || {};
    if (backupStatus) {
      backupStatus.textContent = `Imported: ${a.facts || 0} facts, ${a.notes || 0} notes, ${
        a.decisions || 0
      } decisions.`;
    }
  } catch (err) {
    if (backupStatus) backupStatus.textContent = `Import failed: ${err.message}`;
  } finally {
    e.target.value = "";
  }
});

/* --------------------------------------------------------- install (PWA) */

let installPrompt = null;

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  const btn = document.getElementById("install-app");
  if (btn) btn.hidden = false;
});

document.getElementById("install-app").addEventListener("click", async () => {
  const btn = document.getElementById("install-app");
  if (!installPrompt) {
    if (backupStatus) backupStatus.textContent = "Use your browser menu: Add to Home screen.";
    return;
  }
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  if (btn) btn.hidden = true;
});

/* ---------------------------------------------------------------- wiring */

/* boot */
(async function init() {
  await loadSettings();
  loadVoices();
  try {
    const r = await fetch("/api/health");
    const h = await r.json();
    const ready = h.providers.find((p) => p.ready);
    dot.className = "dot on";
    statusline.textContent = ready ? `${ready.name} · ${h.counts.facts}f ${h.counts.episodes}e ${h.counts.patterns}p` : "no model key";
    if (!ready) dot.className = "dot off";

    if (session) {
      const hr = await fetch(`/api/history/${session}`);
      const { messages } = await hr.json();
      if (messages?.length) {
        for (const m of messages) {
          if (m.role === "user") addUser(m.content);
          else addBot({ text: m.content, warnings: [] });
        }
      }
    }
  } catch {
    dot.className = "dot off";
    statusline.textContent = "offline";
  }
})();

/* PWA */
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}