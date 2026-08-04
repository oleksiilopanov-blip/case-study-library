# Euristiq Case Study Library

Searchable library of our case-study one-pagers. Push a PDF, the site rebuilds
itself.

- **Adding a case study:** upload the PDF to [`pdfs/`](pdfs) — that's the whole job.
- **Setup:** [SETUP.md](SETUP.md) (one time, ~15 minutes)

Cloudflare Pages reads the PDFs on every push, extracts the titles, tags,
outcomes and searchable text, and publishes the site. Nothing to run locally.

## Adding a case study

1. Open the [`pdfs/`](pdfs) folder here on GitHub.
2. **Add file → Upload files**, drag the PDFs in, **Commit changes**.
3. Wait about a minute. Cloudflare rebuilds and the library is live.

Export from Figma with **live text** — not flattened to an image — or there'll be
nothing to search. If a build says `No extractable text`, that's why.

## Removing one

Open the file in `pdfs/`, click the **⋯** menu → **Delete file** → commit. Or set
`"hidden": true` for it in `overrides.json` to keep the file but drop it from the
site.

## Fixing a wrong title, client or industry

Everything is read off the PDF. Where it guesses wrong — the client name is
guessed from the filename, and industries are inferred from the text — correct it
in [`overrides.json`](overrides.json), keyed by PDF filename:

```json
{
  "beeline.pdf": {
    "client": "Beeline Professional",
    "industries": ["HR & Workforce"],
    "internal": true
  }
}
```

| Field | Effect |
|---|---|
| `title`, `client`, `description` | replace what was extracted |
| `industries`, `services`, `tech`, `aws` | replace the tag lists |
| `internal` | `true` adds an **INTERNAL ONLY** badge and a Sharing filter |
| `hidden` | `true` leaves it out of the site entirely |

Commit the change and the site rebuilds.

## Who can see it

The whole site — including every PDF — sits behind a password enforced by
[`functions/_middleware.js`](functions/_middleware.js). The password itself is a
Cloudflare environment variable called `SITE_PASSWORD`; it is **not** in this
repo. Any username works, only the password is checked.

To change it: Cloudflare Pages → your project → **Settings → Environment
variables** → edit `SITE_PASSWORD` → redeploy.

If the variable is missing the site returns a 503 explaining that, rather than
serving the library unprotected.

**Keep this repository private.** The PDFs live in it.

## Repository layout

```
pdfs/                   the case studies (drop new ones here)
functions/
  _middleware.js        the password gate
extract.py              reads the Euristiq one-pager template out of a PDF
build.py                generates the site into dist/
template.html           the library UI — all CSS and JS inline
overrides.json          your manual corrections
requirements.txt        pure-wheel dependencies, no system packages
_headers, robots.txt    security headers, keeps it out of search engines
```

## Building it locally (optional)

Never required — Cloudflare does this on every push.

```bash
pip install -r requirements.txt
python3 build.py --out dist        # then open dist/index.html
python3 build.py --embed           # one self-contained file, for email/Slack
```

## How the parsing works

`extract.py` follows the one-pager template: the title is the largest font at
the top, service tags are the size above body text split on wide gaps, and the
Technology Stack / AWS Services / Outcomes sections are found by their headings.
Outcome bullets are located by their marker glyphs, so bullets that wrap onto a
second line are rejoined correctly.

It also repairs three things the Figma exports introduce, each of which would
otherwise break keyword search:

- Cyrillic look-alike letters — a Cyrillic `С` in "Сompanies" never matches a
  search for "companies"
- words split by a stray space — `device s` → `devices`
- words hyphenated across a line break — `cloud-` + `based` → `cloud-based`

Chips naming a managed cloud service (`AWS …`, `Amazon …`, `S3`, `Lambda`, …) are
routed to the **Cloud service** filter wherever they were printed in the deck, so
filtering stays consistent even though the decks aren't.
