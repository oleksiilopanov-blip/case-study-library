#!/usr/bin/env python3
"""
Euristiq case-study PDF -> structured record.

Reads the 2026 one-pager template (1920x1080, one page, exported from Figma
with live text):

    LEFT COLUMN                         RIGHT COLUMN
    <Title>          (60pt, 1-3 lines)  <client logo + product image>
    <Description>    (16pt)
    <Tag chips>      (16pt, indented)
    Outcomes         (24pt)
      <Headline>     (18pt)             <Label>  <Label>  <Label>   (16pt)
      <Detail>       (16pt, optional)   <Value>  <Value>  <Value>   (20pt)

The footer stats are read as label/value pairs. "Domain" or "Industry" becomes
the Industry filter (values split on "|"), "Location" becomes the Location
filter, and the remaining stat is shown as the case's headline metric.

Usage:  python3 extract.py <file.pdf> [more.pdf ...]   # prints JSON
"""
import json
import re
import sys
import unicodedata
from collections import defaultdict

import pdfplumber

# ---------------------------------------------------------------- text clean-up

# Cyrillic/Greek letters that look identical to Latin ones. Figma files typed
# on a mixed keyboard layout pick these up and they silently break search.
HOMOGLYPHS = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J",
    "Ѕ": "S", "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h",
    "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "і": "i",
    "ѕ": "s", "ј": "j", "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I",
    "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X",
    "ο": "o", "α": "a",
}
INVISIBLE = {"­": "", "​": "", "‌": "", "‍": "", "﻿": "",
             " ": " ", " ": " ", " ": " ", " ": " "}


def clean(s):
    """Normalise homoglyphs, invisible characters and whitespace.

    Typographic quotes and dashes are kept for display; search normalises
    them separately in the browser.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = "".join(HOMOGLYPHS.get(c, INVISIBLE.get(c, c)) for c in s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- layout

LINE_TOL = 3.0        # pt: words whose tops are this close share a line
CHIP_GAP = 18.0       # pt: horizontal gap that separates two tag chips
RIGHT_COL_X = 1030    # pt: the right column (logo, image, stats) starts at ~1035

TITLE_MIN = 36        # pt: title font
HEADING = 24          # pt: "Outcomes"
OUTCOME_HEAD = 18     # pt: outcome headline
BODY = 16             # pt: description, chips, outcome detail, stat label
STAT_VALUE = 20       # pt: stat value


def _near(a, b, tol=0.6):
    return abs(a - b) < tol


def group_lines(words):
    """Group words into visual lines, top to bottom, each sorted left to right."""
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    lines = []
    for w in words:
        for ln in lines:
            if abs(ln["top"] - w["top"]) <= LINE_TOL and _near(ln["size"], w["size"]):
                ln["words"].append(w)
                break
        else:
            lines.append({"top": w["top"], "size": round(w["size"], 1), "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["x0"] = ln["words"][0]["x0"]
        ln["text"] = clean(" ".join(w["text"] for w in ln["words"]))
    lines.sort(key=lambda l: (l["top"], l["x0"]))
    return [l for l in lines if l["text"]]


def split_chips(line):
    """Split one row of tag chips on wide horizontal gaps."""
    chips, cur, prev = [], [], None
    for w in line["words"]:
        if prev is not None and w["x0"] - prev["x1"] > CHIP_GAP:
            chips.append(cur)
            cur = []
        cur.append(w)
        prev = w
    if cur:
        chips.append(cur)
    return [t for t in (clean(" ".join(w["text"] for w in c)) for c in chips) if t]


def join_wrapped(parts):
    """Join wrapped lines, re-attaching words hyphenated across a break."""
    out = ""
    for t in parts:
        if not out:
            out = t
        elif out.endswith("-") and re.match(r"^[a-z]", t) and not out.endswith(" -"):
            out += t
        else:
            out += " " + t
    return clean(out)


def split_values(v):
    """'Aviation | Travel' -> ['Aviation', 'Travel']"""
    return [clean(x) for x in re.split(r"\s*[|,]\s*", v) if clean(x)]


# ---------------------------------------------------------------- parse

INDUSTRY_LABELS = {"domain", "industry", "industries", "sector"}
LOCATION_LABELS = {"location", "region", "country", "geography"}


def parse_pdf(path):
    with pdfplumber.open(path) as pdf:
        npages = len(pdf.pages)
        page = pdf.pages[0]
        words = page.extract_words(extra_attrs=["size"], use_text_flow=False,
                                   keep_blank_chars=False)
        raw_text = "\n".join(clean(p.extract_text() or "") for p in pdf.pages)

    rec = {"pages": npages, "raw_text": raw_text, "warnings": []}
    if not words:
        rec["warnings"].append("No live text - export from Figma without outlining text.")
        return rec

    left = group_lines([w for w in words if w["x0"] < RIGHT_COL_X])
    right = group_lines([w for w in words if w["x0"] >= RIGHT_COL_X])

    # --- title
    title_lines = [l for l in left if l["size"] >= TITLE_MIN]
    rec["title"] = clean(" ".join(l["text"] for l in title_lines))
    after_title = max((l["top"] for l in title_lines), default=0)

    # --- "Outcomes" heading splits the left column in two
    head = next((l for l in left if _near(l["size"], HEADING)
                 and l["text"].lower().rstrip(":") in ("outcomes", "results", "key outcomes")),
                None)
    split_y = head["top"] if head else float("inf")

    # --- description vs tag chips (chips are indented: they sit inside pills)
    upper = [l for l in left if after_title < l["top"] < split_y and _near(l["size"], BODY)]
    base_x = min((l["x0"] for l in upper), default=0)
    desc = [l for l in upper if l["x0"] - base_x < 10]
    chip_rows = [l for l in upper if l["x0"] - base_x >= 10]
    rec["description"] = join_wrapped([l["text"] for l in desc])
    tags, seen = [], set()
    for row in chip_rows:
        for c in split_chips(row):
            if c.lower() not in seen:
                seen.add(c.lower())
                tags.append(c)
    rec["tags"] = tags

    # --- outcomes: an 18pt headline, optionally followed by 16pt detail lines
    # Some decks write each outcome as a wrapped 18pt sentence with no detail
    # line, so an 18pt line directly under another 18pt line (one line-height
    # apart) continues the same outcome rather than starting a new one.
    outcomes, prev = [], None
    for l in left:
        if l["top"] <= split_y:
            continue
        if _near(l["size"], OUTCOME_HEAD):
            if (outcomes and prev is not None and _near(prev["size"], OUTCOME_HEAD)
                    and l["top"] - prev["top"] < 30):
                outcomes[-1]["title"].append(l["text"])
            else:
                outcomes.append({"title": [l["text"]], "detail": []})
        elif _near(l["size"], BODY) and outcomes:
            outcomes[-1]["detail"].append(l["text"])
        prev = l
    rec["outcomes"] = [{"title": join_wrapped(o["title"]),
                        "detail": join_wrapped(o["detail"])} for o in outcomes]

    # --- footer stats: 16pt labels above 20pt values, paired by x position
    labels = [l for l in right if _near(l["size"], BODY)]
    values = [l for l in right if _near(l["size"], STAT_VALUE)]
    stats = []
    if labels and values:
        # Each stat box is one label line + the value line under it. Words on
        # the same row belong to different boxes, so split rows by gap first.
        def boxes(rows):
            out = []
            for r in rows:
                cur, prev = [], None
                for w in r["words"]:
                    if prev is not None and w["x0"] - prev["x1"] > 40:
                        out.append(cur)
                        cur = []
                    cur.append(w)
                    prev = w
                if cur:
                    out.append(cur)
            return [(c[0]["x0"], clean(" ".join(w["text"] for w in c))) for c in out]

        lab, val = boxes(labels), boxes(values)
        for x, text in lab:
            match = min(val, key=lambda v: abs(v[0] - x), default=None)
            if match and abs(match[0] - x) < 30:
                stats.append({"label": text, "value": match[1]})
    rec["stats"] = stats

    # Domain/Industry and Location become filters; every other stat box is a
    # highlight shown on the card and in the preview.
    rec["industries"], rec["locations"], rec["highlights"] = [], [], []
    for s in stats:
        k = s["label"].lower()
        if k in INDUSTRY_LABELS:
            rec["industries"] = split_values(s["value"])
        elif k in LOCATION_LABELS:
            rec["locations"] = split_values(s["value"])
        else:
            rec["highlights"].append(s)

    # --- sanity checks, printed by the build
    w = rec["warnings"]
    if not rec["title"]:
        w.append("no title found")
    if not rec["tags"]:
        w.append("no tag chips found")
    if not rec["outcomes"]:
        w.append("no outcomes found")
    if len(rec["description"]) < 60:
        w.append("description looks short")
    if not rec["industries"]:
        w.append("no Domain/Industry stat")
    if not rec["locations"]:
        w.append("no Location stat")
    return rec


# ---------------------------------------------------------------- clients

def client_from_filename(filename, known):
    """Pick the client for a file.

    `known` maps a filename prefix (e.g. "ryanair", "octopus") to a display
    name. The longest matching prefix wins, so "octopus-investments" can be
    told apart from "octopus-group" when both are listed.
    """
    stem = re.sub(r"\.pdf$", "", filename, flags=re.I).lower()
    best = None
    for prefix, name in known.items():
        p = prefix.lower().strip("-")
        if stem == p or stem.startswith(p + "-"):
            if best is None or len(p) > len(best[0]):
                best = (p, name)
    if best:
        return best[1]
    first = stem.split("-")[0]
    return first.title() if first else "Untitled"


if __name__ == "__main__":
    out = [dict(parse_pdf(p), file=p.split("/")[-1]) for p in sys.argv[1:]]
    for r in out:
        r.pop("raw_text", None)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
