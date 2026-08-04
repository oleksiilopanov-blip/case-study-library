#!/usr/bin/env python3
"""
Euristiq case-study PDF -> structured JSON extractor.

Parses the standard Euristiq one-pager template:
    <Title>                     (largest font, 1-3 lines)
    <Service tag chips>         (font one step larger than body)
    <Description>               (two-column body text)
    Technology Stack
    <Tech tag chips>
    AWS Services                (optional)
    <AWS tag chips>
    Outcomes
    <bulleted outcomes>

Usage:  python3 extract.py <out.json> <file1.pdf> [file2.pdf ...]
"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

import pdfplumber

# ---------------------------------------------------------------- constants

# Section headings that terminate the "header zone" and open a tag/body zone.
SECTION_ALIASES = {
    "technology stack": "tech",
    "tech stack": "tech",
    "technologies": "tech",
    "technology": "tech",
    "aws services": "aws",
    "aws service": "aws",
    "cloud services": "aws",
    "azure services": "aws",
    "outcomes": "outcomes",
    "outcome": "outcomes",
    "key outcomes": "outcomes",
    "results": "outcomes",
    "key results": "outcomes",
    "business outcomes": "outcomes",
}

# Marketing call-to-action / footer lines that are not real content.
CTA_PATTERNS = [
    r"^discuss your project$",
    r"^contact us$",
    r"^let'?s talk$",
    r"^get in touch$",
    r"^book a call$",
    r"^learn more$",
    r"^read more$",
    r"^euristiq(\.com)?$",
    r"^www\.",
    r"^https?://",
    r"^\S+@\S+\.\S+$",
    r"^\+?\d[\d\s()\-]{7,}$",
    r"^(page\s*)?\d+\s*(/|of)\s*\d+$",
    r"^©",
    r"^all rights reserved",
]
CTA_RE = re.compile("|".join(CTA_PATTERNS), re.I)

# Cyrillic/Greek characters that render identically to Latin ones. Figma files
# authored by mixed-keyboard-layout users pick these up silently and they break
# keyword search ("Сompanies" with a Cyrillic C never matches "companies").
HOMOGLYPHS = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m",
    "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j",
    "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I",
    "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P",
    "Τ": "T", "Χ": "X", "ο": "o", "α": "a",
}
PUNCT_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", "…": "...", "ﬀ": "ff", "ﬁ": "fi",
    "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "­": "",
    "​": "", "‌": "", "‍": "", "﻿": "",
}

TAG_GAP = 20.0       # horizontal gap (pt) that separates two tag chips
LINE_TOL = 4.0       # vertical tolerance (pt) for grouping words into a line
BULLET_X_MAX = 64.0  # bullet glyphs sit left of the text column
BULLET_W_MAX = 14.0  # and are small


# ---------------------------------------------------------------- helpers

def clean_text(s):
    """Normalise homoglyphs, smart punctuation and whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(HOMOGLYPHS.get(ch, PUNCT_MAP.get(ch, ch)) for ch in s)
    # Repair words split by a stray space before a trailing fragment
    # ("device s" -> "devices"), a common Figma text-layer artifact.
    s = re.sub(r"\b([A-Za-z]{4,}) ([a-z]{1,2})\b(?=[\s,.;:)]|$)",
               lambda m: m.group(1) + m.group(2)
               if m.group(2) in ("s", "es", "d", "ed", "ly", "er")
               else m.group(0), s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def norm_key(s):
    """Aggressive normalisation for comparison / dedup keys."""
    return re.sub(r"[^a-z0-9]+", "", clean_text(s).lower())


def group_lines(words):
    """Group extracted words into visual lines, sorted top-to-bottom."""
    buckets = defaultdict(list)
    for w in words:
        buckets[round(w["top"] / LINE_TOL)].append(w)
    lines = []
    for key in sorted(buckets):
        ws = sorted(buckets[key], key=lambda w: w["x0"])
        lines.append({
            "words": ws,
            "top": min(w["top"] for w in ws),
            "bottom": max(w["bottom"] for w in ws),
            "x0": min(w["x0"] for w in ws),
            "x1": max(w["x1"] for w in ws),
            "size": max(round(w["size"], 1) for w in ws),
            "text": clean_text(" ".join(w["text"] for w in ws)),
        })
    # Merge lines that overlap vertically (same visual row split by tolerance)
    merged = []
    for ln in lines:
        if merged and ln["top"] < merged[-1]["bottom"] - 2:
            prev = merged[-1]
            prev["words"] = sorted(prev["words"] + ln["words"], key=lambda w: w["x0"])
            prev["bottom"] = max(prev["bottom"], ln["bottom"])
            prev["x1"] = max(prev["x1"], ln["x1"])
            prev["size"] = max(prev["size"], ln["size"])
            prev["text"] = clean_text(" ".join(w["text"] for w in prev["words"]))
        else:
            merged.append(ln)
    return [ln for ln in merged if ln["text"]]


def split_chips(line):
    """Split one visual line into tag chips on wide horizontal gaps."""
    chips, cur, prev = [], [], None
    for w in line["words"]:
        if prev is not None and (w["x0"] - prev["x1"]) > TAG_GAP:
            chips.append(cur)
            cur = []
        cur.append(w)
        prev = w
    if cur:
        chips.append(cur)
    out = []
    for chip in chips:
        t = clean_text(" ".join(w["text"] for w in chip))
        t = t.strip(" ,;•·|/")
        if t and not CTA_RE.match(t):
            out.append(t)
    return out


def find_gutter(lines):
    """Locate the x of the two-column gutter, or None for single column."""
    mids = []
    for ln in lines:
        best, prev = None, None
        for w in ln["words"]:
            if prev is not None:
                gap = w["x0"] - prev["x1"]
                if gap > TAG_GAP and (best is None or gap > best[0]):
                    best = (gap, (prev["x1"] + w["x0"]) / 2)
            prev = w
        if best:
            mids.append(best[1])
    if len(mids) < 2:
        return None
    mids.sort()
    median = mids[len(mids) // 2]
    # Only trust it if the candidate gutters actually cluster together.
    tight = [m for m in mids if abs(m - median) < 60]
    return median if len(tight) >= max(2, len(mids) // 2) else None


def join_wrapped(parts):
    """Join column lines, repairing words hyphenated across a line break."""
    out = ""
    for t in parts:
        if not t:
            continue
        if not out:
            out = t
        elif out.endswith("-") and re.match(r"^[a-z]", t):
            # "cloud-" + "based" -> "cloud-based"
            out = out + t
        else:
            out = out + " " + t
    return clean_text(out)


def read_columns(lines):
    """Reassemble body text in reading order, handling two columns."""
    gutter = find_gutter(lines)
    if gutter is None:
        return join_wrapped([ln["text"] for ln in lines])
    left, right = [], []
    for ln in lines:
        lw = [w for w in ln["words"] if w["x0"] < gutter]
        rw = [w for w in ln["words"] if w["x0"] >= gutter]
        if lw:
            left.append(clean_text(" ".join(w["text"] for w in lw)))
        if rw:
            right.append(clean_text(" ".join(w["text"] for w in rw)))
    return join_wrapped(left) + (" " if left and right else "") + join_wrapped(right)


def bullet_tops(page):
    """Vertical positions of bullet marker glyphs (drawn as vector shapes)."""
    tops = []
    for s in list(page.rects) + list(page.curves):
        if (s["x0"] < BULLET_X_MAX
                and (s["x1"] - s["x0"]) <= BULLET_W_MAX
                and (s["bottom"] - s["top"]) <= BULLET_W_MAX
                and (s["x1"] - s["x0"]) > 0.5):
            tops.append((s["top"] + s["bottom"]) / 2)
    return sorted(tops)


def to_bullets(lines, markers):
    """Turn outcome lines into bullets, re-joining wrapped continuations."""
    bullets = []
    for ln in lines:
        if CTA_RE.match(ln["text"]):
            continue
        has_marker = any(ln["top"] - 4 <= m <= ln["bottom"] + 4 for m in markers)
        starts_new = bool(re.match(r"^[A-Z0-9~$€£(\"']", ln["text"]))
        if bullets and not has_marker and not starts_new:
            bullets[-1] = clean_text(bullets[-1] + " " + ln["text"])
        elif bullets and not has_marker and not markers and not starts_new:
            bullets[-1] = clean_text(bullets[-1] + " " + ln["text"])
        else:
            bullets.append(ln["text"])
    return [re.sub(r"\s+", " ", b).strip(" •-–;,") for b in bullets if b.strip()]


def dedup(seq):
    seen, out = set(), []
    for x in seq:
        k = norm_key(x)
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


# Chips naming a managed cloud service belong in the Cloud facet even when the
# deck lists them under "Technology Stack" (the B2Buster one-pager does this).
CLOUD_CHIP_RE = re.compile(
    r"^(aws|amazon|azure|google cloud|gcp)\b|"
    r"^(s3|ec2|ecs|eks|rds|sqs|sns|ses|elb|iam|vpc|lambda|cognito|dynamodb|"
    r"cloudfront|cloudwatch|cloudtrail|cloudformation|fargate|bedrock|"
    r"sagemaker|api gateway|route ?53|aurora|redshift|athena|glue|kinesis|"
    r"eventbridge|step functions|secrets manager|elasticache)\b", re.I)

# Derived industry hints: first match wins, checked against the full text.
INDUSTRY_RULES = [
    ("Agriculture", r"\bagritech\b|\bagricultur|\bfarm(ing|er)|\bcrop|\btractor"),
    ("Insurance", r"\binsuranc|\binsurer|\bunderwrit|\bactuar|\bclaims process"),
    ("Energy & Utilities", r"\butilit(y|ies)|\bsmart grid|\brenewab|\bsolar\b|\bwind farm|\bmeter(ing)?\b|\benergy\b"),
    ("Logistics & Supply Chain", r"\blogistic|\bwarehous|\bfleet\b|\bsupply chain|\bfreight|\bshipping|\btelematic|\binventory\b"),
    ("Manufacturing", r"\bmanufactur|\bfactory|\bproduction line|\bindustrial automation|\bshop floor"),
    ("Healthcare & Life Sciences", r"\bhealthcare|\bpatient|\bclinical|\bmedical|\bhospital|\bpharma"),
    ("Financial Services", r"\bfintech|\bbanking\b|\bpayment|\btrading\b|\blending\b|\bcredit\b"),
    ("Retail & E-commerce", r"\be-?commerce|\bretail|\bcheckout|\bstorefront|\bshopper|\bmerchandis"),
    ("HR & Workforce", r"\bvendor management|\bworkforce|\bstaffing|\btimesheet|\brecruit|\bcontingent labor|\bhr\b|\bpayroll"),
    ("Telecom", r"\btelecom|\b5g\b|\bnetwork operator|\bbroadband|\bsubscriber"),
    ("Real Estate & Construction", r"\breal estate|\bconstruction|\bbuilding management|\bfacilit(y|ies) management|\bproptech"),
    ("Sales & Marketing", r"\bgo-?to-?market\b|\bgtm\b|\bb2b sales|\bcrm\b|\blead generation|\bsales team"),
    ("Transportation & Mobility", r"\bmobility\b|\bautomotive|\bvehicle|\bdriver\b|\brailway|\baviation"),
    ("Media & Entertainment", r"\bstreaming\b|\bmedia\b|\bbroadcast|\bpublishing|\bgaming\b"),
    ("Education", r"\bedtech|\be-?learning|\bstudent|\bcourse\b|\bcurricul"),
]


def derive_industries(text, limit=2):
    """Best-effort industry guesses. Always reviewed by a human via overrides."""
    low = clean_text(text).lower()
    scored = []
    for name, pattern in INDUSTRY_RULES:
        hits = len(re.findall(pattern, low))
        if hits:
            scored.append((hits, name))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:limit]]


# ---------------------------------------------------------------- core

def parse_pdf(path):
    """Parse one case-study PDF into a structured record."""
    all_lines, markers, npages = [], [], 0
    raw_pages = []
    with pdfplumber.open(path) as pdf:
        npages = len(pdf.pages)
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["size", "fontname"])
            page_lines = group_lines(words)
            for ln in page_lines:
                ln["page"] = page.page_number
            all_lines.extend(page_lines)
            markers.extend(bullet_tops(page))
            raw_pages.append(clean_text(page.extract_text() or ""))

    warnings = []
    if not all_lines:
        return {"warnings": ["No extractable text - this PDF is image-only and needs OCR."],
                "pages": npages, "raw_text": "", "needs_ocr": True}

    # --- locate section headings
    boundaries = []  # (index, kind)
    for i, ln in enumerate(all_lines):
        key = ln["text"].strip().rstrip(":").lower()
        if key in SECTION_ALIASES and len(ln["words"]) <= 4:
            boundaries.append((i, SECTION_ALIASES[key]))

    first_boundary = boundaries[0][0] if boundaries else len(all_lines)
    header_zone = all_lines[:first_boundary]

    # --- title: leading run of largest-font lines
    title_lines = []
    if header_zone:
        max_size = max(ln["size"] for ln in header_zone)
        for ln in header_zone:
            if abs(ln["size"] - max_size) < 0.6:
                title_lines.append(ln)
            else:
                break
    title = clean_text(" ".join(ln["text"] for ln in title_lines))
    title = re.sub(r"\s*\.\s*$", "", title).strip()

    rest = header_zone[len(title_lines):]

    # --- service chips vs description: chips use the larger of the two sizes
    services, desc_lines = [], []
    if rest:
        sizes = sorted({ln["size"] for ln in rest}, reverse=True)
        if len(sizes) >= 2:
            chip_size, body_size = sizes[0], sizes[-1]
            for ln in rest:
                (services if abs(ln["size"] - chip_size) < 0.6 else desc_lines).append(ln)
        else:
            # Single font size: chips are the rows that contain wide gaps or
            # sit above the first long prose line.
            for ln in rest:
                looks_chippy = len(split_chips(ln)) > 1 and len(ln["text"].split()) <= 12
                if looks_chippy and not desc_lines:
                    services.append(ln)
                else:
                    desc_lines.append(ln)
        if not services and desc_lines:
            warnings.append("No service tags detected in the header area.")

    service_tags = dedup([c for ln in services for c in split_chips(ln)])
    description = read_columns(desc_lines)

    # --- zones after each heading
    zones = defaultdict(list)
    for n, (idx, kind) in enumerate(boundaries):
        end = boundaries[n + 1][0] if n + 1 < len(boundaries) else len(all_lines)
        zones[kind].extend(all_lines[idx + 1:end])

    tech_raw = dedup([c for ln in zones["tech"] for c in split_chips(ln)])
    aws_tags = dedup([c for ln in zones["aws"] for c in split_chips(ln)])
    outcomes = to_bullets(zones["outcomes"], markers)

    # Route managed-cloud chips into the cloud facet regardless of which
    # section of the deck they were printed in.
    moved = [c for c in tech_raw if CLOUD_CHIP_RE.match(c)]
    tech_tags = [c for c in tech_raw if not CLOUD_CHIP_RE.match(c)]
    aws_tags = dedup(aws_tags + moved)

    if not title:
        warnings.append("Could not detect a title.")
    if not tech_tags:
        warnings.append("No 'Technology Stack' tags found.")
    if not outcomes:
        warnings.append("No 'Outcomes' bullets found.")
    if len(description) < 80:
        warnings.append("Description looks very short - check the layout.")

    full_text = "\n".join(filter(None, [
        title, " | ".join(service_tags), description,
        " | ".join(tech_tags), " | ".join(aws_tags), "\n".join(outcomes),
    ]))

    return {
        "title": title,
        "services": service_tags,
        "tech": tech_tags,
        "aws": aws_tags,
        "industries": derive_industries(full_text),
        "description": description,
        "outcomes": outcomes,
        "pages": npages,
        "full_text": full_text,
        "raw_text": "\n".join(raw_pages),
        "warnings": warnings,
        "needs_ocr": False,
    }


def nice_name(filename):
    """Human-ish fallback label from a filename."""
    s = re.sub(r"\.pdf$", "", filename, flags=re.I)
    s = re.sub(r"^[0-9a-f]{6,}[-_]", "", s)           # uploaded-file hash prefix
    s = re.sub(r"(pdf)?compressed$", "", s, flags=re.I)
    s = re.sub(r"[-_]+", " ", s).strip()
    return s.title() if s else "Untitled"


OVERRIDABLE = ("title", "client", "industries", "services", "tech",
               "aws", "description", "year", "hidden", "internal")


def apply_overrides(records, path):
    """Merge manual corrections from overrides.json (keyed by file or slug)."""
    if not path or not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        ov = json.load(f)
    applied = 0
    for rec in records:
        for key in (rec["file"], rec["slug"]):
            if key in ov:
                for field, value in ov[key].items():
                    if field in OVERRIDABLE:
                        rec[field] = value
                        applied += 1
                # Keep search text in sync with corrected metadata.
                rec["full_text"] = "\n".join(filter(None, [
                    rec.get("title", ""), " | ".join(rec.get("services", [])),
                    rec.get("description", ""), " | ".join(rec.get("tech", [])),
                    " | ".join(rec.get("aws", [])),
                    " | ".join(rec.get("industries", [])),
                    "\n".join(rec.get("outcomes", [])),
                ]))
                break
    return applied


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    out_path, pdf_paths = sys.argv[1], sys.argv[2:]
    records = []
    for p in pdf_paths:
        rec = parse_pdf(p)
        rec["file"] = os.path.basename(p)
        rec["slug"] = re.sub(r"[^a-z0-9]+", "-", nice_name(os.path.basename(p)).lower()).strip("-")
        rec["client"] = nice_name(os.path.basename(p))
        rec["size_bytes"] = os.path.getsize(p)
        if not rec.get("title"):
            rec["title"] = rec["client"]
        records.append(rec)
        flag = "  !! " + "; ".join(rec["warnings"]) if rec["warnings"] else ""
        print(f"[ok] {rec['file'][:42]:42} {len(rec.get('services', [])):2}svc "
              f"{len(rec.get('tech', [])):2}tech {len(rec.get('aws', [])):2}cloud "
              f"{len(rec.get('outcomes', [])):2}out{flag}")

    n = apply_overrides(records, os.path.join(os.path.dirname(out_path) or ".",
                                              "overrides.json"))
    if n:
        print(f"[overrides] applied {n} manual corrections")

    records = [r for r in records if not r.get("hidden")]
    records.sort(key=lambda r: r["title"].lower())
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(records)} records -> {out_path}")


if __name__ == "__main__":
    main()
