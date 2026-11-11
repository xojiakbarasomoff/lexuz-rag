// LexUZ RAG frontend. All server text is rendered via textContent / text nodes only (no HTML parsing sinks).
"use strict";

const API = "/api/v1";
const ALLOWED_LINK = /^https:\/\/(www\.)?lex\.uz\//;
const STATUS_TEXT = {
  insufficient_evidence: "Manbalarda yetarli maʼlumot topilmadi",
  clarification_needed: "Savolni aniqlashtirish kerak",
};

const $ = (sel) => document.querySelector(sel);
let inFlight = false;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c) node.append(c);
  return node;
}

function fmtDate(iso) {
  if (!iso) return "nomaʼlum";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "nomaʼlum";
  return d.toLocaleString("uz-UZ", { timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function safeLink(url, label) {
  if (typeof url !== "string" || !ALLOWED_LINK.test(url)) return el("span", { text: label });
  return el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: label });
}

async function loadCorpus() {
  const list = $("#corpus-list");
  try {
    const res = await fetch(`${API}/documents`);
    if (!res.ok) throw new Error(String(res.status));
    const docs = await res.json();
    list.replaceChildren();
    if (!docs.length) list.append(el("li", { class: "muted", text: "Hozircha indekslangan hujjat yo‘q." }));
    for (const d of docs) {
      list.append(el("li", {},
        safeLink(d.canonical_url, d.title),
        el("span", { class: "meta", text: `${d.article_count} modda · manba tekshirilgan: ${fmtDate(d.last_checked_at)}` })));
    }
  } catch {
    list.replaceChildren(el("li", { class: "muted", text: "Hujjatlar ro‘yxatini yuklab bo‘lmadi." }));
  }
}

function renderError(message) {
  $("#result").replaceChildren(el("div", { class: "card error", role: "alert", text: message }));
}

function renderAnswer(data) {
  const out = [];
  const main = el("div", { class: "card" + (data.status === "answered" ? "" : " status-note") });
  if (data.status !== "answered") main.append(el("p", {}, el("strong", { text: STATUS_TEXT[data.status] || "" })));
  if (data.status === "clarification_needed" && data.clarifying_question) {
    main.append(el("p", { text: data.clarifying_question }));
  }
  if (data.claims && data.claims.length) {
    const ul = el("ul", { class: "claims" });
    for (const c of data.claims) {
      const li = el("li", { text: c.text });
      for (const sid of c.source_ids) {
        const chip = el("button", { type: "button", class: "cite", "aria-label": `Manba ${sid}`, text: sid });
        chip.addEventListener("click", () => {
          const det = document.getElementById(`src-${sid}`);
          if (det) { det.open = true; det.querySelector("summary").focus(); det.scrollIntoView({ block: "nearest" }); }
        });
        li.append(chip);
      }
      ul.append(li);
    }
    main.append(ul);
  }
  if (data.limitations && data.limitations.length) {
    for (const l of data.limitations) main.append(el("p", { class: "limitations", text: l }));
  }
  out.push(main);

  if (data.sources && data.sources.length) {
    const box = el("div", { class: "card" }, el("h2", { text: data.status === "answered" ? "Manbalar" : "Tegishli bo‘lishi mumkin bo‘lgan moddalar" }));
    for (const s of data.sources) {
      const det = el("details", { class: "source", id: `src-${s.source_id}` });
      det.append(el("summary", { text: `[${s.source_id}] ${s.document_title}, ${s.article_label}-modda. ${s.article_title}` }));
      det.append(el("blockquote", { text: s.excerpt }));
      const meta = el("p", { class: "source-meta" });
      meta.append(safeLink(s.source_url, "Lex.uz’da ochish"));
      meta.append(document.createTextNode(` · manba tekshirilgan: ${fmtDate(s.checked_at)}`));
      det.append(meta);
      if (s.has_future_amendment_note) {
        det.append(el("p", { class: "source-meta", text: "Diqqat: bu moddada kelajakda kuchga kiradigan o‘zgarish qayd etilgan." }));
      }
      box.append(det);
    }
    out.push(box);
  }
  out.push(el("p", { class: "muted", text: `Korpus tekshirilgan: ${fmtDate(data.corpus_checked_at)} · ${data.latency_ms} ms` }));
  $("#result").replaceChildren(...out);
}

async function ask(question) {
  if (inFlight) return;
  inFlight = true;
  const btn = $("#submit");
  const result = $("#result");
  btn.disabled = true;
  result.setAttribute("aria-busy", "true");
  result.replaceChildren(el("p", { class: "muted" }, el("span", { class: "spinner", "aria-hidden": "true" }),
    document.createTextNode(" Manbalar qidirilmoqda va javob tekshirilmoqda…")));
  try {
    const res = await fetch(`${API}/ask`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
    });
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON error page */ }
    if (!res.ok) {
      renderError((data && data.error && data.error.message) || "Xatolik yuz berdi. Qayta urinib ko‘ring.");
    } else {
      renderAnswer(data);
    }
  } catch {
    renderError("Server bilan aloqa yo‘q. Internetni tekshirib, qayta urinib ko‘ring.");
  } finally {
    inFlight = false;
    btn.disabled = false;
    result.setAttribute("aria-busy", "false");
  }
}

function init() {
  const form = $("#ask-form");
  const ta = $("#question");
  const count = $("#char-count");
  ta.addEventListener("input", () => { count.textContent = `${ta.value.length} / 600`; });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = ta.value.trim();
    if (q.length < 3) { renderError("Savolni kamida 3 belgida yozing."); ta.focus(); return; }
    ask(q);
  });
  for (const b of document.querySelectorAll(".example")) {
    b.addEventListener("click", () => { ta.value = b.textContent; count.textContent = `${ta.value.length} / 600`; ta.focus(); });
  }
  loadCorpus();
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", init);
if (typeof module !== "undefined") module.exports = { el, safeLink, renderAnswer };
