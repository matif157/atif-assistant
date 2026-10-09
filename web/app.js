/* Atif Assistant PWA client */

const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusline = document.getElementById("statusline");
const dot = document.getElementById("dot");

let session = localStorage.getItem("atif-assistant.session") || null;

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

async function ask(question) {
  addUser(question);
  addTyping();
  sendBtn.disabled = true;
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session }),
    });
    if (!res.ok) throw new Error(`server returned ${res.status}`);
    const data = await res.json();
    removeTyping();
    addBot(data);
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
  } catch (e) {
    removeTyping();
    const detail = e instanceof SyntaxError
      ? "Malformed response from server."
      : String(e.message || e);
    addBot({ text: `Request failed: ${detail}`, warnings: [] });
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
    if (!iBody.childNodes.length) iBody.textContent = "No history yet.";
  } catch {
    iBody.textContent = "Could not load insights.";
  }
});
document.getElementById("close-insights").addEventListener("click", () => (iSheet.hidden = true));

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

/* boot */
(async function init() {
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