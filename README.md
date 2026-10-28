# Euristiq Case Study Library

A searchable library of Euristiq case-study one-pagers, shared by link.
Upload a PDF, and the site rebuilds itself.

- **Add a case study:** upload the PDF to [`pdfs/`](pdfs). That's the whole job.
- **One-time setup:** [SETUP.md](SETUP.md) (about 15 minutes)

**Keep this repository private.** The PDFs live in it, including the NDA ones.

## What the site does

- **Search** across every word in every PDF: titles, descriptions, tags,
  outcomes and the stat boxes. Several words narrow the search (all of them
  must match). Put a phrase in quotes to match it exactly: `"micro front end"`.
- **Filters**: Client, Domain, Services & technology, and Location. Filters in the
  same group widen the results (Novalume *or* Ryanair). Filters in different
  groups narrow them (Novalume *and* Europe). Each one shows how many case
  studies it would match.
- **Preview** any case study. You see the page with its full text, tags, stats
  and outcomes as real text you can select and copy. From there you can
  **download the PDF**, **open it in a new tab**, or **copy a link** to that
  case study.
- Every search and filter state is in the URL, so you can share a filtered view.

## Adding a case study

1. Export the one-pager from Figma as a PDF **with live text**. Don't outline or
   flatten the text, or there will be nothing to search.
2. Name the file `client-short-title.pdf`, for example `ryanair-legacy-web-app-modernization.pdf`.
   For NDA cases, start the name with `confidential-`.
3. On GitHub, open [`pdfs/`](pdfs) → **Add file → Upload files** → drag the
   PDFs in → **Commit changes**.
4. About a minute later, Cloudflare has rebuilt the site.

If the client is new, add it to `clients` in [`overrides.json`](overrides.json).
Otherwise it shows up as the first word of the filename, title-cased.

## What is read from the PDF

The build reads the 1920×1080 one-pager template:

| On the PDF | On the site |
|---|---|
| Big title | Card and preview title |
| Paragraph under the title | Description |
| Pill tags | **Services & technology** filter |
| `Outcomes` → bold line + text under it | Outcomes list |
| Stat box `Domain` or `Industry` | **Domain** filter (split on `\|`) |
| Stat box `Location` | **Location** filter |
| Any other stat box (`Scale`, `Delivery`, …) | Highlight on the card and in the preview |
| Filename prefix | **Client** filter, via `overrides.json` |

So to fix a tag, a title or an outcome, **fix it in Figma and re-export**. The
site will match the PDF.

## overrides.json: the things a PDF can't say

| Section | What it's for |
|---|---|
| `clients` | Filename prefix → client name. Two files with the same prefix (`novalume-…`, `octopus-…`) become one client with several cases. |
| `tag_aliases` | Merges spelling variants so a tag never appears twice (`UI/UX design` → `UX/UI design`). |
| `industry_aliases` | Same idea, for Domain values. |
| `files` | Per-file corrections keyed by filename: `title`, `client`, `description`, `tags`, `industries`, `locations`, `hidden: true` (leave it off the site), `internal: true` (INTERNAL ONLY badge). |

Example: give the SQL assistant case a domain and location without re-exporting:

```json
"files": {
  "confidential-ai-assistant-for-sql-database-interaction.pdf": {
    "industries": ["IT"],
    "locations": ["Europe"]
  }
}
```

## Removing a case study

Delete the file in `pdfs/` (open it → **⋯ → Delete file** → commit). Or set
`"hidden": true` for it under `files` in `overrides.json`.

## Who can see it

Anyone who has the link. There is no password: share the URL only with the
people who need it. Search engines are told not to index the site
(`robots.txt` and the `X-Robots-Tag` header in `_headers`).

To put a password back later, add a Cloudflare Pages Function in
`functions/_middleware.js` (it is in this repo's git history) and set the
`SITE_PASSWORD` environment variable in Cloudflare.

## Repository layout

```
pdfs/                  the case studies (drop new ones here)
overrides.json         client names, tag spelling fixes, per-file corrections
extract.py             reads title, tags, outcomes and stats out of each PDF
build.py               generates the site into dist/
template.html          the library UI (Euristiq DLS tokens, all CSS and JS inline)
assets/                Euristiq wordmark and DLS icons, inlined at build time
requirements.txt       pure-wheel dependencies, no system packages
_headers, robots.txt   security headers, keeps it out of search engines
```

## Building it locally (optional)

You never need to. Cloudflare builds the site on every push.

```bash
pip install -r requirements.txt
python3 build.py --out dist       # then open dist/index.html via a local server
python3 build.py --embed          # one self-contained HTML file, for email/Slack
```

The build prints every PDF with its tag and outcome counts, and lists anything
that **NEEDS A LOOK**, such as a missing Domain or Location stat box.
