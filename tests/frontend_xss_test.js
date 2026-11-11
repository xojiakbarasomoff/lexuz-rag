// Runs frontend/app.js renderAnswer() against a minimal fake DOM and checks that
// attacker-controlled strings never become elements/attributes and that only
// https://lex.uz links are rendered as <a>.
"use strict";
const assert = require("assert");

class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this._text = ""; this.className = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  append(...c) { for (const x of c) this.children.push(typeof x === "string" ? new Text(x) : x); }
  replaceChildren(...c) { this.children = []; this.append(...c); }
  addEventListener() {}
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  querySelector() { return null; }
}
class Text extends Node { constructor(t) { super("#text"); this._text = t; } }

const all = [];
global.document = {
  createElement: (t) => { const n = new Node(t.toUpperCase()); all.push(n); return n; },
  createTextNode: (t) => new Text(t),
  getElementById: () => null,
  querySelector: () => result,
  addEventListener: () => {},
};
const result = new Node("SECTION");
const app = require(process.argv[2]);

const evil = '<img src=x onerror=alert(1)><script>alert(2)</script>';
app.renderAnswer({
  status: "answered", latency_ms: 1, corpus_checked_at: null, limitations: [evil],
  claims: [{ text: evil, source_ids: ["S1"] }],
  sources: [
    { source_id: "S1", document_title: evil, article_label: "1", article_title: evil, excerpt: evil,
      source_url: "javascript:alert(3)", checked_at: null },
    { source_id: "S2", document_title: "Doc", article_label: "2", article_title: "T", excerpt: "e",
      source_url: "https://lex.uz/docs/-4704#-4718", checked_at: null },
  ],
});

const tags = new Set(all.map((n) => n.tagName));
assert(!tags.has("IMG") && !tags.has("SCRIPT"), "markup in data became elements");
for (const n of all) for (const [k, v] of Object.entries(n.attrs)) {
  assert(!/^on/i.test(k), "event handler attribute created");
  assert(!/javascript:/i.test(v), "javascript: URL rendered");
}
const links = all.filter((n) => n.tagName === "A");
assert.strictEqual(links.length, 1);
assert.strictEqual(links[0].attrs.href, "https://lex.uz/docs/-4704#-4718");
assert(result.textContent.includes("<script>alert(2)</script>"), "evil text should be shown as plain text");
console.log("ok");
