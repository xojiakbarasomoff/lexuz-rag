"""Build a small parser fixture from a raw Lex.uz snapshot.

Keeps the real page structure (document header, edition selector, #divCont)
but only the first N article blocks, so tests stay small and offline.

usage: python scripts/make_fixture.py RAW.html OUT.html --articles 6
"""

import argparse
import hashlib
import re
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser

p = argparse.ArgumentParser()
p.add_argument("raw")
p.add_argument("out")
p.add_argument("--articles", type=int, default=6)
p.add_argument("--extra-labels", default="", help="comma-separated extra article labels to keep (e.g. 12¹)")
a = p.parse_args()

raw = Path(a.raw).read_text(encoding="utf-8")
tree = LexborHTMLParser(raw)
title = tree.css_first("title").text()
header = tree.css_first(".docHeader").html
editions = re.findall(r'<div class="dropdown-menu__item lx_date_link"[^>]*>[^<]*</div>', raw)
cont = tree.css_first("div#divCont")
extra = {x for x in a.extra_labels.split(",") if x}

kept, n_articles, keep_current = [], 0, True
for child in cont.iter():
    cls = (child.attributes.get("class") or "").split()
    if cls and cls[0] == "CLAUSE_DEFAULT":
        n_articles += 1
        m = re.search(r'id="-?\d+">(\d+)(?:<sup>(\d+)</sup>)?-modda', child.html or "")
        label = (m.group(1) + (m.group(2) or "").translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))) if m else ""
        keep_current = n_articles <= a.articles or label in extra
    # headings are always kept so heading context stays correct
    if keep_current or (cls and cls[0] == "TEXT_HEADER_DEFAULT"):
        kept.append(child.html)

doc = (f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>{title}</title></head><body>"
       f"<div class=\"lx_menu\">NAVIGATION MENU (must not be parsed)</div>{header}"
       f"<div class=\"dropdown-menu\">{''.join(editions)}</div>"
       f"<div id=\"divBody\"><div id=\"divCont\">{''.join(kept)}</div></div></body></html>")
Path(a.out).write_text(doc, encoding="utf-8", newline="\n")
print("raw sha256", hashlib.sha256(raw.encode("utf-8")).hexdigest(), "kept elements", len(kept))
