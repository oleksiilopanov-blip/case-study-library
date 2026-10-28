# Setup — one time, about 15 minutes

Two accounts, both free: GitHub holds the files, Cloudflare builds and serves
them. After this, adding a case study is "upload a PDF to `pdfs/`".

---

## 1. Create the repository (5 min)

1. Go to **github.com/new**.
2. Repository name: `case-study-library`.
3. Set it to **Private**. ← the PDFs go in here, so this matters.
4. **Create repository.**
5. On the next screen: **uploading an existing file**.
6. Unzip `case-study-library-repo.zip`, then drag **everything inside it** —
   not the enclosing folder — into the browser. That's `pdfs/`,
   `assets/`, `build.py`, and the rest.
7. **Commit changes.**

You should see `pdfs/`, `assets/`, `build.py`, `extract.py`, `template.html`,
`overrides.json`, `requirements.txt` and `README.md` at the top level of the repo.
If they're nested inside a folder, the build won't find them — delete and re-upload
the contents.

## 2. Connect Cloudflare (5 min)

1. Sign up at **dash.cloudflare.com/sign-up** (free, no card).
2. Sidebar → **Compute (Workers & Pages)** → **Create** → **Pages** tab →
   **Connect to Git**.
3. Authorise GitHub, pick `case-study-library`.
4. Set the build settings exactly:

   | Setting | Value |
   |---|---|
   | Framework preset | None |
   | Build command | `pip install -r requirements.txt && python3 build.py --out dist` |
   | Build output directory | `dist` |

5. **Save and Deploy.** The first build takes 2–3 minutes — it's installing the
   PDF libraries.

When it finishes you get a URL like `case-study-library-a1b.pages.dev`.
Open it and the library loads.

## 3. Check it before sharing

- All the case studies appear (the build log prints the count).
- A **Download** link actually produces a PDF.
- **Open in new tab** shows the PDF, and its text can be selected.

There is no password: anyone with the link can open the library and its PDFs,
so share the URL only with the people who need it.

---

## Then what

Adding a case study, from now on:

> `pdfs/` → **Add file → Upload files** → drag → **Commit changes** → live in a minute.

No terminal, no export step, no admin panel.

## If a build fails

Open the failed deployment in Cloudflare and read the log — it names the file.

| Log says | Fix |
|---|---|
| `No such file or directory: 'requirements.txt'` | The files were uploaded inside a folder. They must be at the repo root. |
| `No extractable text` | That PDF was exported from Figma as a flat image. Re-export with live text. |
| A `pip` / wheel error mentioning the Python version | Add an environment variable `PYTHON_VERSION` = `3.12` and retry. |

A failed build never takes the site down — the previous deployment stays live
until a new one succeeds.

## Optional — your own domain

Pages project → **Custom domains** → add e.g. `cases.euristiq.com`, then add the
CNAME it shows you at your DNS provider (GoDaddy, for euristiq.com).
