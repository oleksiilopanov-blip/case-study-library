#!/usr/bin/env python3
"""
Build the Euristiq case-study library.

    python3 build.py --out dist      # site folder: index.html, pdfs/, img/
    python3 build.py --embed         # one self-contained HTML file (no previews
                                     # at full size; PDFs inlined) for Slack/email

Everything shown on the site is read from the live text of the PDFs in pdfs/.
overrides.json holds the few things a PDF can't say about itself: the client
name for each filename, tag spelling fixes, and per-file corrections.
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract import parse_pdf, client_from_filename  # noqa: E402

CARD_W = 720      # px, card thumbnail (shown ~360px wide, so 2x)
FULL_W = 1600     # px, preview image
# The card shows the right-hand visual of the one-pager (client logo bar +
# product image), in PDF points on the 1920x1080 template.
CARD_CROP = (1035, 160, 1835, 833)


# ---------------------------------------------------------------- images

def render_pages(pdf_path):
    """Return a PIL image of page 1, or None."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        doc = pdfium.PdfDocument(pdf_path)
        try:
            page = doc[0]
            return page.render(scale=FULL_W / page.get_size()[0]).to_pil().convert("RGB")
        finally:
            doc.close()
    except Exception:
        return None


def card_crop(im):
    """Cut the product visual out of a page render; whole page if the page
    isn't the 1920x1080 template."""
    k = im.width / 1920
    if abs(im.height / k - 1080) > 2:
        return im
    return im.crop(tuple(round(v * k) for v in CARD_CROP))


def jpeg(im, width, quality):
    from PIL import Image
    if im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


# ---------------------------------------------------------------- overrides

OVERRIDABLE = ("title", "client", "description", "tags", "industries",
               "locations", "hidden", "internal")


def load_overrides(path):
    if not os.path.exists(path):
        return {}, {}, {}, {}
    with open(path, encoding="utf-8") as fh:
        ov = json.load(fh)
    files = dict(ov.get("files", {}))
    # Older format: per-file entries at the top level, keyed by filename.
    files.update({k: v for k, v in ov.items() if k.lower().endswith(".pdf")})
    return (ov.get("clients", {}), ov.get("tag_aliases", {}),
            ov.get("industry_aliases", {}), files)


def alias(values, table):
    """Apply spelling fixes, case-insensitively, and drop duplicates."""
    low = {k.lower(): v for k, v in table.items()}
    out, seen = [], set()
    for v in values:
        v = low.get(v.lower(), v)
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def download_name(rec):
    """'Client - Title.pdf', without repeating the client if the title has it."""
    title, client = rec["title"], rec["client"]
    if rec.get("confidential") or client.lower() in title.lower():
        base = title
    else:
        base = f"{client} - {title}"
    base = re.sub(r'[\\/:*?"<>|]+', "", base)
    base = re.sub(r"\s+", " ", base).strip(" .")[:120]
    return f"Euristiq case study - {base}.pdf"


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, "pdfs"))
    ap.add_argument("--out", default=os.path.join(HERE, "dist"))
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--title", default="Case Study Library · Euristiq")
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    pdfs = sorted(f for f in os.listdir(args.src) if f.lower().endswith(".pdf"))
    if not pdfs:
        sys.exit(f"No PDFs found in {args.src}")

    clients, tag_alias, ind_alias, file_ov = load_overrides(
        os.path.join(HERE, "overrides.json"))

    print(f"Reading {len(pdfs)} PDFs from {args.src}\n" + "-" * 72)
    records, problems = [], []
    for f in pdfs:
        path = os.path.join(args.src, f)
        rec = parse_pdf(path)
        rec["file"] = f
        rec["slug"] = re.sub(r"[^a-z0-9]+", "-", os.path.splitext(f)[0].lower()).strip("-")
        rec["client"] = client_from_filename(f, clients)
        rec["confidential"] = f.lower().startswith("confidential")
        for field, value in file_ov.get(f, {}).items():
            if field in OVERRIDABLE:
                rec[field] = value
        rec["tags"] = alias(rec.get("tags", []), tag_alias)
        rec["industries"] = alias(rec.get("industries", []), ind_alias)
        rec["title"] = rec.get("title") or rec["client"]
        rec["size_bytes"] = os.path.getsize(path)
        records.append(rec)
        warn = rec.get("warnings", [])
        if warn:
            problems.append((f, warn))
        print(f"  {f[:44]:44} {len(rec.get('tags', [])):2} tags "
              f"{len(rec.get('outcomes', [])):2} outcomes  {rec['client']}"
              + ("   !! " + "; ".join(warn) if warn else ""))

    records = [r for r in records if not r.get("hidden")]
    records.sort(key=lambda r: r["title"].lower())

    # ---------------------------------------------------------- write
    os.makedirs(args.out, exist_ok=True)
    if not args.embed:
        for sub in ("pdfs", "img"):
            p = os.path.join(args.out, sub)
            if os.path.isdir(p):
                shutil.rmtree(p)      # removed case studies must not linger
            os.makedirs(p, exist_ok=True)

    payload = []
    for rec in records:
        src = os.path.join(args.src, rec["file"])
        item = {
            "id": rec["slug"],
            "title": rec["title"],
            "client": rec["client"],
            "confidential": rec["confidential"],
            "internal": bool(rec.get("internal")),
            "description": rec.get("description", ""),
            "tags": rec.get("tags", []),
            "industries": rec.get("industries", []),
            "locations": rec.get("locations", []),
            "highlights": rec.get("highlights", []),
            "outcomes": rec.get("outcomes", []),
            "raw": rec.get("raw_text", ""),
            "bytes": rec["size_bytes"],
            "dl": download_name(rec),
            "thumb": None, "full": None, "href": "",
        }
        im = None if args.no_images else render_pages(src)
        if args.embed:
            if im is not None:
                item["thumb"] = "data:image/jpeg;base64," + base64.b64encode(
                    jpeg(card_crop(im), CARD_W // 2, 72)).decode()
                item["full"] = "data:image/jpeg;base64," + base64.b64encode(
                    jpeg(im, 1200, 72)).decode()
            with open(src, "rb") as fh:
                item["data"] = base64.b64encode(fh.read()).decode()
        else:
            shutil.copy2(src, os.path.join(args.out, "pdfs", rec["slug"] + ".pdf"))
            item["href"] = f"pdfs/{rec['slug']}.pdf"
            if im is not None:
                for kind, src_im, w, q in (("card", card_crop(im), CARD_W, 78),
                                           ("full", im, FULL_W, 82)):
                    name = f"img/{rec['slug']}-{kind}.jpg"
                    with open(os.path.join(args.out, name), "wb") as fh:
                        fh.write(jpeg(src_im, w, q))
                    item["thumb" if kind == "card" else "full"] = name
        payload.append(item)

    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as fh:
        html = fh.read()
    def asset(name):
        with open(os.path.join(HERE, "assets", name), encoding="utf-8") as fh:
            return fh.read()

    logo = re.sub(r"<svg ", '<svg class="logo" role="img" aria-label="Euristiq" ',
                  asset("logo-wordmark-white.svg"), count=1)
    icons = re.sub(r"<!--.*?-->", "", asset("icons.svg"), flags=re.S)

    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_js = data_js.replace("</", "<\\/")          # never break out of <script>
    html = (html.replace("__LOGO__", logo)
                .replace("__ICONS__", icons)
                .replace("__PAGE_TITLE__", args.title)
                .replace("__DATA__", data_js)
                .replace("__CFG__", json.dumps({"embedded": args.embed})))

    name = "library-standalone.html" if args.embed else "index.html"
    dest = os.path.join(args.out, name)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(html)

    if not args.embed:
        meta = [{k: v for k, v in it.items() if k not in ("data", "raw")} for it in payload]
        with open(os.path.join(args.out, "library.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        for extra in ("_headers", "robots.txt"):
            if os.path.exists(os.path.join(HERE, extra)):
                shutil.copy2(os.path.join(HERE, extra), os.path.join(args.out, extra))
        # Cloudflare Pages reads functions/ from the project root. Copying it
        # into the output too covers projects whose root is set to dist/.
        fn_src = os.path.join(HERE, "functions")
        if os.path.isdir(fn_src):
            fn_dst = os.path.join(args.out, "functions")
            if os.path.isdir(fn_dst):
                shutil.rmtree(fn_dst)
            shutil.copytree(fn_src, fn_dst)
            print(f"  copied functions/ -> {fn_dst}")

    # ---------------------------------------------------------- report
    print("-" * 72)
    print(f"  {len(payload)} case studies -> {dest} "
          f"({os.path.getsize(dest) / 1048576:.2f} MB)")
    facets = {
        "clients": {p["client"] for p in payload},
        "industries": {v for p in payload for v in p["industries"]},
        "tags": {v for p in payload for v in p["tags"]},
        "locations": {v for p in payload for v in p["locations"]},
    }
    print("  filters: " + ", ".join(f"{len(v)} {k}" for k, v in facets.items()))
    if problems:
        print("\n  NEEDS A LOOK (the site still builds):")
        for f, w in problems:
            print(f"    {f}: {'; '.join(w)}")
    print()


if __name__ == "__main__":
    main()
