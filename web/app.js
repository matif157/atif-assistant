/* Atif Assistant PWA client */

const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const mic = document.getElementById("mic");
const statusline = document.getElementById("statusline");
const dot = document.getElementById("dot");

// The server hands back a session id with the first reply; restoring it here
// keeps a reload inside the same conversation. Accidentally removed once (by
// the basis-sidebar commit) which broke chat, the call and hands-free at once.
let session = localStorage.getItem("atif-assistant.session") || null;
let lastBasis = null;

function renderBasis(data) {
  const sidebar = document.getElementById("basis-sidebar");
  const body = document.getElementById("basis-body");
  if (!body) return;
  if (!data || (!data.route && !data.labels?.length && !data.critique?.length && !data.memories_used)) {
    if (sidebar) sidebar.hidden = true;
    body.innerHTML = "";
    return;
  }
  if (sidebar) sidebar.hidden = false;
  body.innerHTML = "";

  const addRow = (title, content) => {
    if (!content) return;
    const row = document.createElement("div");
    row.className = "basis-row";
    const t = document.createElement("small");
    t.textContent = title;
    const c = document.createElement("div");
    c.textContent = content;
    row.appendChild(t);
    row.appendChild(c);
    body.appendChild(row);
  };

  if (data.route) {
    addRow("MODE", `${(ROUTE_LABEL[data.route.mode] || (data.route.mode||"").toUpperCase())}${data.route.confidence ? " · "+Math.round(data.route.confidence*100)+"%" : ""}`);
    addRow("WHY", data.route.reason || "");
    addRow("INTENT", data.route.intent || "");
    if (data.route.escalations?.length) {
      addRow("ESCALATIONS", data.route.escalations.join("\n"));
    }
  }
  addRow("PROVIDER", (data.provider||"").toUpperCase());
  if (data.memories_used) addRow("MEMORIES USED", String(data.memories_used));
  if (data.asked_count > 1) addRow("ASKED COUNT", String(data.asked_count));
  if (data.speaker?.name) {
    addRow("SPEAKER (advisory)", `${data.speaker.name}${data.speaker.score!=null ? " · "+Math.round(data.speaker.score*100)+"%" : ""}`);
  }

  if (data.labels?.length) {
    const row = document.createElement("div");
    row.className = "basis-row";
    const t = document.createElement("small");
    t.textContent = "LABELS";
    const wrap = document.createElement("div");
    wrap.className = "basis-labels";
    for (const lbl of data.labels) {
      const l = document.createElement("div");
      const tag = document.createElement("div");
      tag.className = "basis-lbl";
      tag.textContent = (lbl.label || "").toUpperCase();
      const txt = document.createElement("div");
      txt.className = "basis-lbl-text";
      txt.textContent = lbl.text || "";
      l.appendChild(tag);
      l.appendChild(txt);
      wrap.appendChild(l);
    }
    row.appendChild(t);
    row.appendChild(wrap);
    body.appendChild(row);
  }

  if (data.critique?.length) {
    addRow("CRITIQUE", data.critique.join("\n"));
  }
  if (data.warnings?.length) {
    addRow("WARNINGS", data.warnings.join("\n"));
  }
  if (data.patterns?.length) {
    addRow("PATTERNS", data.patterns.map(p => p.name || JSON.stringify(p)).join(", "));
  }
  if (data.professional_risk?.length) {
    addRow("PROFESSIONAL RISK", data.professional_risk.join(", "));
  }
  if (data.rumination) addRow("RUMINATION", "YES");
}

function renderReplyOptions(data) {
  const wrap = document.getElementById("reply-options");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!data) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  const mk = (label, fn) => {
    const b = document.createElement("button");
    b.className = "reply-chip";
    b.textContent = label;
    b.onclick = fn;
    wrap.appendChild(b);
  };
  mk("Explain more", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = `Explain that more clearly: ${data.text?.slice(0,80) || ""}`; inEl.focus(); }
  });
  mk("Shorter", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = "Make it shorter."; inEl.focus(); }
  });
  mk("Facts only", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = "Answer with only [FACT]-supported points."; inEl.focus(); }
  });
  mk("Show basis", () => {
    const sb = document.getElementById("basis-sidebar");
    if (sb) sb.hidden = false;
  });
  mk("Give example", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = "Give a concrete example."; inEl.focus(); }
  });
  mk("Challenge this", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = "Challenge this answer - show the strongest case against it."; inEl.focus(); }
  });
  mk("In Urdu", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = inEl.value || "Reply in Urdu."; inEl.focus(); }
  });
  mk("In English", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = inEl.value || "Reply in English."; inEl.focus(); }
  });
  mk("Different angle", () => {
    const inEl = document.getElementById("input");
    if (inEl) { inEl.value = "Give a different angle on this."; inEl.focus(); }
  });
}

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
  const out = [];
  let labelled = false;
  let wrote = false;

  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    // Separate every non-empty line, labelled or not. Previously a plain line
    // after a labelled one lost its break, gluing the two together.
    if (wrote) out.push(document.createElement("br"));
    wrote = true;

    re.lastIndex = 0;
    const m = re.exec(line);
    if (!m || !m[1]) {
      // Preserve unlabelled text so nothing is silently dropped.
      out.push(document.createTextNode(line));
      continue;
    }
    labelled = true;
    const span = document.createElement("span");
    span.className = `lbl ${m[1].toUpperCase()}`;
    span.textContent = m[1].toUpperCase();
    out.push(span);
    out.push(document.createTextNode(line.replace(re, "").trim()));
  }

  // If the model ignored the label format entirely, fall back to plain text
  // so the user still sees the answer.
  if (!labelled) {
    out.length = 0;
    out.push(document.createTextNode(text));
  }
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
  // A question that came in by voice is answered out loud even if SPEAK
  // REPLIES is off, so tapping the mic gives a real voice assistant.
  const spokeQuestion = voiceInputPending;
  voiceInputPending = false;
  const speaker = opts.speaker || pendingSpeaker || null;
  pendingSpeaker = null;
  // Nothing should hang forever: a wedged provider or dead engine must not
  // leave the typing indicator up with the send button disabled. 240s covers
  // a cold on-device model start plus generation.
  const askCtl = ("AbortController" in window) ? new AbortController() : null;
  const askTimer = askCtl ? setTimeout(() => askCtl.abort(), 240000) : 0;
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        session,
        lang: settings.lang,
        reply_language: settings.replyLanguage,
        detail: settings.detail,
        speaker: speaker ? speaker.name : null,
        speaker_score: speaker ? speaker.score : null,
      }),
      signal: askCtl ? askCtl.signal : undefined,
    });
    if (!res.ok) throw new Error(`server returned ${res.status}`);
    const data = await res.json();
    removeTyping();
    addBot(data);
    lastBasis = data;
    renderBasis(data);
    renderReplyOptions(data);
    if (!opts.suppressSpeak && data.text && (settings.speak === "on" || spokeQuestion)) {
      speak(data.text, { lang: data.language });
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
    const timedOut = e && (e.name === "AbortError" || e.code === 20);
    const detail = timedOut
      ? "the engine took too long to answer (4 minutes) - try again"
      : e instanceof SyntaxError
        ? "Malformed response from server."
        : String(e.message || e);
    addBot({ text: `Request failed: ${detail}`, warnings: [] });
    lastBasis = null;
    renderBasis(null);
    renderReplyOptions(null);
    // Callers (the voice call and hands-free loop) need the reason, not just
    // a null, so the failure can be shown instead of looping silently.
    return { text: null, error: detail };
  } finally {
    clearTimeout(askTimer);
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
  // Typing takes over from a running hands-free conversation.
  if (handsFreeActive) stopHandsFree();
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

document.getElementById("mem-add")?.addEventListener("click", async () => {
  const text = prompt("New fact to remember:");
  if (text == null || !text.trim()) return;
  const res = await fetch("/api/facts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text: text.trim(), source: "manual" }),
  });
  if (!res.ok) {
    alert("Could not save that fact");
    return;
  }
  await searchMemory(memq.value || "");
});

// The right REST endpoint for a memory kind, or null if the kind is read-only.
function memoryEndpoint(kind) {
  const k = (kind || "").toLowerCase();
  if (k === "fact") return "/api/facts";
  if (k === "episode") return "/api/episodes";
  if (k === "rule") return "/api/rules";
  if (k === "learned") return "/api/learned";
  return null;
}

async function searchMemory(q) {
  const r = await fetch(`/api/memory?q=${encodeURIComponent(q)}&limit=25`);
  const { results } = await r.json();
  memResults.innerHTML = "";
  if (!results.length) {
    memResults.innerHTML = `<div class="mrow"><div class="t">No matching memory.</div></div>`;
    return;
  }
  for (const m of results) memResults.appendChild(memoryRow(m));
}

// One editable memory card. Facts/episodes/rules/learned can be edited and
// deleted in place; the change goes straight to the same API the assistant
// reads from, so the next reply reflects it.
function memoryRow(m) {
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

  const endpoint = memoryEndpoint(m.kind);
  if (!endpoint) return row;

  const actions = document.createElement("div");
  actions.className = "m";

  const edit = document.createElement("button");
  edit.className = "ghost small";
  edit.textContent = "EDIT";
  edit.addEventListener("click", () => {
    if (row.querySelector("textarea")) return;
    const box = document.createElement("textarea");
    box.className = "mem-edit";
    box.value = m.text || m.title || m.summary || "";
    t.replaceWith(box);
    box.focus();

    const save = document.createElement("button");
    save.className = "ghost small";
    save.textContent = "SAVE";
    save.addEventListener("click", async () => {
      const field = m.kind === "episode" ? "title" : "text";
      const body = {};
      body[field] = box.value;
      const res = await fetch(`${endpoint}/${m.id}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        m.text = box.value;
        m.title = box.value;
        t.textContent = box.value;
        box.replaceWith(t);
        save.remove();
        cancel.remove();
      } else {
        meta.textContent = "could not save";
      }
    });
    const cancel = document.createElement("button");
    cancel.className = "ghost small";
    cancel.textContent = "CANCEL";
    cancel.addEventListener("click", () => {
      box.replaceWith(t);
      save.remove();
      cancel.remove();
    });
    actions.append(save, cancel);
  });
  actions.appendChild(edit);

  const del = document.createElement("button");
  del.className = "ghost small";
  del.textContent = "DELETE";
  del.addEventListener("click", async () => {
    const res = await fetch(`${endpoint}/${m.id}`, { method: "DELETE" });
    if (res.ok) row.remove();
    else meta.textContent = "could not delete";
  });
  actions.appendChild(del);

  row.appendChild(actions);
  return row;
}

let memTimer;
memq.addEventListener("input", () => {
  clearTimeout(memTimer);
  memTimer = setTimeout(() => searchMemory(memq.value.trim()), 200);
});

/* insights sheet */
const iSheet = document.getElementById("insights-sheet");
const iBody = document.getElementById("insights-body");

document.getElementById("btn-insights").addEventListener("click", () => {
  iSheet.hidden = false;
  loadInsights();
});

async function loadInsights() {
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
      h.textContent = "CONFLICTING MEMORY - PICK THE ONE THAT HOLDS";
      iBody.appendChild(h);
      for (const c of d.contradictions) {
        const r = document.createElement("div");
        r.className = "mrow";
        const k = document.createElement("div");
        k.className = "k";
        k.textContent = c.subject || "claim";
        r.appendChild(k);
        // Two claims that cannot both be true. There is no verdict here; the
        // app only offers a way to settle it. "KEEP THIS" deletes the other
        // fact, so the surviving memory is the one the user actually trusts.
        for (const side of ["a", "b"]) {
          const other = side === "a" ? "b" : "a";
          const line = document.createElement("div");
          line.className = "t";
          line.textContent = c[side];
          const keep = document.createElement("button");
          keep.className = "ghost small";
          keep.textContent = "KEEP THIS";
          keep.style.marginLeft = "8px";
          keep.addEventListener("click", async () => {
            const otherId = c[`${other}_id`];
            if (otherId == null) return;
            if (!confirm(`Keep "${c[side]}" and forget "${c[other]}"?`)) return;
            keep.disabled = true;
            const res = await fetch(`/api/facts/${otherId}`, { method: "DELETE" });
            if (res.ok) loadInsights();
            else keep.textContent = "FAILED";
          });
          if (c[`${other}_id`] != null && c[`${side}_id`] != null) {
            line.appendChild(keep);
          }
          r.appendChild(line);
        }
        if (c.a_id != null && c.b_id != null) {
          const actions = document.createElement("div");
          actions.className = "m";
          // Neither button destroys evidence on its own: DISMISS only hides a
          // pair the person judged harmless, MERGE rewrites memory once with
          // wording the person wrote.
          const dismiss = document.createElement("button");
          dismiss.className = "ghost small";
          dismiss.textContent = "NOT A CONFLICT";
          dismiss.style.marginRight = "8px";
          dismiss.addEventListener("click", async () => {
            dismiss.disabled = true;
            const res = await fetch(
              `/api/insights/contradictions/${c.a_id}/${c.b_id}/review`,
              { method: "POST" },
            );
            if (res.ok) loadInsights();
            else dismiss.textContent = "FAILED";
          });
          const merge = document.createElement("button");
          merge.className = "ghost small";
          merge.textContent = "MERGE...";
          merge.addEventListener("click", async () => {
            const text = prompt("What should memory say after the merge?", c.a || "");
            if (text == null || !text.trim()) return;
            merge.disabled = true;
            const res = await fetch("/api/insights/contradictions/merge", {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({
                keep_id: c.a_id,
                remove_id: c.b_id,
                reconciled_text: text.trim(),
              }),
            });
            if (res.ok) loadInsights();
            else merge.textContent = "FAILED";
          });
          actions.append(dismiss, merge);
          r.appendChild(actions);
        }
        iBody.appendChild(r);
      }
    }
    await renderPlaces(iBody);
    if (!iBody.childNodes.length) iBody.textContent = "No history yet.";
  } catch {
    iBody.textContent = "Could not load insights.";
  }
}
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

  const chk = document.createElement("input");
  chk.type = "checkbox";
  chk.checked = decSelected.has(d.id);
  chk.addEventListener("change", () => {
    if (chk.checked) decSelected.add(d.id);
    else decSelected.delete(d.id);
    updateDecCount();
  });
  row.appendChild(chk);

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

  const del = document.createElement("button");
  del.className = "ghost small";
  del.textContent = "DELETE";
  del.addEventListener("click", async () => {
    if (!confirm(`Delete decision "${d.topic || "(untitled)"}"?`)) return;
    del.disabled = true;
    const res = await fetch(`/api/decisions/${d.id}`, { method: "DELETE" });
    if (!res.ok) {
      del.disabled = false;
      del.textContent = "FAILED";
      return;
    }
    row.remove();
  });
  row.appendChild(del);

  const ed = document.createElement("button");
  ed.className = "ghost small";
  ed.textContent = "EDIT";
  ed.addEventListener("click", () => openDecisionEditor(row, d));
  row.appendChild(ed);
  return row;
}

function openDecisionEditor(row, d) {
  if (row.querySelector(".dec-edit")) return;
  const box = document.createElement("div");
  box.className = "dec-edit";
  box.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;width:100%;margin-top:6px";
  const mkField = (label, value, type) => {
    const w = document.createElement("label");
    w.style.cssText = "font-size:.75rem;opacity:.85;display:flex;flex-direction:column;gap:2px";
    w.textContent = label;
    const i = document.createElement("input");
    i.value = value ?? "";
    if (type === "number") {
      i.type = "number";
      i.min = "0";
      i.max = "1";
      i.step = "0.05";
    } else if (type === "date") {
      i.type = "date";
    }
    w.appendChild(i);
    box.appendChild(w);
    return i;
  };
  const topicIn = mkField("TOPIC", d.topic, "text");
  const decIn = mkField("DECISION", d.decision, "text");
  const confIn = mkField("CONFIDENCE 0-1", d.confidence, "number");
  const revIn = mkField("REVIEW ON", d.review_date, "date");

  const save = document.createElement("button");
  save.className = "ghost small";
  save.textContent = "SAVE";
  const cancel = document.createElement("button");
  cancel.className = "ghost small";
  cancel.textContent = "CANCEL";
  cancel.addEventListener("click", () => box.remove());
  save.addEventListener("click", async () => {
    const body = {
      topic: topicIn.value.trim(),
      decision: decIn.value.trim(),
      review_date: revIn.value,
    };
    if (confIn.value !== "") {
      const c = Number(confIn.value);
      if (Number.isNaN(c) || c < 0 || c > 1) {
        alert("Confidence must be between 0 and 1");
        return;
      }
      body.confidence = c;
    }
    save.disabled = true;
    const res = await fetch(`/api/decisions/${d.id}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    save.disabled = false;
    if (!res.ok) {
      alert("Could not save that change");
      return;
    }
    await loadDecisions();
  });
  box.append(save, cancel);
  row.appendChild(box);
}

function updateDecCount() {
  const el = document.getElementById("dec-count");
  if (el) el.textContent = String(decSelected.size);
}

async function loadDecisions() {
  dBody.textContent = "loading...";
  try {
    const { due = [], open = [], resolved = [] } = await (await fetch("/api/decisions")).json();
    const dueIds = new Set(due.map((d) => d.id));
    decAll = [
      ...due.map((d) => ({ ...d, due: true })),
      ...open.filter((d) => !dueIds.has(d.id)).map((d) => ({ ...d, due: false })),
      ...resolved.map((d) => ({ ...d, due: false })),
    ];
    renderDecisions();
  } catch {
    dBody.textContent = "Could not load decisions.";
  }
}

function renderDecisions() {
  const filter = document.getElementById("dec-filter")?.value || "all";
  const q = (document.getElementById("dec-search")?.value || "").toLowerCase();
  const n = new Date();
  const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(
    n.getDate(),
  ).padStart(2, "0")}`;

  const matches = decAll.filter((d) => {
    if (filter === "due" && !d.due) return false;
    if (filter === "open" && d.resolved_at) return false;
    if (filter === "resolved" && !d.resolved_at) return false;
    // "overdue" is strictly past-due: due covers today, overdue does not.
    if (filter === "overdue" && !(d.due && d.review_date && d.review_date < today)) return false;
    if (q) {
      const hay = `${d.topic || ""} ${d.decision || ""} ${d.prediction || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  dBody.innerHTML = "";
  if (!matches.length) {
    dBody.textContent = decAll.length ? "Nothing matches that filter." : "Nothing open.";
    return;
  }
  let lastGroup = "";
  for (const d of matches) {
    const group = d.resolved_at ? "RESOLVED" : d.due ? "DUE FOR REVIEW" : "OPEN";
    if (group !== lastGroup) {
      const h = document.createElement("div");
      h.className = "ihead";
      h.textContent = group;
      dBody.appendChild(h);
      lastGroup = group;
    }
    dBody.appendChild(decisionCard(d, d.due));
  }
  updateDecCount();
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
document.getElementById("dec-filter")?.addEventListener("change", renderDecisions);
document.getElementById("dec-search")?.addEventListener("input", renderDecisions);
document.getElementById("dec-select-all")?.addEventListener("click", () => {
  for (const d of decAll) decSelected.add(d.id);
  updateDecCount();
  renderDecisions();
});
document.getElementById("dec-clear")?.addEventListener("click", () => {
  decSelected.clear();
  updateDecCount();
  renderDecisions();
});
document.getElementById("dec-bulk-delete")?.addEventListener("click", async () => {
  if (!decSelected.size) return;
  if (!confirm(`Delete ${decSelected.size} decision(s)? This cannot be undone.`)) return;
  for (const id of Array.from(decSelected)) {
    await fetch(`/api/decisions/${id}`, { method: "DELETE" });
  }
  decSelected.clear();
  updateDecCount();
  await loadDecisions();
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
let learnedSelected = new Set();
let learnedAll = [];

function updateLearnedSelCount() {
  const el = document.getElementById("learned-count");
  if (el) el.textContent = String(learnedSelected.size);
}

async function loadLearned(filter) {
  const f = filter || (document.getElementById("learned-filter")?.value) || "candidate";
  try {
    const res = await fetch(`/api/learned?status=${encodeURIComponent(f)}`);
    const data = await res.json();
    learnedAll = res.ok ? data.candidates || [] : [];
    learnedSelected.clear();
    updateLearnedSelCount();
    renderLearned();
    lSheet.hidden = false;
  } catch (e) {}
}

function renderLearned() {
  const q = (document.getElementById("learned-search")?.value || "").toLowerCase();
  if (!lBody) return;
  lBody.innerHTML = "";
  let items = learnedAll;
  if (q) items = items.filter(x => (x.text||"").toLowerCase().includes(q) || String(x.id).includes(q));
  for (const c of items) {
    const row = document.createElement("div");
    row.className = "mrow";
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = learnedSelected.has(c.id);
    chk.addEventListener("change", () => {
      if (chk.checked) learnedSelected.add(c.id); else learnedSelected.delete(c.id);
      updateLearnedSelCount();
    });
    const t = document.createElement("div");
    t.className = "t";
    t.style.flex = "1";
    t.textContent = c.text;
    const edit = document.createElement("input");
    edit.value = c.text;
    edit.style.display = "none";
    const btns = document.createElement("div");
    btns.className = "m";
    const bEdit = document.createElement("button");
    bEdit.className = "ghost small";
    bEdit.textContent = "EDIT";
    let editing = false;
    bEdit.addEventListener("click", async () => {
      if (!editing) {
        editing = true;
        t.style.display = "none";
        edit.style.display = "block";
        bEdit.textContent = "SAVE";
      } else {
        editing = false;
        await fetch(`/api/learned/${c.id}`, {method:"PUT", headers:{"content-type":"application/json"}, body: JSON.stringify({text: edit.value})});
        t.textContent = edit.value;
        t.style.display = "block";
        edit.style.display = "none";
        bEdit.textContent = "EDIT";
      }
    });
    for (const [label, act] of [["APPROVE", "approve"], ["REJECT", "reject"]]) {
      const b = document.createElement("button");
      b.className = "ghost small";
      b.textContent = label;
      b.addEventListener("click", async () => {
        await fetch(`/api/learned/${c.id}/${act}`, { method: "POST" });
        await loadLearned();
      });
      btns.appendChild(b);
    }
    const bDel = document.createElement("button");
    bDel.className = "ghost small";
    bDel.textContent = "DEL";
    bDel.addEventListener("click", async () => {
      await fetch(`/api/learned/${c.id}`, { method: "DELETE" });
      await loadLearned();
    });
    btns.appendChild(bDel);
    btns.appendChild(bEdit);
    row.append(chk, t, edit, btns);
    lBody.appendChild(row);
  }
}

async function refreshLearned() {
  await loadLearned();
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
const lf = document.getElementById("learned-filter");
if (lf) lf.addEventListener("change", () => loadLearned(lf.value));
const ls = document.getElementById("learned-search");
if (ls) ls.addEventListener("input", () => renderLearned());
const lsa = document.getElementById("learned-select-all");
if (lsa) lsa.addEventListener("click", () => {
  for (const it of learnedAll) learnedSelected.add(it.id);
  updateLearnedSelCount();
  renderLearned();
});
const lsc = document.getElementById("learned-clear");
if (lsc) lsc.addEventListener("click", () => {
  learnedSelected.clear();
  updateLearnedSelCount();
  renderLearned();
});
const lap = document.getElementById("learned-approve");
if (lap) lap.addEventListener("click", async () => {
  if (!learnedSelected.size) return;
  await fetch("/api/learned/bulk", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({action:"approve", ids:Array.from(learnedSelected)})});
  await loadLearned();
});
const lrj = document.getElementById("learned-reject");
if (lrj) lrj.addEventListener("click", async () => {
  if (!learnedSelected.size) return;
  await fetch("/api/learned/bulk", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({action:"reject", ids:Array.from(learnedSelected)})});
  await loadLearned();
});
const ldel = document.getElementById("learned-delete");
if (ldel) ldel.addEventListener("click", async () => {
  if (!learnedSelected.size) return;
  if (!confirm("Delete selected learned?")) return;
  await fetch("/api/learned/bulk", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({action:"delete", ids:Array.from(learnedSelected)})});
  await loadLearned();
});
const lrf = document.getElementById("learned-refresh");
if (lrf) lrf.addEventListener("click", () => loadLearned());

/* WhatsApp import (propose-then-approve) */
let waPreviewItems = [];
let waSelected = new Set(); // key "msg_id:chat_id"

async function loadWhatsAppStatus() {
  const statusEl = document.getElementById("wa-status");
  const chatsEl = document.getElementById("wa-chats");
  if (!statusEl || !chatsEl) return;
  statusEl.textContent = "loading...";
  chatsEl.innerHTML = "";
  try {
    const res = await fetch("/api/import/whatsapp/status");
    const s = await res.json();
    if (!s.exists) {
      statusEl.textContent = s.error || "WhatsApp Desktop DB not found in common macOS locations.";
      chatsEl.innerHTML = "";
      return;
    }
    const sz = s.size ? `(${Math.round(s.size/1024/1024)}MB)` : "";
    statusEl.textContent = `Found: ${s.path} ${sz}. Chats: ${s.chats?.length || 0}`;
    for (const c of s.chats || []) {
      const row = document.createElement("label");
      row.style.display = "flex";
      row.style.alignItems = "center";
      row.style.gap = ".5rem";
      row.style.margin = ".25rem 0";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.name = "wa-chat";
      cb.value = c.chat_id;
      cb.checked = true;
      const label = document.createElement("span");
      label.textContent = `${c.chat_name} · ${c.msg_count}`;
      row.append(cb, label);
      chatsEl.appendChild(row);
    }
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
  }
}

async function previewWhatsApp() {
  const wrap = document.getElementById("wa-preview-wrap");
  const meta = document.getElementById("wa-preview-meta");
  const stageBtn = document.getElementById("wa-stage");
  if (!wrap || !meta) return;
  wrap.innerHTML = "";
  meta.textContent = "loading...";
  if (stageBtn) stageBtn.style.display = "none";
  waSelected.clear();
  waPreviewItems = [];
  const checks = Array.from(document.querySelectorAll('input[name="wa-chat"]:checked'));
  const chat_ids = checks.map((x) => parseInt(x.value)).filter((n) => !isNaN(n));
  const from_me = document.getElementById("wa-fromme")?.checked;
  const body = {
    chat_ids: chat_ids.length ? chat_ids : null,
    from_me: from_me ? true : null,
    limit: 50,
    offset: 0,
  };
  try {
    const res = await fetch("/api/import/whatsapp/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!data.items || !data.items.length) {
      meta.textContent = "No messages found.";
      return;
    }
    waPreviewItems = data.items;
    meta.textContent = `Showing ${data.items.length} of ${data.total}`;
    const table = document.createElement("table");
    table.style.width = "100%";
    table.style.fontSize = ".9rem";
    table.innerHTML = "<thead><tr><th></th><th>Time</th><th>Chat</th><th>Me</th><th>Text</th></tr></thead>";
    const tbody = document.createElement("tbody");
    for (const it of data.items) {
      const tr = document.createElement("tr");
      const key = it.msg_id + ":" + it.chat_id;
      const td1 = document.createElement("td");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.dataset.key = key;
      cb.dataset.item = JSON.stringify(it);
      cb.addEventListener("change", () => {
        if (cb.checked) waSelected.add(key); else waSelected.delete(key);
        updateWaStageBtn();
      });
      td1.appendChild(cb);
      const td2 = document.createElement("td");
      td2.textContent = it.when ? it.when.substring(0, 16) : "—";
      const td3 = document.createElement("td");
      td3.textContent = it.chat_name || "";
      const td4 = document.createElement("td");
      td4.textContent = it.from_me ? "Y" : "N";
      const td5 = document.createElement("td");
      td5.textContent = (it.text || "").length > 120 ? (it.text || "").substring(0, 120) + "…" : (it.text || "");
      tr.append(td1, td2, td3, td4, td5);
      tbody.appendChild(tr);
      waSelected.add(key);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
    updateWaStageBtn();
  } catch (e) {
    meta.textContent = `Error: ${e.message}`;
  }
}

function updateWaStageBtn() {
  const btn = document.getElementById("wa-stage");
  if (!btn) return;
  btn.style.display = waSelected.size > 0 ? "inline-block" : "none";
  const meta = document.getElementById("wa-stage-meta");
  if (meta) meta.textContent = waSelected.size ? `${waSelected.size} selected` : "";
}

async function stageWhatsApp() {
  if (waSelected.size === 0) {
    alert("No items selected");
    return;
  }
  const items = [];
  const checks = Array.from(document.querySelectorAll('#wa-preview-wrap input[type="checkbox"]'));
  for (const cb of checks) {
    if (cb.checked && cb.dataset.key) {
      try {
        items.push(JSON.parse(cb.dataset.item || "{}"));
      } catch { /* ignore */ }
    }
  }
  if (items.length === 0) {
    alert("No items selected");
    return;
  }
  const btn = document.getElementById("wa-stage");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/import/whatsapp/stage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    const data = await res.json();
    alert(`Staged ${data.staged}, skipped ${data.skipped?.length || 0}`);
    if (typeof refreshLearnedIfAny === "function") refreshLearnedIfAny();
    // switch to learned sheet if exists
    const lSheet = document.getElementById("learned-sheet");
    if (lSheet) {
      lSheet.hidden = false;
      if (typeof refreshLearned === "function") refreshLearned();
    }
    const wrap = document.getElementById("wa-preview-wrap");
    if (wrap) wrap.innerHTML = "";
    waSelected.clear();
    if (btn) { btn.style.display = "none"; btn.disabled = false; }
    const meta = document.getElementById("wa-stage-meta");
    if (meta) meta.textContent = "";
  } catch (e) {
    alert(`Error: ${e.message}`);
    if (btn) btn.disabled = false;
  }
}

document.getElementById("btn-import")?.addEventListener("click", () => {
  const dataSheet = document.getElementById("data-sheet");
  if (dataSheet) { dataSheet.hidden = false; showDataTab("import"); loadWhatsAppStatus(); }
});
document.getElementById("wa-preview")?.addEventListener("click", previewWhatsApp);
document.getElementById("wa-stage")?.addEventListener("click", stageWhatsApp);
document.getElementById("wa-selectall")?.addEventListener("click", () => {
  document.querySelectorAll('#wa-preview-wrap input[type="checkbox"]').forEach((cb) => {
    cb.checked = true;
    if (cb.dataset.key) waSelected.add(cb.dataset.key);
  });
  updateWaStageBtn();
});
document.getElementById("wa-clear")?.addEventListener("click", () => {
  document.querySelectorAll('#wa-preview-wrap input[type="checkbox"]').forEach((cb) => {
    cb.checked = false;
    if (cb.dataset.key) waSelected.delete(cb.dataset.key);
  });
  updateWaStageBtn();
});

/* ------------------------------------------------------------- settings */

// Snapshot of the built-in defaults so RESET can restore them in memory as
// well as on the server.
const SETTINGS_DEFAULTS = {
  lang: "en",
  replyLanguage: "auto",
  speak: "off",
  handsfree: "off",
  voice: "",
  stt: "en-US",
  sttEngine: "auto",
  detail: "normal",
  accent: "",
  theme: "dark",
};
const settings = { ...SETTINGS_DEFAULTS };

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
    uploaded: "Read and saved to memory.",
    uploadedStored: "Saved. This file type can't be read as text.",
    uploadedNoOcr: "Saved. OCR isn't installed, so images/scans can't be read yet.",
    uploadedNoVision: "Saved. Images and scans need a vision provider - add a Gemini key in Settings.",
    uploadFailed: "Upload failed. The file may be too large (max 25 MB).",
    saved: "Settings saved.",
    offlineReady: "On-device speech is installed. The mic and calls work offline, including Urdu.",
    offlineMissing: "On-device speech isn't installed. Browser speech needs an internet connection.",
  },
  ur: {
    placeholder: "پوچھیں۔ عاطف اسسٹنٹ خود جواب دے گا۔",
    related: "یہ فائل کس بارے میں ہے؟ (مثلاً ریزیومے، پروجیکٹ، نوٹ)",
    uploading: "اپ لوڈ ہو رہا ہے...",
    uploaded: "پڑھ کر یادداشت میں محفوظ ہو گیا۔",
    uploadedStored: "محفوظ ہو گیا، مگر اس قسم کی فائل پڑھی نہیں جا سکتی۔",
    uploadedNoOcr: "محفوظ ہو گیا۔ تصویریں پڑھنے کے لیے OCR انسٹال نہیں ہے۔",
    uploadedNoVision: "محفوظ ہو گیا۔ تصویر یا اسکین پڑھنے کے لیے سیٹنگز میں Gemini کلید شامل کریں۔",
    uploadFailed: "اپ لوڈ ناکام۔ فائل بہت بڑی ہو سکتی ہے (زیادہ سے زیادہ 25 MB)۔",
    saved: "سیٹنگز محفوظ ہو گئیں۔",
    offlineReady: "آن ڈیوائس آواز انسٹال ہے۔ مائیک اور کال بغیر انٹرنیٹ، اردو میں بھی، کام کرتے ہیں۔",
    offlineMissing: "آن ڈیوائس آواز انسٹال نہیں ہے۔ براؤزر کی آواز کے لیے انٹرنیٹ درکار ہے۔",
  },
};

async function loadSettings() {
  try {
    const saved = await (await fetch("/api/settings")).json();
    for (const k of Object.keys(settings)) {
      if (saved[k] != null && saved[k] !== "") settings[k] = saved[k];
    }
    // reply_language is stored in snake_case (it is also a request field), but
    // the local setting is camelCase. Without this the saved choice is lost on
    // every reload and /api/ask then clobbers the server default back to "auto".
    if (saved.reply_language != null && saved.reply_language !== "") {
      settings.replyLanguage = saved.reply_language;
    }
  } catch {
    /* defaults are fine */
  }
  // Heal a stored mismatch: Urdu replies with the untouched default English
  // microphone would prevent anyone from speaking Urdu at all.
  if (settings.lang === "ur" && settings.stt === "en-US") settings.stt = "ur-PK";
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
    reply_language: settings.replyLanguage,
    speak: settings.speak,
    handsfree: settings.handsfree,
    voice: settings.voice,
    stt: settings.stt,
    sttEngine: settings.sttEngine,
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

// The spoken language follows the reply, not the microphone. When the server
// tells us the reply language we use it; otherwise we fall back to the setting,
// and finally to a script test on the text itself so an Urdu answer is never
// read by an English voice.
function speechLang(replyLang) {
  if (replyLang) return replyLang === "ur" ? "ur-PK" : "en-US";
  return settings.lang === "ur" || settings.replyLanguage === "ur" ? "ur-PK" : "en-US";
}

const URDU_RE = /[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]/;
function looksUrdu(text) {
  return URDU_RE.test(String(text || ""));
}

function pickVoice(lang) {
  const pref = lang.slice(0, 2).toLowerCase();
  const norm = (v) => (v.lang || "").replace("_", "-").toLowerCase();
  const chosen = settings.voice && voices.find((v) => v.name === settings.voice);
  const exact = voices.find((v) => norm(v).startsWith(lang.toLowerCase()));
  const anyPref = voices.find((v) => norm(v).startsWith(pref));
  // Honour an explicit voice only when it matches the language we need to
  // speak. Otherwise an English voice chosen earlier would read Urdu text -
  // the words come out but in the wrong language.
  if (chosen && norm(chosen).startsWith(pref)) return chosen;
  return exact || anyPref || chosen || null;
}

function hasVoiceFor(lang) {
  const pref = lang.slice(0, 2);
  return voices.some((v) => (v.lang || "").replace("_", "-").startsWith(pref));
}

let currentAudio = null;
let speechToken = 0;
let voiceInputPending = false;
let pendingSpeaker = null;

// Stop any speech in progress, whichever engine is producing it.
function stopSpeech() {
  speechToken += 1;
  try {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
  if (currentAudio) {
    try {
      currentAudio.pause();
    } catch {
      /* ignore */
    }
    if (currentAudio.__url) URL.revokeObjectURL(currentAudio.__url);
    currentAudio = null;
  }
}

// Play a server-synthesized clip. Resolves true once it has played to the end,
// false if it could not play (no key, quota, autoplay blocked) so the caller
// can fall back to a device voice.
function playServerClip(text, onDone, lang) {
  const token = speechToken;
  return fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, lang: lang || speechLang() }),
  })
    .then((res) => (res.ok ? res.blob() : null))
    .then(
      (blob) =>
        new Promise((resolve) => {
          if (!blob || !blob.size || token !== speechToken) {
            resolve(false);
            return;
          }
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          audio.__url = url;
          let settled = false;
          const finish = (played) => {
            if (settled) return;
            settled = true;
            URL.revokeObjectURL(url);
            if (currentAudio === audio) currentAudio = null;
            if (played) onDone();
            resolve(played);
          };
          currentAudio = audio;
          audio.onended = () => finish(true);
          audio.onerror = () => finish(false);
          audio.play().then(
            () => {},
            () => finish(false)
          );
        })
    )
    .catch(() => false);
}

async function speak(text, opts = {}) {
  if (!opts.force && settings.speak !== "on") return;
  if (!text) return;
  const clean = String(text).replace(/\[(FACT|INFERENCE|ASSUMPTION|UNKNOWN|PREDICTION)\]/gi, "").trim();
  if (!clean) {
    if (opts.onEnd) opts.onEnd();
    return;
  }

  // onEnd must fire exactly once, whichever engine finishes first.
  const myToken = speechToken;
  let ended = false;
  let safety = null;
  const done = () => {
    if (ended) return;
    ended = true;
    clearTimeout(safety);
    if (opts.onEnd) opts.onEnd();
  };

  // The reply language decides the voice; a script test is the final guard so
  // Urdu-script text is never spoken by an English voice.
  const replyLang = opts.lang || (looksUrdu(clean) ? "ur" : null);
  const lang = speechLang(replyLang);
  const words = clean.split(/\s+/).filter(Boolean).length;
  // Server speech needs generation time; the device engine should answer far
  // sooner. Either way, release a call stuck in SPEAKING if nothing arrives.
  safety = setTimeout(() => {
    stopSpeech();
    done();
  }, Math.min(Math.max(words * 700 + 9000, 12000), 150000));

  // Inside the Android app native TTS is the only engine; there is no
  // completion callback, so the safety timer releases the loop.
  if (window.AndroidVoice && typeof window.AndroidVoice.speak === "function") {
    try {
      window.AndroidVoice.speak(clean, lang);
      return;
    } catch {
      /* fall through to the web engine */
    }
  }

  const hasWeb = "speechSynthesis" in window;
  const urdu = lang.startsWith("ur");
  // A typical device has no Urdu voice, so speaking Urdu locally comes out as
  // English gibberish. Use the server whenever the language has no local voice.
  const needServer =
    opts.server === true || !hasWeb || urdu || (voices.length > 0 && !hasVoiceFor(lang));
  if (needServer) {
    const played = await playServerClip(clean, done, lang);
    if (played) return;
    // Cancelled (barge-in) or already released - do not start another engine.
    if (myToken !== speechToken || ended) return;
  }

  if (!hasWeb) {
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
    // A spoken question should be answered out loud, even if SPEAK REPLIES is
    // off, so the voice assistant actually talks back.
    voiceInputPending = true;
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

  // Hands-free mode turns the mic into a live conversation: a tap starts
  // listening, and it keeps answering out loud and listening again until you
  // tap it once more.
  if (settings.handsfree === "on") {
    if (handsFreeActive) stopHandsFree();
    else startHandsFree();
    return;
  }

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

  // Offline / on-device recognition (whisper.cpp on the server). Tap to start,
  // tap again to stop; it also stops by itself once you finish a sentence.
  if (wantLocalStt()) {
    if (localMicRec) stopLocalMic();
    else startLocalMic();
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

/* ------------------------------------------------- offline speech input */

// The browser's SpeechRecognition sends audio to Google, so it needs a network.
// When whisper.cpp is installed on the server we record a clip and transcribe it
// there instead, which is what lets the mic and the call work with no internet
// and in Urdu.
let localSttReady = false;
let localMicRec = null;

function wantLocalStt() {
  if (settings.sttEngine === "local") return true;
  if (settings.sttEngine === "browser") return false;
  return localSttReady; // "auto": use the offline engine when it is installed
}

function browserSttAvailable() {
  return Boolean(
    (window.SpeechRecognition || window.webkitSpeechRecognition) ||
      (window.AndroidVoice && typeof window.AndroidVoice.listen === "function")
  );
}

function pcmToWav(chunks, sampleRate) {
  let length = 0;
  for (const c of chunks) length += c.length;
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const writeStr = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const c of chunks) {
    for (let i = 0; i < c.length; i++) {
      const s = Math.max(-1, Math.min(1, c[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }
  return new Blob([view], { type: "audio/wav" });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.onerror = () => reject(new Error("could not read the recording"));
    reader.readAsDataURL(blob);
  });
}

async function transcribeLocal(blob) {
  const b64 = await blobToBase64(blob);
  const res = await fetch("/api/stt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio: b64, lang: settings.stt }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  const data = await res.json();
  return { text: (data.text || "").trim(), speaker: data.speaker || null };
}

// Show who the assistant thinks is speaking, as a short-lived, clearly-advisory
// badge. The voice match is a guess, so it is never presented as a fact.
let voiceWhoTimer = null;
function showSpeaker(speaker) {
  const el = document.getElementById("voice-who");
  if (!el) return;
  clearTimeout(voiceWhoTimer);
  if (speaker && speaker.name) {
    const pct = Math.round((speaker.score || 0) * 100);
    const unsure = speaker.known === false ? " (unsure)" : "";
    el.textContent = `🎙️ ${speaker.name}${unsure} · voice ${pct}%`;
    el.hidden = false;
    voiceWhoTimer = setTimeout(() => { el.hidden = true; }, 6000);
  } else {
    el.hidden = true;
    el.textContent = "";
  }
}

// Record 16 kHz mono audio into a WAV the server can transcribe. A simple
// energy test tracks whether the user has started and finished speaking.
function createLocalRecorder() {
  const rec = {
    stream: null,
    ctx: null,
    source: null,
    proc: null,
    gain: null,
    chunks: [],
    sampleRate: 16000,
    running: false,
    speaking: false,
    started: 0,
    lastVoice: 0,
    onTick: null,
  };
  rec.start = async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("microphone not available");
    }
    rec.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const AC = window.AudioContext || window.webkitAudioContext;
    rec.ctx = new AC({ sampleRate: 16000 });
    rec.sampleRate = rec.ctx.sampleRate || 16000;
    rec.source = rec.ctx.createMediaStreamSource(rec.stream);
    rec.proc = rec.ctx.createScriptProcessor(4096, 1, 1);
    rec.chunks = [];
    rec.running = true;
    rec.speaking = false;
    rec.started = performance.now();
    rec.lastVoice = rec.started;
    rec.proc.onaudioprocess = (e) => {
      if (!rec.running) return;
      const ch = e.inputBuffer.getChannelData(0);
      rec.chunks.push(new Float32Array(ch));
      let sum = 0;
      for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i];
      const rms = Math.sqrt(sum / ch.length);
      if (rms > 0.012) {
        rec.speaking = true;
        rec.lastVoice = performance.now();
      }
      if (rec.onTick) rec.onTick(rec, rms);
    };
    rec.source.connect(rec.proc);
    // ScriptProcessor only runs while connected to a destination, but sending
    // the mic straight there would echo every word through the speakers and the
    // recogniser would hear itself. Route it through a muted gain instead.
    rec.gain = rec.ctx.createGain();
    rec.gain.gain.value = 0;
    rec.proc.connect(rec.gain);
    rec.gain.connect(rec.ctx.destination);
  };
  rec.stop = async () => {
    if (!rec.running) return null;
    rec.running = false;
    try { rec.proc.disconnect(); } catch { /* ignore */ }
    try { rec.gain.disconnect(); } catch { /* ignore */ }
    try { rec.source.disconnect(); } catch { /* ignore */ }
    try { rec.stream.getTracks().forEach((t) => t.stop()); } catch { /* ignore */ }
    try { await rec.ctx.close(); } catch { /* ignore */ }
    return pcmToWav(rec.chunks, rec.sampleRate);
  };
  return rec;
}

function fallBackToBrowserMic() {
  if (!recognizer) recognizer = setupRecognizer();
  if (!recognizer) return;
  recognizer.lang = settings.stt;
  try {
    recognizer.start();
    listening = true;
    mic?.classList.add("active");
  } catch {
    listening = false;
  }
}

async function startLocalMic() {
  if (localMicRec) return;
  let rec;
  try {
    rec = createLocalRecorder();
    await rec.start();
  } catch (err) {
    if (browserSttAvailable()) {
      fallBackToBrowserMic();
      return;
    }
    alert("Microphone unavailable: " + err.message);
    return;
  }
  localMicRec = rec;
  mic?.classList.add("active");
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    stopLocalMic();
  };
  rec.onTick = (r) => {
    const now = performance.now();
    const dur = (now - r.started) / 1000;
    if (dur > 15 || (r.speaking && now - r.lastVoice > 1100) || (!r.speaking && dur > 7)) {
      finish();
    }
  };
}

async function stopLocalMic() {
  const rec = localMicRec;
  if (!rec) return;
  localMicRec = null;
  mic?.classList.remove("active");
  const blob = await rec.stop();
  if (!blob || blob.size < 100) return;
  let text = "";
  let speaker = null;
  try {
    ({ text, speaker } = await transcribeLocal(blob));
  } catch (err) {
    if (browserSttAvailable()) {
      fallBackToBrowserMic();
      return;
    }
    alert("Offline speech failed: " + err.message);
    return;
  }
  if (text) {
    input.value = text;
    input.focus();
    voiceInputPending = true;
    pendingSpeaker = speaker;
    showSpeaker(speaker);
  }
}

/* ------------------------------------------------------------- voice call */

const callSheet = document.getElementById("call-sheet");
const callStateEl = document.getElementById("call-state");
const callTranscriptEl = document.getElementById("call-transcript");
const callHeardEl = document.getElementById("call-heard");
const callOrb = document.getElementById("call-orb");
const callBtn = document.getElementById("btn-call");
const endCallBtn = document.getElementById("end-call");

const CALL_LABEL = { listening: "LISTENING", thinking: "THINKING", speaking: "SPEAKING" };
let callActive = false;
let callPhase = "idle"; // listening | thinking | speaking
let callRecognizer = null;
let callLocalRec = null;
let callLocalBusy = false;
let callGotResult = false;
let callRetry = null;
let callResumeTimer = null;
let callErrorStreak = 0;

function callSupported() {
  // The offline engine makes a call possible even in browsers with no built-in
  // speech recognition.
  if (wantLocalStt()) return true;
  return Boolean(
    (window.SpeechRecognition || window.webkitSpeechRecognition) ||
      (window.AndroidVoice && typeof window.AndroidVoice.listen === "function")
  );
}

function callSetPhase(phase) {
  callPhase = phase;
  if (!callSheet) return;
  callSheet.classList.remove("listening", "thinking", "speaking");
  callSheet.classList.add(phase);
  if (callStateEl) callStateEl.textContent = CALL_LABEL[phase] || "";
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
  // Always release the offline recorder's busy flag, or a new call after END
  // would find the loop "busy" and never listen again.
  callLocalBusy = false;
  if (callLocalRec) {
    try {
      callLocalRec.stop();
    } catch {
      /* already stopped */
    }
    callLocalRec = null;
  }
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
  if (callActive || !callSheet) return;
  if (!callSupported()) {
    alert(
      "Voice calls need speech recognition, which this browser does not " +
        "support. On phones, open the app over HTTPS (or localhost) in Chrome, " +
        "Edge or Safari and allow the microphone."
    );
    return;
  }
  callErrorStreak = 0;
  // A call and the hands-free loop must never run together.
  if (handsFreeActive) stopHandsFree();
  // The one-shot mic and the call must never run together.
  if (listening && recognizer) {
    try { recognizer.stop(); } catch { /* ignore */ }
  }
  stopSpeech();
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
  stopSpeech();
  if (window.AndroidVoice && typeof window.AndroidVoice.stop === "function") {
    try { window.AndroidVoice.stop(); } catch { /* ignore */ }
  }
  if (callSheet) callSheet.hidden = true;
}

function callListen() {
  if (!callActive) return;
  if (wantLocalStt()) {
    callListenLocal();
    return;
  }
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

async function callListenLocal() {
  if (!callActive || callLocalBusy || callLocalRec) return;
  callLocalBusy = true;
  clearTimeout(callRetry);
  callGotResult = false;
  callSetPhase("listening");
  callTranscriptEl.textContent = "";
  callHeardEl.textContent = "Listening…";

  let rec;
  try {
    rec = createLocalRecorder();
    await rec.start();
  } catch (err) {
    callLocalBusy = false;
    // If "auto" picked offline and the mic is the problem, retry once online.
    if (
      settings.sttEngine === "auto" &&
      (window.SpeechRecognition || window.webkitSpeechRecognition)
    ) {
      settings.sttEngine = "browser";
      callListen();
      return;
    }
    callTranscriptEl.textContent = "Microphone unavailable: " + err.message;
    endCall();
    return;
  }
  if (!callActive) {
    try {
      rec.stop();
    } catch {
      /* ignore */
    }
    callLocalBusy = false;
    return;
  }
  callLocalRec = rec;

  let finished = false;
  const finish = async () => {
    if (finished) return;
    finished = true;
    callLocalRec = null;
    const blob = await rec.stop();
    callLocalBusy = false;
    if (!callActive) return;
    if (!blob || blob.size < 100) {
      // Nothing recorded: arm the next turn directly. callResume() would be a
      // no-op here because the phase is still "listening".
      callRetry = setTimeout(() => {
        if (callActive) callListen();
      }, 350);
      return;
    }
    let text = "";
    let speaker = null;
    try {
      ({ text, speaker } = await transcribeLocal(blob));
    } catch (err) {
      if (!callActive) return;
      callTranscriptEl.textContent = "Offline speech failed: " + err.message;
      callRetry = setTimeout(() => {
        if (callActive) callListen();
      }, 600);
      return;
    }
    if (!callActive) return;
    if (text) callSubmit(text, speaker);
    else callResume();
  };

  rec.onTick = (r, rms) => {
    const now = performance.now();
    const dur = (now - r.started) / 1000;
    if (rms > 0.012) callHeardEl.textContent = "Hearing you…";
    if (dur > 20 || (r.speaking && now - r.lastVoice > 1100) || (!r.speaking && dur > 8)) {
      finish();
    }
  };
}

async function callSubmit(text, speaker) {
  if (!callActive) return;
  stopCallRecognition();
  callTranscriptEl.textContent = text;
  callHeardEl.textContent = "";
  callSetPhase("thinking");

  const data = await ask(text, { suppressSpeak: true, speaker });
  if (!callActive) return;
  if (!data || !data.text) {
    // Never loop silently: show why the answer never came, then keep listening.
    callTranscriptEl.textContent = data?.error || "No answer. Try again.";
    callResume();
    return;
  }
  callSetPhase("speaking");
  speak(data.text, { force: true, lang: data.language, onEnd: callResume });
}

if (callBtn) callBtn.addEventListener("click", startCall);
if (endCallBtn) endCallBtn.addEventListener("click", endCall);
// Tap the orb to barge in while the answer is being spoken.
if (callOrb) {
  callOrb.addEventListener("click", () => {
    if (callActive && callPhase === "speaking") {
      stopSpeech();
      callResume();
    }
  });
}

/* --------------------------------------------------------- hands-free chat */

// With HANDS-FREE CHAT on, a tap on the mic starts a live conversation in the
// normal chat: it listens, answers out loud, then listens again, and keeps
// going until you tap the mic once more. It reuses the same engines as the call
// (offline whisper.cpp, the Android bridge, or the browser recogniser) and shows
// its state in the composer hint line.
const hintEl = document.getElementById("hint");
let handsFreeActive = false;
let handsFreePhase = "idle";
let handsFreeRec = null;
let handsFreeRecognizer = null;
let handsFreeRetry = null;
let handsFreeBusy = false;
let handsFreeGotResult = false;
let handsFreeHintDefault = null;

function setHandsFreePhase(phase) {
  handsFreePhase = phase;
  if (handsFreeHintDefault === null) handsFreeHintDefault = hintEl ? hintEl.textContent : "";
  const btn = mic;
  const on = phase !== "idle";
  btn?.classList.toggle("active", on);
  if (btn) btn.setAttribute("data-phase", phase);
  if (!hintEl) return;
  if (phase === "idle") {
    hintEl.textContent = handsFreeHintDefault;
  } else if (phase === "listening") {
    hintEl.textContent = "Listening… (tap the mic to stop)";
  } else if (phase === "thinking") {
    hintEl.textContent = "Thinking…";
  } else if (phase === "error") {
    hintEl.textContent = "No answer. Listening again…";
  } else {
    hintEl.textContent = "Speaking… (tap the mic to stop)";
  }
  if (btn) {
    btn.title = on ? "Stop hands-free chat" : settings.handsfree === "on" ? "Start hands-free chat" : "Speak";
  }
}

function startHandsFree() {
  if (handsFreeActive) return;
  // The one-shot mic and the hands-free loop must never run together.
  if (listening && recognizer) {
    try { recognizer.stop(); } catch { /* ignore */ }
  }
  stopSpeech();
  handsFreeActive = true;
  setHandsFreePhase("listening");
  handsFreeListen();
}

function stopHandsFree() {
  handsFreeActive = false;
  handsFreeBusy = false;
  clearTimeout(handsFreeRetry);
  if (handsFreeRec) {
    try { handsFreeRec.stop(); } catch { /* ignore */ }
    handsFreeRec = null;
  }
  if (handsFreeRecognizer) {
    try {
      handsFreeRecognizer.onend = null;
      handsFreeRecognizer.onresult = null;
      handsFreeRecognizer.onerror = null;
      handsFreeRecognizer.stop();
    } catch { /* ignore */ }
    handsFreeRecognizer = null;
  }
  if (window.AndroidVoice && typeof window.AndroidVoice.stop === "function") {
    try { window.AndroidVoice.stop(); } catch { /* ignore */ }
  }
  stopSpeech();
  setHandsFreePhase("idle");
}

function handsFreeResume() {
  if (!handsFreeActive) return;
  clearTimeout(handsFreeRetry);
  handsFreeRetry = setTimeout(() => {
    if (handsFreeActive && handsFreePhase !== "listening") handsFreeListen();
  }, 400);
}

function handsFreeListen() {
  if (!handsFreeActive) return;
  setHandsFreePhase("listening");
  if (wantLocalStt()) {
    handsFreeListenLocal();
    return;
  }

  if (window.AndroidVoice && typeof window.AndroidVoice.listen === "function") {
    window.onAndroidSpeechResult = (text) => {
      if (!handsFreeActive) return;
      const said = (text || "").trim();
      if (said) handsFreeSubmit(said);
      else handsFreeResume();
    };
    try {
      window.AndroidVoice.listen(settings.stt);
    } catch {
      handsFreeResume();
    }
    return;
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    stopHandsFree();
    return;
  }
  let r;
  try {
    r = new SR();
  } catch {
    stopHandsFree();
    return;
  }
  handsFreeRecognizer = r;
  handsFreeGotResult = false;
  r.lang = settings.stt;
  r.continuous = false;
  r.interimResults = false;
  r.maxAlternatives = 1;
  r.onresult = (e) => {
    if (!handsFreeActive) return;
    const said = (e.results[0][0].transcript || "").trim();
    if (said) {
      handsFreeGotResult = true;
      handsFreeSubmit(said);
    } else {
      handsFreeResume();
    }
  };
  r.onerror = (e) => {
    if (!handsFreeActive) return;
    const err = e.error || "unknown";
    // Silence and our own aborts are normal; onend re-arms the mic.
    if (err === "no-speech" || err === "aborted") return;
    if (err === "not-allowed" || err === "service-not-allowed") stopHandsFree();
  };
  r.onend = () => {
    if (!handsFreeActive || handsFreeGotResult) return;
    if (handsFreePhase === "listening") handsFreeResume();
  };
  try {
    r.start();
  } catch {
    handsFreeResume();
  }
}

async function handsFreeListenLocal() {
  if (!handsFreeActive || handsFreeBusy || handsFreeRec) return;
  handsFreeBusy = true;
  let rec;
  try {
    rec = createLocalRecorder();
    await rec.start();
  } catch {
    handsFreeBusy = false;
    // If "auto" picked offline and the mic is the problem, retry once online.
    if (settings.sttEngine === "auto" && (window.SpeechRecognition || window.webkitSpeechRecognition)) {
      settings.sttEngine = "browser";
      handsFreeListen();
      return;
    }
    stopHandsFree();
    return;
  }
  if (!handsFreeActive) {
    try { rec.stop(); } catch { /* ignore */ }
    handsFreeBusy = false;
    return;
  }
  handsFreeRec = rec;
  const finish = async () => {
    const live = handsFreeRec;
    if (!live) return;
    handsFreeRec = null;
    const blob = await live.stop();
    handsFreeBusy = false;
    if (!handsFreeActive) return;
    if (!blob || blob.size < 100) {
      handsFreeResume();
      return;
    }
    try {
      const { text, speaker } = await transcribeLocal(blob);
      if (!handsFreeActive) return;
      if (text) handsFreeSubmit(text, speaker);
      else handsFreeResume();
    } catch {
      handsFreeResume();
    }
  };
  rec.onTick = () => {
    const now = performance.now();
    const dur = (now - rec.started) / 1000;
    if (dur > 20 || (rec.speaking && now - rec.lastVoice > 1100) || (!rec.speaking && dur > 8)) finish();
  };
}

async function handsFreeSubmit(text, speaker) {
  if (!handsFreeActive) return;
  showSpeaker(speaker);
  if (handsFreeRecognizer) {
    try {
      handsFreeRecognizer.onend = null;
      handsFreeRecognizer.stop();
    } catch { /* ignore */ }
    handsFreeRecognizer = null;
  }
  setHandsFreePhase("thinking");
  // spokenQuestion-style: answer out loud even if SPEAK REPLIES is off.
  voiceInputPending = true;
  const data = await ask(text, { suppressSpeak: true, speaker });
  if (!handsFreeActive) return;
  if (!data || !data.text) {
    // Same rule as the call: name the failure, then keep the loop alive.
    setHandsFreePhase("error");
    handsFreeResume();
    return;
  }
  setHandsFreePhase("speaking");
  speak(data.text, { force: true, lang: data.language, onEnd: handsFreeResume });
}

let mediaSelected = new Set();
let decSelected = new Set();
let decAll = [];
let rulesSelected = new Set();
let rulesAll = [];

/* --------------------------------------------------------------- uploads */

const dataSheet = document.getElementById("data-sheet");
const dataUpload = document.getElementById("data-upload");
const dataImport = document.getElementById("data-import");
const dataMedia = document.getElementById("data-media");

function showDataTab(tab) {
  if (dataUpload) dataUpload.hidden = (tab !== "upload");
  if (dataImport) dataImport.hidden = (tab !== "import");
  if (dataMedia) dataMedia.hidden = (tab !== "media");
}

document.getElementById("btn-data")?.addEventListener("click", () => {
  if (dataSheet) { dataSheet.hidden = false; showDataTab("upload"); }
});
document.getElementById("close-data")?.addEventListener("click", () => {
  if (dataSheet) dataSheet.hidden = true;
});
document.getElementById("tab-upload")?.addEventListener("click", () => showDataTab("upload"));
document.getElementById("tab-import")?.addEventListener("click", () => { showDataTab("import"); loadWhatsAppStatus(); });
document.getElementById("tab-media")?.addEventListener("click", () => { showDataTab("media"); loadLibrary("media-body", true); });

document.getElementById("btn-upload")?.addEventListener("click", () => {
  if (dataSheet) { dataSheet.hidden = false; showDataTab("upload"); }
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

let lastMediaId = null;

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
    const data = await res.json();
    if (data.read) {
      const extra = data.whatsapp_summary ? ` ${data.whatsapp_summary}` : "";
      statusEl.textContent = `${s.uploaded} (${data.read_chars.toLocaleString()} chars)${extra}`;
    } else if ((data.read_reason || "").toLowerCase().includes("vision")) {
      statusEl.textContent = s.uploadedNoVision;
    } else if ((data.read_reason || "").toLowerCase().includes("ocr")) {
      statusEl.textContent = s.uploadedNoOcr;
    } else {
      statusEl.textContent = s.uploadedStored;
    }
    // The server proposes rules and LEARNED candidates from readable uploads,
    // but nothing is active until approved - say where to review them.
    const proposals = [];
    if (data.rules_added?.length) {
      proposals.push(`${data.rules_added.length} rule proposal(s) in RULES`);
    }
    if (data.learned_added?.length) {
      proposals.push(`${data.learned_added.length} candidate fact(s) in LEDGER`);
    }
    if (proposals.length) statusEl.textContent += ` · proposed: ${proposals.join("; ")}`;
    lastMediaId = data.media_id;
    document.getElementById("make-plan").hidden = !data.read;
    fileEl.value = "";
    if (relatedEl) relatedEl.value = "";
  } catch {
    statusEl.textContent = s.uploadFailed;
  }
}

document.getElementById("do-upload").addEventListener("click", uploadFile);

document.getElementById("make-plan").addEventListener("click", async () => {
  const btn = document.getElementById("make-plan");
  const statusEl = document.getElementById("upload-status");
  if (lastMediaId == null) return;
  btn.disabled = true;
  statusEl.textContent = "Drafting a strict plan...";
  try {
    const res = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_id: lastMediaId, strict: true }),
    });
    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = `Plan failed: ${data.error || res.status}`;
    } else if (!data.rules.length) {
      statusEl.textContent = `Plan "${data.title}" has no concrete commitments to enforce.`;
    } else {
      statusEl.textContent = `Plan "${data.title}" added - ${data.rules.length} strict rule(s) now enforced.`;
      openRules();
    }
  } catch {
    statusEl.textContent = "Plan failed.";
  } finally {
    btn.disabled = false;
  }
});

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

function syncMediaCount() {
  document.querySelectorAll("[data-media-count]").forEach((el) => {
    el.textContent = `${mediaSelected.size} selected`;
  });
}

function mediaBulkBar(media, boxId) {
  const bar = document.createElement("div");
  bar.className = "mrow";
  const count = document.createElement("span");
  count.dataset.mediaCount = "1";
  count.textContent = `${mediaSelected.size} selected`;
  const mk = (label, fn) => {
    const b = document.createElement("button");
    b.className = "ghost small";
    b.textContent = label;
    b.addEventListener("click", fn);
    return b;
  };
  bar.appendChild(count);
  bar.appendChild(mk("SELECT ALL", () => {
    mediaSelected.clear();
    for (const m of media) mediaSelected.add(m.id);
    syncMediaCount();
  }));
  bar.appendChild(mk("CLEAR", () => {
    mediaSelected.clear();
    syncMediaCount();
  }));
  bar.appendChild(mk("BULK DELETE", async () => {
    if (!mediaSelected.size) return;
    if (!confirm(`Delete ${mediaSelected.size} file(s)? A file still used by another row is kept.`)) return;
    const res = await fetch("/api/media/bulk/delete", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids: Array.from(mediaSelected) }),
    });
    if (!res.ok) {
      count.textContent = "could not delete";
      return;
    }
    mediaSelected.clear();
    await loadLibrary(boxId, true);
  }));
  return bar;
}

async function loadLibrary(boxId = "upload-library", selectable = false) {
  const box = document.getElementById(boxId);
  if (!box) return;
  box.innerHTML = "loading...";
  try {
    const { media = [] } = await (await fetch(`/api/media?limit=${selectable ? 200 : 50}`)).json();
    box.innerHTML = "";
    if (!media.length) {
      box.textContent = "No files uploaded yet.";
      return;
    }
    if (selectable) box.appendChild(mediaBulkBar(media, boxId));
    for (const m of media) {
      let meta = {};
      try {
        meta = m.meta ? JSON.parse(m.meta) : {};
      } catch {
        meta = {};
      }
      const row = document.createElement("div");
      row.className = "mrow";
      if (selectable) {
        const chk = document.createElement("input");
        chk.type = "checkbox";
        chk.checked = mediaSelected.has(m.id);
        chk.addEventListener("change", () => {
          if (chk.checked) mediaSelected.add(m.id);
          else mediaSelected.delete(m.id);
          syncMediaCount();
        });
        row.appendChild(chk);
      }
      const k = document.createElement("div");
      k.className = "k";
      k.textContent = `${(m.kind || "file").toUpperCase()} · ${humanSize(meta.size)}`;
      const t = document.createElement("div");
      t.className = "t";
      t.textContent = meta.filename || m.path || "(file)";
      const d = document.createElement("div");
      d.className = "m";
      const tagsText = () =>
        [m.tags ? `related to: ${m.tags}` : "", m.created_at || ""]
          .filter(Boolean)
          .join(" · ");
      d.textContent = tagsText();

      const actions = document.createElement("div");
      actions.className = "m";
      const ed = document.createElement("button");
      ed.className = "ghost small";
      ed.textContent = "RELATED TO";
      ed.addEventListener("click", () => {
        if (row.querySelector("input.media-edit")) return;
        const input2 = document.createElement("input");
        input2.className = "media-edit";
        input2.placeholder = "what is this about";
        input2.value = m.tags || "";
        input2.style.cssText = "width:100%;margin-top:4px";
        ed.replaceWith(input2);
        input2.focus();
        const save = document.createElement("button");
        save.className = "ghost small";
        save.textContent = "SAVE";
        save.addEventListener("click", async () => {
          const res = await fetch(`/api/media/${m.id}`, {
            method: "PUT",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ tags: input2.value.trim() }),
          });
          if (res.ok) {
            m.tags = input2.value.trim();
            d.textContent = tagsText();
            input2.replaceWith(ed);
            save.remove();
            cancel.remove();
          } else {
            d.textContent = "could not save";
          }
        });
        const cancel = document.createElement("button");
        cancel.className = "ghost small";
        cancel.textContent = "CANCEL";
        cancel.addEventListener("click", () => {
          input2.replaceWith(ed);
          save.remove();
          cancel.remove();
        });
        actions.append(save, cancel);
      });
      const del = document.createElement("button");
      del.className = "ghost small";
      del.textContent = "DELETE";
      del.addEventListener("click", async () => {
        if (!confirm(`Delete ${meta.filename || m.path || "this file"}?`)) return;
        const res = await fetch(`/api/media/${m.id}`, { method: "DELETE" });
        if (res.ok) row.remove();
        else d.textContent = "could not delete";
      });
      actions.append(ed, del);

      row.append(k, t, d, actions);
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

/* --------------------------------------------------------------- rules */

const rulesSheet = document.getElementById("rules-sheet");
const rulesBody = document.getElementById("rules-body");

function ruleCard(r) {
  const row = document.createElement("div");
  row.className = "mrow";

  const chk = document.createElement("input");
  chk.type = "checkbox";
  chk.checked = rulesSelected.has(r.id);
  chk.addEventListener("change", () => {
    if (chk.checked) rulesSelected.add(r.id);
    else rulesSelected.delete(r.id);
    updateRulesCount();
  });
  row.appendChild(chk);

  const k = document.createElement("div");
  k.className = "k";
  k.textContent = r.approved ? "ENFORCED" : "CANDIDATE";
  const t = document.createElement("div");
  t.className = "t";
  t.textContent = r.text;
  const d = document.createElement("div");
  d.className = "m";
  d.textContent = [r.code, r.source, r.created_at].filter(Boolean).join(" · ");
  row.append(k, t, d);

  const actions = document.createElement("div");
  actions.className = "m";
  if (!r.approved) {
    const ap = document.createElement("button");
    ap.className = "ghost small";
    ap.textContent = "ENFORCE";
    ap.addEventListener("click", async () => {
      await fetch(`/api/rules/${r.id}/approve`, { method: "POST" });
      loadRules();
    });
    actions.appendChild(ap);
  }
  const ed = document.createElement("button");
  ed.className = "ghost small";
  ed.textContent = "EDIT";
  ed.addEventListener("click", () => {
    if (row.querySelector("textarea")) return;
    const box = document.createElement("textarea");
    box.className = "mem-edit";
    box.value = r.text || "";
    t.replaceWith(box);
    box.focus();
    const save = document.createElement("button");
    save.className = "ghost small";
    save.textContent = "SAVE";
    save.addEventListener("click", async () => {
      const res = await fetch(`/api/rules/${r.id}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: box.value }),
      });
      if (res.ok) {
        r.text = box.value;
        t.textContent = box.value;
        box.replaceWith(t);
        save.remove();
        cancel.remove();
      } else {
        d.textContent = "could not save";
      }
    });
    const cancel = document.createElement("button");
    cancel.className = "ghost small";
    cancel.textContent = "CANCEL";
    cancel.addEventListener("click", () => {
      box.replaceWith(t);
      save.remove();
      cancel.remove();
    });
    actions.append(save, cancel);
  });
  actions.appendChild(ed);

  const rm = document.createElement("button");
  rm.className = "ghost small";
  rm.textContent = "REMOVE";
  rm.addEventListener("click", async () => {
    await fetch(`/api/rules/${r.id}`, { method: "DELETE" });
    rulesAll = rulesAll.filter((x) => x.id !== r.id);
    rulesSelected.delete(r.id);
    updateRulesCount();
    renderRules();
  });
  actions.appendChild(rm);
  row.appendChild(actions);
  return row;
}

async function loadRules() {
  if (!rulesBody) return;
  rulesBody.textContent = "loading...";
  try {
    const { rules = [] } = await (await fetch("/api/rules")).json();
    rulesAll = rules;
    renderRules();
  } catch {
    rulesBody.textContent = "Could not load rules.";
  }
}

function renderRules() {
  if (!rulesBody) return;
  const filter = document.getElementById("rules-filter")?.value || "all";
  const q = (document.getElementById("rules-search")?.value || "").toLowerCase();

  const matches = rulesAll.filter((r) => {
    if (filter === "enforced" && !r.approved) return false;
    if (filter === "candidate" && r.approved) return false;
    if (q && !`${r.text || ""} ${r.code || ""} ${r.source || ""}`.toLowerCase().includes(q)) return false;
    return true;
  });

  rulesBody.innerHTML = "";
  if (!rulesAll.length) {
    rulesBody.textContent =
      "No rules yet. Upload a plan or document, then choose MAKE STRICT PLAN.";
    return;
  }
  if (!matches.length) {
    rulesBody.textContent = "Nothing matches that filter.";
    updateRulesCount();
    return;
  }
  const groups = [
    ["ENFORCED", matches.filter((r) => r.approved)],
    ["CANDIDATES", matches.filter((r) => !r.approved)],
  ];
  for (const [label, list] of groups) {
    if (!list.length) continue;
    const h = document.createElement("div");
    h.className = "ihead";
    h.textContent = `${label} - ${list.length}`;
    rulesBody.appendChild(h);
    for (const r of list) rulesBody.appendChild(ruleCard(r));
  }
  updateRulesCount();
}

function updateRulesCount() {
  const el = document.getElementById("rules-count");
  if (el) el.textContent = String(rulesSelected.size);
}

document.getElementById("rules-filter")?.addEventListener("change", renderRules);
document.getElementById("rules-search")?.addEventListener("input", renderRules);
document.getElementById("rules-select-all")?.addEventListener("click", () => {
  for (const r of rulesAll) rulesSelected.add(r.id);
  updateRulesCount();
  renderRules();
});
document.getElementById("rules-clear")?.addEventListener("click", () => {
  rulesSelected.clear();
  updateRulesCount();
  renderRules();
});
document.getElementById("rules-bulk-delete")?.addEventListener("click", async () => {
  if (!rulesSelected.size) return;
  if (!confirm(`Delete ${rulesSelected.size} rule(s)? This cannot be undone.`)) return;
  for (const id of Array.from(rulesSelected)) {
    await fetch(`/api/rules/${id}`, { method: "DELETE" });
    rulesAll = rulesAll.filter((x) => x.id !== id);
  }
  rulesSelected.clear();
  updateRulesCount();
  renderRules();
});

function openRules() {
  if (!rulesSheet) return;
  rulesSheet.hidden = false;
  loadRules();
}

document.getElementById("btn-rules").addEventListener("click", openRules);
document.getElementById("close-rules").addEventListener("click", () => {
  if (rulesSheet) rulesSheet.hidden = true;
});

/* ------------------------------------------------------------ settings ui */

const setSheet = document.getElementById("settings-sheet");
const setLang = document.getElementById("set-lang");
const setReplyLang = document.getElementById("set-reply-lang");
const setSpeak = document.getElementById("set-speak");
const setHandsfree = document.getElementById("set-handsfree");
const setVoice = document.getElementById("set-voice");
const setStt = document.getElementById("set-stt");
const setSttEngine = document.getElementById("set-stt-engine");
const setDetail = document.getElementById("set-detail");
const settingsStatus = document.getElementById("settings-status");

function syncSettingsForm() {
  if (setLang) setLang.value = settings.lang;
  if (setReplyLang) setReplyLang.value = settings.replyLanguage || "auto";
  if (setHandsfree) setHandsfree.value = settings.handsfree || "off";
  if (setSpeak) setSpeak.value = settings.speak;
  if (setStt) setStt.value = settings.stt;
  if (setSttEngine) {
    setSttEngine.value = settings.sttEngine || "auto";
    const note = document.getElementById("stt-engine-note");
    if (note) {
      const s = STRINGS[settings.lang === "ur" ? "ur" : "en"];
      note.textContent = localSttReady ? s.offlineReady : s.offlineMissing;
    }
  }
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
  syncAppLockToggle();
  loadProviders();
  loadSpeechStatus();
  loadVoiceprints();
  loadOllama();
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
    // The microphone must follow the reply language, or Urdu speech gets
    // transcribed as English gibberish. A voice chosen for the other language
    // would also read the reply in the wrong accent, so reset it to Automatic.
    const wantStt = settings.lang === "ur" ? "ur-PK" : "en-US";
    settings.stt = wantStt;
    if (setStt) setStt.value = wantStt;
    settings.voice = "";
    loadVoices();
  });
}
if (setSpeak) setSpeak.addEventListener("change", () => (settings.speak = setSpeak.value));
if (setReplyLang)
  setReplyLang.addEventListener("change", () => (settings.replyLanguage = setReplyLang.value));
if (setHandsfree)
  setHandsfree.addEventListener("change", () => {
    settings.handsfree = setHandsfree.value;
    if (settings.handsfree !== "on" && handsFreeActive) stopHandsFree();
  });
if (setStt) setStt.addEventListener("change", () => (settings.stt = setStt.value));
if (setSttEngine)
  setSttEngine.addEventListener("change", () => (settings.sttEngine = setSttEngine.value));
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

/* App lock lives in native SharedPreferences, not server settings, so it is
   read/written through the bridge and never saved with the other options. */
function syncAppLockToggle() {
  const row = document.getElementById("lock-setting-row");
  const cb = document.getElementById("set-applock");
  const bridge = appLockBridge();
  if (!row || !cb || !bridge) return;
  row.hidden = false;
  cb.checked = Boolean(bridge.appLockEnabled());
}
{
  const lockCb = document.getElementById("set-applock");
  if (lockCb) {
    lockCb.addEventListener("change", () => {
      const bridge = appLockBridge();
      if (bridge) bridge.setAppLock(lockCb.checked);
    });
  }
}

document.getElementById("save-settings").addEventListener("click", async () => {
  await saveSettings();
  const status = document.getElementById("settings-status");
  const s = STRINGS[settings.lang === "ur" ? "ur" : "en"];
  if (status) status.textContent = s.saved;
});

document.getElementById("reset-settings").addEventListener("click", async () => {
  if (!window.confirm("Reset every setting to its default? API keys are kept.")) return;
  try {
    await fetch("/api/settings/reset", { method: "POST" });
  } catch {
    /* the in-memory reset below still helps even if the server is down */
  }
  Object.assign(settings, SETTINGS_DEFAULTS);
  applyLang(settings.lang);
  applyTheme(settings.theme);
  applyAccent(settings.accent);
  syncSettingsForm();
  const status = document.getElementById("settings-status");
  if (status) status.textContent = "Settings reset to defaults.";
});

document.getElementById("test-voice").addEventListener("click", () => {
  const was = settings.speak;
  settings.speak = "on";
  const urdu = settings.replyLanguage === "ur" || settings.lang === "ur";
  speak(
    urdu ? "السلام علیکم، میں عاطف اسسٹنٹ ہوں۔" : "This is the Atif Assistant voice.",
    { force: true, lang: urdu ? "ur" : "en" }
  );
  settings.speak = was;
});

/* ------------------------------------------------ on-device LLM (llama.cpp) */
// The APK ships llama-server; this fetches the model once and then reports
// progress/health. Downloads run on the server thread, so the UI only polls.
const dlLlmBtn = document.getElementById("download-llm-model");
const llmStatusEl = document.getElementById("llm-status");
const llmProgressEl = document.getElementById("llm-progress");
const llmSectionEl = document.getElementById("llm-section");
let llmPollTimer = null;
const llmMb = (b) => (b / 1048576).toFixed(0);

function scheduleLlmPoll(ms) {
  clearTimeout(llmPollTimer);
  llmPollTimer = setTimeout(refreshLlmStatus, ms);
}

async function refreshLlmStatus() {
  if (!llmStatusEl) return;
  let s;
  try {
    s = await (await fetch("/api/llm")).json();
  } catch {
    scheduleLlmPoll(3000);
    return;
  }
  const d = s.download || {};
  // The section only exists on builds that ship llama-server (Android).
  if (llmSectionEl) {
    llmSectionEl.hidden =
      !s.binary && d.state !== "downloading" && d.state !== "paused";
  }
  if (d.state === "downloading") {
    const pct = d.total ? Math.floor((d.bytes / d.total) * 100) : 0;
    llmStatusEl.textContent = `Downloading model... ${pct}% (${llmMb(d.bytes)} of ${llmMb(d.total)} MB)`;
    if (llmProgressEl) {
      llmProgressEl.hidden = false;
      llmProgressEl.value = pct;
    }
    if (dlLlmBtn) {
      dlLlmBtn.disabled = true;
      dlLlmBtn.hidden = false;
      dlLlmBtn.textContent = "DOWNLOADING...";
    }
    scheduleLlmPoll(1500);
    return;
  }
  if (d.state === "paused") {
    const mb = llmMb(d.bytes || d.partial || 0);
    llmStatusEl.textContent =
      `Model download paused at ${mb} MB. Resume continues from there.`;
    if (llmProgressEl && d.total) {
      llmProgressEl.hidden = false;
      llmProgressEl.value = Math.floor(((d.bytes || 0) / d.total) * 100);
    }
    if (dlLlmBtn) {
      dlLlmBtn.disabled = false;
      dlLlmBtn.hidden = false;
      dlLlmBtn.textContent = "RESUME DOWNLOAD";
    }
    scheduleLlmPoll(3000);
    return;
  }
  if (llmProgressEl) llmProgressEl.hidden = true;
  if (dlLlmBtn) dlLlmBtn.disabled = false;
  if (d.state === "error") {
    llmStatusEl.textContent = "Download failed: " + (d.reason || "unknown error");
    if (dlLlmBtn) {
      dlLlmBtn.hidden = false;
      dlLlmBtn.textContent = "RETRY DOWNLOAD";
    }
  } else if (s.model && s.model.present) {
    llmStatusEl.textContent = `Model ready (${s.model.file}, ${llmMb(s.model.size)} MB). Server: ${s.server}.`;
    if (dlLlmBtn) dlLlmBtn.hidden = true;
  } else if (s.binary) {
    llmStatusEl.textContent = "llama-server is ready. Download the model to answer fully offline.";
    if (dlLlmBtn) {
      dlLlmBtn.hidden = false;
      dlLlmBtn.textContent = "DOWNLOAD MODEL (~1.1 GB)";
    }
  } else {
    llmStatusEl.textContent = "On-device model is not part of this build.";
    if (dlLlmBtn) dlLlmBtn.hidden = true;
  }
}

if (dlLlmBtn) {
  dlLlmBtn.addEventListener("click", async () => {
    dlLlmBtn.disabled = true;
    try {
      await fetch("/api/llm/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } catch {
      /* status poll reports the failure */
    }
    refreshLlmStatus();
  });
}
refreshLlmStatus();

/* ------------------------------------------------ offline speech model */
// The base Whisper model is weak for Urdu. This lets the user fetch the more
// accurate "small" model in one tap; the server reports what it already has.
const dlModelBtn = document.getElementById("download-urdu-model");
const dlModelNote = document.getElementById("urdu-model-status");

async function loadSpeechStatus() {
  if (!dlModelBtn && !dlModelNote) return;
  try {
    const { stt: s } = await (await fetch("/api/speech")).json();
    const hasSmall = Boolean(s && s.small_present);
    const dl = (s && s.download) || {};
    if (dl.state === "downloading") {
      // Mid-fetch: report progress instead of the static note.
      if (dlModelBtn) {
        dlModelBtn.disabled = true;
        dlModelBtn.hidden = false;
        dlModelBtn.textContent = "DOWNLOADING...";
      }
      if (dlModelNote) {
        const got = Math.round((dl.bytes || 0) / 1048576);
        const want = Math.round((dl.total || 0) / 1048576);
        dlModelNote.textContent = want
          ? `Fetching the speech model: ${got} / ${want} MB...`
          : "Fetching the speech model...";
      }
      scheduleSpeechPoll(1500);
      return;
    }
    if (dl.state === "paused") {
      const mb = Math.round((dl.bytes || dl.partial || 0) / 1048576);
      if (dlModelBtn) {
        dlModelBtn.disabled = false;
        dlModelBtn.hidden = false;
        dlModelBtn.textContent = "RESUME DOWNLOAD";
      }
      if (dlModelNote) {
        dlModelNote.textContent =
          `Speech model paused at ${mb} MB. Resume continues from there.`;
      }
      scheduleSpeechPoll(3000);
      return;
    }
    if (dlModelBtn) {
      dlModelBtn.disabled = false;
      dlModelBtn.hidden = hasSmall || dl.state === "ready";
      dlModelBtn.textContent =
        dl.state === "error" ? "RETRY DOWNLOAD" : "DOWNLOAD URDU MODEL";
    }
    if (dlModelNote) {
      if (dl.state === "error") {
        dlModelNote.textContent = "Download failed: " + (dl.reason || "unknown error");
      } else if (hasSmall) {
        dlModelNote.textContent = `On-device speech ready (${s.model}).`;
      } else if (s && s.available) {
        dlModelNote.textContent =
          `On-device speech ready (${s.model}). A more accurate Urdu model is available.`;
      } else {
        dlModelNote.textContent = "On-device speech is not set up yet (needs whisper.cpp).";
      }
    }
  } catch {
    /* leave the default note */
  }
}

let speechPollTimer = 0;
function scheduleSpeechPoll(ms) {
  clearTimeout(speechPollTimer);
  speechPollTimer = setTimeout(loadSpeechStatus, ms);
}

/* ------------------------------------------------------- first-run setup */
// Shown once, when the offline models are missing. START is never blocked by
// a download: the set below is a one-tap fetch of both models that pauses,
// resumes where it stopped, and never throws away progress.

const setupOverlay = document.getElementById("setup-overlay");
const setupModelsState = document.getElementById("setup-models-state");
const setupHint = document.getElementById("setup-hint");
const setupEta = document.getElementById("setup-eta");
const setupDlBtn = document.getElementById("setup-dl");
const setupPauseBtn = document.getElementById("setup-pause");
const setupStartBtn = document.getElementById("setup-start");
const setupSetBtns = Array.from(document.querySelectorAll(".setup-set"));
let setupPollTimer = 0;
let setupInfo = null;    // GET /api/setup: sets, recommendation, free space
let setupSet = "quick";  // which set the DOWNLOAD button fetches
let setupEtaFrom = { t: 0, got: 0 };
let setupDlArmedAt = 0;  // second-tap timestamp for the mobile-data guard

// Same numbers the backend reports, used when /api/setup is unreachable so
// the button never lies about the size.
const SETUP_SETS_FALLBACK = {
  quick: { llm: "qwen2.5-0.5b", stt: "ggml-base.bin", total_mib: 610 },
  full: { llm: "qwen2.5-1.5b", stt: "ggml-small.bin", total_mib: 1531 },
};

function markSetupDone() {
  try { localStorage.setItem("atif_setup_done", "1"); } catch { /* private mode */ }
  if (setupOverlay) setupOverlay.hidden = true;
  clearTimeout(setupPollTimer);
}

function setupState(el, text, cls) {
  if (!el) return;
  el.textContent = text;
  el.className = "setup-state" + (cls ? " " + cls : "");
}

function setupActiveSet() {
  const sets = (setupInfo && setupInfo.sets) || SETUP_SETS_FALLBACK;
  return sets[setupSet] || sets.quick || SETUP_SETS_FALLBACK.quick;
}

function setupOnCellular() {
  try {
    const c = navigator.connection || navigator.mozConnection;
    if (!c) return false;
    if (c.type) return c.type === "cellular";
    return /^(slow-2g|2g|3g|4g|5g)$/.test(c.effectiveType || "");
  } catch { return false; }
}

function renderSetupSet() {
  setupSetBtns.forEach((b) => b.classList.toggle("sel", b.dataset.set === setupSet));
  const set = setupActiveSet();
  const free = (setupInfo && setupInfo.storage && setupInfo.storage.free_bytes) || 0;
  const need = set.total_mib * 1048576;
  const noSpace = Boolean(setupInfo) && free > 0 && free < need;
  if (setupDlBtn) setupDlBtn.disabled = noSpace;
  if (setupHint) {
    setupHint.textContent = noSpace
      ? `Needs about ${set.total_mib} MB but only ${Math.round(free / 1048576)} MB free - ` +
        "free up space and retry. START works either way."
      : "Speech recognition and the reasoning model, downloaded once. " +
        "Pause anytime; progress is never lost.";
  }
}

/* App lock: an Android-only opt-in fingerprint gate. The bridge exists only
   inside the APK WebView, and only when the device has a biometric sensor. */
function appLockBridge() {
  return window.AndroidVoice
    && typeof window.AndroidVoice.appLockAvailable === "function"
    && window.AndroidVoice.appLockAvailable()
    ? window.AndroidVoice
    : null;
}

function renderSetupLock() {
  const row = document.getElementById("setup-lock-row");
  if (!row) return;
  const bridge = appLockBridge();
  if (!bridge) return; // browser/desktop: the row stays hidden
  row.hidden = false;
  const on = Boolean(bridge.appLockEnabled());
  setupState(document.getElementById("setup-lock-state"),
    on ? "on" : "off", on ? "ok" : "");
  const btn = document.getElementById("setup-lock-btn");
  if (btn) {
    btn.textContent = on ? "TURN OFF FINGERPRINT LOCK" : "TURN ON FINGERPRINT LOCK";
  }
}

// Speed from the previous poll, so a phone on a flaky link sees an honest
// countdown instead of a fake one.
function setupEtaText(want, got, downloading) {
  const now = Date.now();
  if (!downloading) {
    setupEtaFrom = { t: 0, got: 0 };
    return "";
  }
  let text = "";
  if (setupEtaFrom.t && got > setupEtaFrom.got && want > got) {
    const dt = (now - setupEtaFrom.t) / 1000;
    const dB = got - setupEtaFrom.got;
    if (dt >= 1 && dB > 65536) {
      const secs = (want - got) / (dB / dt);
      if (secs > 20 && secs < 8 * 3600) {
        text = secs >= 90 ? `about ${Math.ceil(secs / 60)} min left` : "finishing soon";
      }
    }
  }
  setupEtaFrom = { t: now, got };
  return text;
}

async function refreshSetup() {
  if (!setupOverlay || setupOverlay.hidden) return;
  let speech = null;
  let llm = null;
  try { speech = await (await fetch("/api/speech")).json(); } catch { /* next poll */ }
  try { llm = await (await fetch("/api/llm")).json(); } catch { /* desktop: none */ }
  const s = (speech && speech.stt) || {};
  const d = s.download || {};
  const hasLlm = Boolean(llm && llm.binary);
  const ldl = (llm && llm.download) || {};
  const set = setupActiveSet();
  const speechReady = (s.models_present || []).includes(set.stt);
  const llmReady = !hasLlm || Boolean(llm.model && llm.model.present);
  const parts = [d].concat(hasLlm ? [ldl] : []);
  const phase = parts.some((p) => p.state === "downloading")
    ? "downloading"
    : parts.some((p) => p.state === "paused")
      ? "paused"
      : parts.some((p) => p.state === "error")
        ? "error"
        : (speechReady && llmReady) ? "ready"
        : "idle";

  let got = 0;
  let want = 0;
  for (const p of parts) {
    if (p.total) {
      want += p.total;
      got += Math.min(p.bytes || 0, p.total);
    }
  }
  if (want && got > want) got = want;
  const gotMb = Math.round(got / 1048576);
  const wantMb = Math.round(want / 1048576);
  const eta = setupEtaText(want, got, phase === "downloading");

  if (setupDlBtn) setupDlBtn.hidden = phase === "downloading" || phase === "ready";
  if (setupPauseBtn) setupPauseBtn.hidden = phase !== "downloading";
  if (setupEta) {
    setupEta.hidden = phase !== "paused";
    setupEta.textContent = phase === "paused"
      ? "Paused. Resume continues from where it stopped."
      : "";
  }

  if (phase === "downloading") {
    setupState(setupModelsState, wantMb
      ? `downloading ${gotMb}/${wantMb} MB${eta ? " · " + eta : ""}`
      : "downloading...");
  } else if (phase === "paused") {
    setupState(setupModelsState, gotMb
      ? `paused at ${gotMb} MB - resumes where it stopped`
      : "paused - progress saved");
    if (setupDlBtn) setupDlBtn.textContent = `RESUME (${set.total_mib} MB)`;
  } else if (phase === "error") {
    const bad = parts.find((p) => p.state === "error") || {};
    setupState(setupModelsState, "failed: " + (bad.reason || "network error"), "err");
    if (setupDlBtn) setupDlBtn.textContent = `RETRY (${set.total_mib} MB)`;
  } else if (phase === "ready") {
    setupState(setupModelsState, "ready", "ok");
  } else {
    setupState(setupModelsState, "not installed");
    if (setupDlBtn) setupDlBtn.textContent = `DOWNLOAD (${set.total_mib} MB)`;
  }

  if (phase === "downloading") setupPollTimer = setTimeout(refreshSetup, 1500);
}

async function maybeShowSetup() {
  if (!setupOverlay) return;
  try { if (localStorage.getItem("atif_setup_done")) return; } catch { /* show it */ }
  let need = false;
  try {
    const speech = await (await fetch("/api/speech")).json();
    need = (speech?.stt?.models_present || []).length === 0;
    if (!need && speech?.stt?.available === false) need = true;
  } catch { return; /* server unreachable: never block the app */ }
  if (!need) {
    try {
      const llm = await (await fetch("/api/llm")).json();
      if (llm.binary && !llm.model.present) need = true;
    } catch { /* no llm endpoints: desktop without the binary */ }
  }
  if (!need) {
    markSetupDone(); // nothing to set up; never nag again
    return;
  }
  try { setupInfo = await (await fetch("/api/setup")).json(); } catch { /* fallback */ }
  if (setupInfo && setupInfo.recommended) setupSet = setupInfo.recommended;
  setupOverlay.hidden = false;
  renderSetupSet();
  renderSetupLock();
  refreshSetup();
}

setupSetBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    setupSet = btn.dataset.set === "full" ? "full" : "quick";
    setupEtaFrom = { t: 0, got: 0 };
    renderSetupSet();
    refreshSetup();
  });
});

if (setupDlBtn) {
  setupDlBtn.addEventListener("click", async () => {
    // Two taps on mobile data: an accidental 1.5 GB over a metered link is
    // worse than one extra tap. Wi-Fi starts immediately.
    if (setupOnCellular() && Date.now() - setupDlArmedAt > 5000) {
      setupDlArmedAt = Date.now();
      setupDlBtn.textContent = "TAP AGAIN TO USE MOBILE DATA";
      setTimeout(() => {
        if (Date.now() - setupDlArmedAt >= 4900) refreshSetup();
      }, 5000);
      return;
    }
    setupDlArmedAt = 0;
    const set = setupActiveSet();
    try {
      await fetch("/api/speech/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: set.stt, background: true }),
      });
      let llmBin = false;
      try {
        llmBin = Boolean((await (await fetch("/api/llm")).json()).binary);
      } catch { /* no llm endpoints */ }
      if (llmBin) {
        await fetch("/api/llm/model", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: set.llm }),
        });
      }
    } catch { /* refreshSetup shows the failure */ }
    refreshSetup();
  });
}

if (setupPauseBtn) {
  setupPauseBtn.addEventListener("click", async () => {
    try {
      await fetch("/api/speech/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "pause" }),
      });
    } catch { /* offline */ }
    try {
      await fetch("/api/llm/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "pause" }),
      });
    } catch { /* offline */ }
    clearTimeout(setupPollTimer);
    refreshSetup();
  });
}

if (document.getElementById("setup-lock-btn")) {
  document.getElementById("setup-lock-btn").addEventListener("click", () => {
    const bridge = appLockBridge();
    if (!bridge) return;
    bridge.setAppLock(!bridge.appLockEnabled());
    renderSetupLock();
  });
}

if (document.getElementById("setup-skip")) {
  document.getElementById("setup-skip").addEventListener("click", markSetupDone);
}
if (setupStartBtn) {
  // START is deliberately never disabled: a failed or slow download must not
  // stop the user from reaching the app.
  setupStartBtn.addEventListener("click", () => {
    markSetupDone();
    localSttReady = true;
    loadSpeechStatus();
    refreshLlmStatus();
  });
}
maybeShowSetup();

if (dlModelBtn) {
  dlModelBtn.addEventListener("click", async () => {
    dlModelBtn.disabled = true;
    if (dlModelNote) {
      dlModelNote.textContent = "Fetching the speech model (~466 MB). Progress shows here.";
    }
    try {
      const res = await fetch("/api/speech/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "ggml-small.bin", background: true }),
      });
      const data = await res.json();
      if (!data.ok && !data.started) {
        if (dlModelNote) {
          dlModelNote.textContent = "Download failed: " + (data.reason || data.error || "unknown error");
        }
        dlModelBtn.disabled = false;
        return;
      }
      localSttReady = false;
      scheduleSpeechPoll(1200);
    } catch (e) {
      if (dlModelNote) dlModelNote.textContent = "Download failed: " + e.message;
      dlModelBtn.disabled = false;
    }
  });
}


/* -------------------------------------------------------- voice profiles */
// Saved people: a short voice sample is stored as an embedding on the server so
// a spoken question can be attributed to them. Identification is always shown
// as a labelled guess, never as a fact.

const voiceListEl = document.getElementById("voiceprints-list");
const voiceStatus = document.getElementById("voice-status");
const voiceName = document.getElementById("voice-name");
const voiceEnrollBtn = document.getElementById("voice-enroll");
const voiceModelBtn = document.getElementById("download-voice-model");
let voiceEnrollActive = false;
let voiceEnrollRec = null;

async function loadVoiceprints() {
  if (!voiceListEl && !voiceModelBtn) return;
  try {
    const data = await (await fetch("/api/voiceprints")).json();
    renderVoiceprints(data);
  } catch {
    /* leave whatever is on screen */
  }
}

function renderVoiceprints(data) {
  const engine = data.engine || {};
  const prints = data.voiceprints || [];
  if (voiceListEl) {
    voiceListEl.innerHTML = "";
    if (!prints.length) {
      const d = document.createElement("div");
      d.className = "hint";
      d.textContent = "No saved voices yet.";
      voiceListEl.appendChild(d);
    }
    for (const p of prints) {
      const card = document.createElement("div");
      card.className = "pcard";
      card.dataset.id = p.id;
      const name = document.createElement("strong");
      name.textContent = p.name;
      const meta = document.createElement("span");
      meta.className = "hint";
      meta.textContent = `${p.samples} sample${p.samples === 1 ? "" : "s"} · ${p.dim}d`;
      const del = document.createElement("button");
      del.className = "ghost small";
      del.textContent = "DELETE";
      del.addEventListener("click", () => deleteVoiceprint(p.id, p.name));
      card.append(name, meta, del);
      voiceListEl.appendChild(card);
    }
  }
  if (voiceModelBtn) voiceModelBtn.hidden = Boolean(engine.available);
  if (voiceStatus && !engine.available) {
    voiceStatus.textContent = engine.model_present
      ? "Speaker engine not ready (needs the sherpa-onnx package)."
      : "Voice identification needs a model. Download it below.";
  }
}

async function deleteVoiceprint(id, name) {
  if (!window.confirm(`Delete the saved voice for ${name}?`)) return;
  try {
    await fetch(`/api/voiceprints/${id}`, { method: "DELETE" });
  } catch {
    /* ignore */
  }
  loadVoiceprints();
}

if (voiceModelBtn) {
  voiceModelBtn.addEventListener("click", async () => {
    voiceModelBtn.disabled = true;
    const original = voiceModelBtn.textContent;
    voiceModelBtn.textContent = "DOWNLOADING...";
    if (voiceStatus) voiceStatus.textContent = "Fetching the voice model (~28 MB).";
    try {
      const res = await fetch("/api/voice/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (data.ok) {
        if (voiceStatus) voiceStatus.textContent = "Voice model installed.";
      } else if (voiceStatus) {
        voiceStatus.textContent =
          "Download failed: " + (data.reason || data.error || "unknown error");
      }
    } catch (e) {
      if (voiceStatus) voiceStatus.textContent = "Download failed: " + e.message;
    } finally {
      voiceModelBtn.disabled = false;
      voiceModelBtn.textContent = original;
    }
    loadVoiceprints();
  });
}

if (voiceEnrollBtn) {
  voiceEnrollBtn.addEventListener("click", () => {
    if (voiceEnrollActive) {
      stopVoiceEnroll();
      return;
    }
    const name = (voiceName?.value || "").trim();
    if (!name) {
      if (voiceStatus) voiceStatus.textContent = "Type a name first.";
      voiceName?.focus();
      return;
    }
    startVoiceEnroll();
  });
}

async function startVoiceEnroll() {
  voiceEnrollActive = true;
  if (voiceEnrollBtn) voiceEnrollBtn.textContent = "STOP";
  if (voiceStatus) {
    voiceStatus.textContent = "Recording… speak for a few seconds, then it stops by itself.";
  }
  let rec;
  try {
    rec = createLocalRecorder();
    await rec.start();
  } catch (e) {
    voiceEnrollActive = false;
    if (voiceEnrollBtn) voiceEnrollBtn.textContent = "RECORD & SAVE VOICE";
    if (voiceStatus) voiceStatus.textContent = "Microphone unavailable: " + e.message;
    return;
  }
  voiceEnrollRec = rec;
  rec.onTick = () => {
    const now = performance.now();
    const dur = (now - rec.started) / 1000;
    if (dur > 8 || (rec.speaking && now - rec.lastVoice > 1200)) stopVoiceEnroll();
  };
}

async function stopVoiceEnroll() {
  const rec = voiceEnrollRec;
  if (!rec) return;
  voiceEnrollRec = null;
  voiceEnrollActive = false;
  if (voiceEnrollBtn) voiceEnrollBtn.textContent = "RECORD & SAVE VOICE";
  const blob = await rec.stop();
  if (!blob || blob.size < 100) {
    if (voiceStatus) voiceStatus.textContent = "Nothing was recorded.";
    return;
  }
  if (voiceStatus) voiceStatus.textContent = "Saving voice…";
  try {
    const audio = await blobToBase64(blob);
    const res = await fetch("/api/voiceprints", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: (voiceName?.value || "").trim(), audio }),
    });
    const data = await res.json();
    if (data.ok && data.voiceprint) {
      if (voiceStatus) voiceStatus.textContent = `Saved a voice sample for ${data.voiceprint.name}.`;
      loadVoiceprints();
    } else if (voiceStatus) {
      voiceStatus.textContent = data.error || "Could not save that voice.";
    }
  } catch (e) {
    if (voiceStatus) voiceStatus.textContent = "Could not save that voice: " + e.message;
  }
}



/* ------------------------------------------------------ local model host */
// Ollama runs the offline chat model on this Mac. The app starts it when it can
// and can pull the model on request, so offline chat needs no terminal.

const ollamaStatusEl = document.getElementById("ollama-status");
const ollamaStartBtn = document.getElementById("ollama-start");
const ollamaPullBtn = document.getElementById("ollama-pull");
const setOllamaAutostart = document.getElementById("set-ollama-autostart");
let ollamaPollTimer = null;

function renderOllama(s) {
  if (!ollamaStatusEl) return;
  if (!s.installed) {
    ollamaStatusEl.textContent =
      "Ollama is not installed. Install it (brew install ollama) to chat fully offline.";
    if (ollamaStartBtn) ollamaStartBtn.disabled = true;
    if (ollamaPullBtn) ollamaPullBtn.disabled = true;
    return;
  }
  if (!s.running) {
    ollamaStatusEl.textContent = "Installed but not running.";
  } else if (!s.model_present) {
    ollamaStatusEl.textContent = `Running at ${s.url} - model ${s.model} is not downloaded yet.`;
  } else {
    ollamaStatusEl.textContent = `Running at ${s.url} - model ${s.model} ready.`;
  }
  if (ollamaStartBtn) ollamaStartBtn.disabled = s.running;
  if (ollamaPullBtn) ollamaPullBtn.disabled = !s.running || s.model_present;
  if (setOllamaAutostart) setOllamaAutostart.value = s.autostart ? "on" : "off";
}

async function loadOllama() {
  if (!ollamaStatusEl) return;
  try {
    renderOllama(await (await fetch("/api/ollama")).json());
  } catch {
    /* leave whatever is on screen */
  }
}

function pollOllamaUntilReady() {
  if (ollamaPollTimer) clearInterval(ollamaPollTimer);
  let tries = 0;
  ollamaPollTimer = setInterval(async () => {
    tries += 1;
    let s = null;
    try {
      s = await (await fetch("/api/ollama")).json();
    } catch {
      return;
    }
    renderOllama(s);
    if (s.model_present || tries > 200) {
      clearInterval(ollamaPollTimer);
      ollamaPollTimer = null;
    }
  }, 3000);
}

if (ollamaStartBtn) {
  ollamaStartBtn.addEventListener("click", async () => {
    ollamaStartBtn.disabled = true;
    if (ollamaStatusEl) ollamaStatusEl.textContent = "Starting the local model...";
    try {
      const data = await (
        await fetch("/api/ollama/start", { method: "POST" })
      ).json();
      if (!data.ok && ollamaStatusEl) {
        ollamaStatusEl.textContent = "Could not start: " + (data.reason || "unknown error");
      }
    } catch (e) {
      if (ollamaStatusEl) ollamaStatusEl.textContent = "Could not start: " + e.message;
    }
    loadOllama();
  });
}

if (ollamaPullBtn) {
  ollamaPullBtn.addEventListener("click", async () => {
    ollamaPullBtn.disabled = true;
    if (ollamaStatusEl) {
      ollamaStatusEl.textContent = "Downloading the model... this can take a few minutes.";
    }
    try {
      const data = await (
        await fetch("/api/ollama/pull", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        })
      ).json();
      if (!data.ok && ollamaStatusEl) {
        ollamaStatusEl.textContent = "Download failed: " + (data.reason || "unknown error");
      } else {
        pollOllamaUntilReady();
      }
    } catch (e) {
      if (ollamaStatusEl) ollamaStatusEl.textContent = "Download failed: " + e.message;
    }
  });
}

if (setOllamaAutostart) {
  setOllamaAutostart.addEventListener("change", async () => {
    try {
      await fetch("/api/ollama/autostart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: setOllamaAutostart.value === "on" }),
      });
    } catch {
      /* non-critical */
    }
  });
}

// ------------------------------------------------------------- pipeline
// Settings -> MODEL PIPELINE. Each row is a stage that ran for real; a
// failing row carries its own fix so "chat is broken" stops being a mystery.
const pipelineListEl = document.getElementById("pipeline-list");
const pipelineStatusEl = document.getElementById("pipeline-status");
const pipelineRunBtn = document.getElementById("pipeline-run");
const pipelineFullBtn = document.getElementById("pipeline-full");

function renderPipelineRow(stage) {
  if (!pipelineListEl) return;
  const card = document.createElement("div");
  card.className = "pcard";
  card.dataset.id = stage.id || stage.label;
  const head = document.createElement("div");
  head.className = "phead";
  const title = document.createElement("strong");
  title.textContent = stage.label;
  const badge = document.createElement("span");
  badge.className = "pbadge " + (stage.state === "pass" ? "pok" : stage.state === "fail" ? "pbad" : "poff");
  badge.textContent = (stage.state || "skip").toUpperCase();
  head.append(title, badge);
  if (stage.ms) {
    const ms = document.createElement("span");
    ms.className = "hint";
    ms.textContent = stage.ms + " ms";
    head.appendChild(ms);
  }
  card.appendChild(head);
  if (stage.detail) {
    const detail = document.createElement("div");
    detail.className = "hint";
    detail.textContent = stage.detail;
    card.appendChild(detail);
  }
  if (stage.hint) {
    const fix = document.createElement("div");
    fix.className = "hint";
    fix.textContent = "FIX: " + stage.hint;
    card.appendChild(fix);
  }
  pipelineListEl.appendChild(card);
}

function clientStages() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  return [
    {
      id: "session",
      label: "Session on this device",
      state: session ? "pass" : "skip",
      ms: 0,
      detail: session ? "this device holds a session id" : "no session - open the app from the server address, not a copied file",
    },
    {
      id: "mic",
      label: "Microphone",
      state: navigator.mediaDevices ? "pass" : "fail",
      ms: 0,
      detail: navigator.mediaDevices
        ? "the browser exposes a microphone"
        : "no microphone API (needs https or localhost)",
    },
    {
      id: "browser-sr",
      label: "Browser speech-in (online)",
      state: SR ? "pass" : "skip",
      ms: 0,
      detail: SR
        ? "built-in speech recognition available (needs network)"
        : "this browser has no built-in speech recognition",
    },
    {
      id: "offline-stt",
      label: "Offline speech-in downloaded",
      state: localSttReady ? "pass" : "skip",
      ms: 0,
      detail: localSttReady
        ? "the server's offline engine is ready"
        : "not downloaded yet - use DOWNLOAD URDU MODEL above",
    },
    {
      id: "sw",
      label: "Service worker",
      state: navigator.serviceWorker ? "pass" : "skip",
      ms: 0,
      detail: navigator.serviceWorker ? "offline page caching active" : "no service worker support",
    },
  ];
}

async function runPipelineChecks() {
  if (!pipelineRunBtn || !pipelineListEl) return;
  pipelineRunBtn.disabled = true;
  pipelineListEl.innerHTML = "";
  if (pipelineStatusEl) pipelineStatusEl.textContent = "Running each stage for real...";
  try {
    const data = await (await fetch("/api/pipeline")).json();
    for (const stage of data.stages || []) renderPipelineRow(stage);
  } catch (e) {
    if (pipelineStatusEl) {
      pipelineStatusEl.textContent = "Could not reach the server: " + e.message;
    }
  }
  for (const s of clientStages()) renderPipelineRow(s);
  const fails = pipelineListEl.querySelectorAll(".pbad").length;
  if (pipelineStatusEl) {
    pipelineStatusEl.textContent = fails
      ? fails + " stage(s) need attention - the FIX line on each card says how."
      : "Every stage passed.";
  }
  pipelineRunBtn.disabled = false;
}

if (pipelineRunBtn) pipelineRunBtn.addEventListener("click", runPipelineChecks);

if (pipelineFullBtn) {
  pipelineFullBtn.addEventListener("click", async () => {
    pipelineFullBtn.disabled = true;
    if (pipelineStatusEl) {
      pipelineStatusEl.textContent =
        "Asking for a full answer... a small local model can take a minute or more.";
    }
    try {
      const data = await (
        await fetch("/api/pipeline/full", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        })
      ).json();
      if (!data.ok) {
        if (pipelineStatusEl) {
          pipelineStatusEl.textContent = "Full answer failed: " + (data.error || "unknown error");
        }
      } else {
        renderPipelineRow({
          id: "full-answer",
          label: "Full answer (" + (data.provider || "?") + ")",
          state: "pass",
          ms: data.ms,
          detail: data.text,
          hint: null,
        });
        if (pipelineStatusEl) {
          pipelineStatusEl.textContent =
            data.ms + " ms via " + data.provider + ", route '" + data.route + "'. " + (data.note || "");
        }
      }
    } catch (e) {
      if (pipelineStatusEl) pipelineStatusEl.textContent = "Full answer failed: " + e.message;
    }
    pipelineFullBtn.disabled = false;
  });
}

const providersEl = document.getElementById("providers-list");
const providersStatus = document.getElementById("providers-status");

function providerBadge(state) {
  const b = document.createElement("span");
  b.className = "pbadge";
  b.dataset.role = "badge";
  b.classList.add(
    state === "ready" ? "pok" : state === "error" ? "pbad" : state === "off" ? "poff" : "punknown"
  );
  b.textContent =
    state === "ready" ? "READY" : state === "error" ? "ERROR" : state === "off" ? "OFF" : "UNKNOWN";
  return b;
}

function renderProvider(p) {
  const card = document.createElement("div");
  card.className = "pcard";
  card.dataset.name = p.name;
  const off = p.enabled === false;

  const head = document.createElement("div");
  head.className = "phead";
  const title = document.createElement("strong");
  title.textContent = p.label || p.name;
  const badge = providerBadge(off ? "off" : p.ready ? "ready" : p.error ? "error" : "unknown");
  const toggle = document.createElement("button");
  toggle.className = "ghost small ptoggle";
  if (off) toggle.classList.add("off");
  toggle.dataset.role = "toggle";
  toggle.textContent = off ? "TURN ON" : "TURN OFF";
  toggle.title = off ? "Enable this provider" : "Disable this provider";
  if (off) head.append(title, badge, toggle);
  else head.append(title, badge, toggle);
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
  if (off) note.textContent = "turned off - not used for answers";
  else if (!p.key_set && p.name !== "ollama") note.textContent = "no key set";
  card.appendChild(note);

  toggle.addEventListener("click", () => toggleProvider(card, off));
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
  const cls =
    state === "ready" ? "pok" : state === "error" ? "pbad" : state === "off" ? "poff" : "punknown";
  badge.className = "pbadge " + cls;
  badge.textContent =
    text || (state === "ready" ? "READY" : state === "error" ? "ERROR" : state === "off" ? "OFF" : "UNKNOWN");
}

async function toggleProvider(card, enable) {
  const name = card.dataset.name;
  const note = card.querySelector('[data-role="note"]');
  const toggle = card.querySelector('[data-role="toggle"]');
  if (toggle) toggle.disabled = true;
  try {
    const res = await fetch(`/api/providers/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !!enable }),
    });
    if (!res.ok) throw new Error((await res.json()).error || "toggle failed");
    await loadProviders();
  } catch (err) {
    if (toggle) toggle.disabled = false;
    if (note) note.textContent = `Could not change: ${err.message}`;
  }
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
    const total = Object.values(a).reduce((n, v) => n + (Number(v) || 0), 0);
    const parts = ["facts", "notes", "decisions", "patterns", "rules", "media", "places", "routines"]
      .filter((k) => a[k])
      .map((k) => `${a[k]} ${k}`);
    if (backupStatus) {
      backupStatus.textContent = total
        ? `Imported ${total} ${total === 1 ? "item" : "items"} (${parts.join(", ")}).`
        : "Backup already present; nothing new added.";
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

/* Health: the dot and status line must stay honest for the whole session,
   not just the first load - one failed fetch at boot used to leave "offline"
   forever, and a dead engine never turned the dot off. */
function applyHealth(h) {
  localSttReady = Boolean(h.speech && h.speech.offline_in && h.speech.offline_in.available);
  const ready = h.providers && h.providers.find((p) => p.ready);
  dot.className = ready ? "dot on" : "dot off";
  statusline.textContent = ready
    ? `${ready.name} · ${h.counts.facts}f ${h.counts.episodes}e ${h.counts.patterns}p`
    : "no model key";
}

async function healthTick() {
  try {
    const h = await (await fetch("/api/health")).json();
    applyHealth(h);
    return true;
  } catch {
    dot.className = "dot off";
    statusline.textContent = "engine offline";
    return false;
  }
}

/* ------------------------------------------------- conversations (sessions) */

/** Render the active conversation from the server. Used at boot and after a
 *  switch; tolerates empty history and an unreachable engine. */
async function loadSessionHistory() {
  if (!session) return;
  try {
    const hr = await fetch(`/api/history/${session}`);
    const { messages } = await hr.json();
    for (const m of messages || []) {
      if (m.role === "user") addUser(m.content);
      else addBot({ text: m.content, warnings: [] });
    }
  } catch { /* no history: start clean */ }
}

/** Clear the thread and forget the session id; the next ask creates a new
 *  conversation server-side. */
function startNewChat() {
  session = null;
  try { localStorage.removeItem("atif-assistant.session"); } catch { /* private mode */ }
  chat.innerHTML = "";
  document.getElementById("history-sheet").hidden = true;
  document.getElementById("input")?.focus();
}

function switchSession(sid) {
  if (!sid) return;
  session = sid;
  try { localStorage.setItem("atif-assistant.session", sid); } catch { /* private mode */ }
  chat.innerHTML = "";
  document.getElementById("history-sheet").hidden = true;
  loadSessionHistory();
}

function renderSessions(list) {
  const box = document.getElementById("history-list");
  if (!box) return;
  box.innerHTML = "";
  if (!list.length) {
    box.textContent = "No conversations yet - tap NEW to start the first one.";
    return;
  }
  for (const s of list) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "history-item" + (s.session === session ? " sel" : "");
    const prev = document.createElement("span");
    prev.className = "h-prev";
    prev.textContent = s.last_message || "(empty)";
    const meta = document.createElement("span");
    meta.className = "h-meta";
    const when = (s.last_at || "").slice(0, 16).replace("T", " ");
    const n = s.messages || 0;
    meta.textContent = `${n} message${n === 1 ? "" : "s"}${when ? " · " + when : ""}`;
    item.append(prev, meta);
    item.addEventListener("click", () => switchSession(s.session));
    box.appendChild(item);
  }
}

document.getElementById("btn-new-chat")?.addEventListener("click", startNewChat);
document.getElementById("close-history")?.addEventListener("click", () => {
  document.getElementById("history-sheet").hidden = true;
});
document.getElementById("btn-history")?.addEventListener("click", async () => {
  const sheetEl = document.getElementById("history-sheet");
  const box = document.getElementById("history-list");
  sheetEl.hidden = false;
  if (box) box.textContent = "Loading...";
  try {
    const res = await fetch("/api/sessions");
    renderSessions((await res.json()).sessions || []);
  } catch {
    if (box) box.textContent = "Could not load conversations. Is the engine running?";
  }
});

/* boot */
(async function init() {
  await loadSettings();
  loadVoices();
  await healthTick();
  await loadSessionHistory();
})();

// Keep the status fresh and recover automatically when the engine comes
// back (server auto-restart, model download finished, transient hiccup).
setInterval(healthTick, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) healthTick();
});
window.addEventListener("focus", healthTick);

/* PWA */
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}