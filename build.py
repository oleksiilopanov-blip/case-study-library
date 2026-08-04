#!/usr/bin/env python3
"""
Build the Euristiq case-study web library.

    python3 build.py                 # folder build  -> out/index.html + out/pdfs/
    python3 build.py --embed         # single-file build -> out/library-standalone.html
    python3 build.py --src PDdir     # where the source PDFs live (default: pdfs)

The folder build works by double-click from a local disk AND uploads unchanged
to a web server. The --embed build inlines every PDF as base64 so the whole
library is one shareable file.
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import parse_pdf, nice_name, apply_overrides  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
THUMB_W = 420
THUMB_Q = 72


def _encode_thumb(im):
    """Crop to 16:9 off the top of the page, downscale, return a data URI."""
    from PIL import Image
    im = im.convert("RGB")
    w, h = im.size
    # The title and tag chips live at the top, so a top crop stays legible small.
    crop_h = min(h, int(w * 9 / 16))
    im = im.crop((0, 0, w, crop_h))
    if w != THUMB_W:
        im = im.resize((THUMB_W, max(1, int(THUMB_W * crop_h / w))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=THUMB_Q, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def make_thumb(pdf_path):
    """Render page 1 to a small base64 JPEG data URI (None if unavailable).

    Prefers pypdfium2 — a pure wheel with no system dependencies, so this
    works unchanged on a hosted build runner where poppler isn't installed.
    Falls back to poppler's pdftoppm if pypdfium2 isn't present.
    """
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_path)
        try:
            page = doc[0]
            width = page.get_size()[0]
            im = page.render(scale=THUMB_W / width).to_pil()
            return _encode_thumb(im)
        finally:
            doc.close()
    except ImportError:
        pass
    except Exception:
        return None

    try:
        from PIL import Image
        out = subprocess.run(
            ["pdftoppm", "-r", "50", "-png", "-f", "1", "-l", "1",
             "-singlefile", pdf_path, "/tmp/_thumb"],
            capture_output=True, timeout=60)
        if out.returncode != 0 or not os.path.exists("/tmp/_thumb.png"):
            return None
        return _encode_thumb(Image.open("/tmp/_thumb.png"))
    except Exception:
        return None
    finally:
        if os.path.exists("/tmp/_thumb.png"):
            os.remove("/tmp/_thumb.png")


def safe_filename(rec):
    """Presentable download filename: 'Client - Title.pdf'."""
    title, client = rec.get("title", ""), rec["client"]
    # Prefix the client only when the title doesn't already name them, so we
    # never ship "DMI - Digital Twin ... for DMI.pdf".
    if not title:
        base = client
    elif client.lower() in title.lower():
        base = title
    else:
        base = f"{client} - {title}"
    base = re.sub(r'[\\/:*?"<>|]+', "", base).strip()
    base = re.sub(r"\s+", " ", base)[:110].rstrip(" .")
    return base + ".pdf"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, "pdfs"))
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--embed", action="store_true",
                    help="inline the PDFs into one standalone HTML file")
    ap.add_argument("--title", default="Euristiq — Case Study Library")
    ap.add_argument("--no-thumbs", action="store_true")
    args = ap.parse_args()

    pdfs = sorted(f for f in os.listdir(args.src) if f.lower().endswith(".pdf"))
    if not pdfs:
        sys.exit(f"No PDFs found in {args.src}")

    print(f"Parsing {len(pdfs)} PDFs from {args.src}\n" + "-" * 68)
    records, problems = [], []
    for f in pdfs:
        path = os.path.join(args.src, f)
        rec = parse_pdf(path)
        rec["file"] = f
        rec["client"] = nice_name(f)
        rec["slug"] = re.sub(r"[^a-z0-9]+", "-", rec["client"].lower()).strip("-")
        rec["size_bytes"] = os.path.getsize(path)
        if not rec.get("title"):
            rec["title"] = rec["client"]
        records.append(rec)
        if rec["warnings"]:
            problems.append((f, rec["warnings"]))
        print(f"  {f[:40]:40} {len(rec.get('services',[])):2}svc "
              f"{len(rec.get('tech',[])):2}tech {len(rec.get('aws',[])):2}cloud "
              f"{len(rec.get('outcomes',[])):2}out"
              + ("   !! " + "; ".join(rec["warnings"]) if rec["warnings"] else ""))

    n = apply_overrides(records, os.path.join(HERE, "overrides.json"))
    if n:
        print(f"\n  overrides.json: applied {n} manual corrections")
    records = [r for r in records if not r.get("hidden")]
    records.sort(key=lambda r: r["title"].lower())

    # ---------------------------------------------------------- assemble
    os.makedirs(args.out, exist_ok=True)
    pdf_out = os.path.join(args.out, "pdfs")
    if not args.embed:
        # Rebuild from scratch so renamed or removed case studies don't linger.
        if os.path.isdir(pdf_out):
            shutil.rmtree(pdf_out)
        os.makedirs(pdf_out, exist_ok=True)

    used, payload = set(), []
    for rec in records:
        src = os.path.join(args.src, rec["file"])
        dl = safe_filename(rec)

        # stable, collision-free on-disk name
        name = re.sub(r"[^a-z0-9]+", "-", os.path.splitext(dl)[0].lower()).strip("-")
        cand, k = name + ".pdf", 2
        while cand in used:
            cand, k = f"{name}-{k}.pdf", k + 1
        used.add(cand)

        item = {
            "title": rec["title"], "client": rec["client"],
            "services": rec.get("services", []), "industries": rec.get("industries", []),
            "tech": rec.get("tech", []), "aws": rec.get("aws", []),
            "description": rec.get("description", ""),
            "outcomes": rec.get("outcomes", []),
            "raw": rec.get("raw_text", ""),
            "internal": bool(rec.get("internal")),
            "flags": ["Internal only"] if rec.get("internal") else ["Shareable externally"],
            "pages": rec.get("pages", 1), "bytes": rec["size_bytes"],
            "file": rec["file"], "dl": dl,
            "thumb": None if args.no_thumbs else make_thumb(src),
        }
        if args.embed:
            with open(src, "rb") as fh:
                item["data"] = base64.b64encode(fh.read()).decode()
            item["href"] = ""
        else:
            shutil.copy2(src, os.path.join(pdf_out, cand))
            item["href"] = "pdfs/" + cand
        payload.append(item)

    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as fh:
        html = fh.read()

    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_js = data_js.replace("</", "<\\/")          # never break out of <script>
    cfg = json.dumps({"embedded": bool(args.embed)})

    html = (html.replace("__PAGE_TITLE__", args.title)
                .replace("__DATA__", data_js)
                .replace("__CFG__", cfg))

    name = "library-standalone.html" if args.embed else "index.html"
    dest = os.path.join(args.out, name)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(html)

    if not args.embed:
        # Machine-readable copy so admin.html can reopen the library later.
        meta = [{k: v for k, v in item.items() if k != "data"} for item in payload]
        with open(os.path.join(args.out, "library.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)

        # Static extras + Pages Functions. Cloudflare reads functions/ from the
        # build output directory, so copy it there rather than relying on root.
        for extra in ("_headers", "robots.txt"):
            src = os.path.join(HERE, extra)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(args.out, extra))
        fn_src = os.path.join(HERE, "functions")
        if os.path.isdir(fn_src):
            fn_dst = os.path.join(args.out, "functions")
            if os.path.isdir(fn_dst):
                shutil.rmtree(fn_dst)
            shutil.copytree(fn_src, fn_dst)
            print(f"  copied functions/ -> {fn_dst}")

    # ---------------------------------------------------------- report
    size = os.path.getsize(dest)
    print("-" * 68)
    print(f"  {len(payload)} case studies")
    print(f"  {dest}  ({size/1048576:.2f} MB)")
    if not args.embed:
        tot = sum(os.path.getsize(os.path.join(pdf_out, f)) for f in os.listdir(pdf_out))
        print(f"  {pdf_out}/  ({tot/1048576:.1f} MB, {len(os.listdir(pdf_out))} files)")
    facets = {k: len({v for r in payload for v in r[k]})
              for k in ("services", "industries", "tech", "aws")}
    print(f"  facets: " + ", ".join(f"{v} {k}" for k, v in facets.items()))
    if problems:
        print("\n  NEEDS A LOOK:")
        for f, w in problems:
            print(f"    {f}: {'; '.join(w)}")
    print()


if __name__ == "__main__":
    main()
