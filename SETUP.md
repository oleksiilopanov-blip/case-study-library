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
   not the enclosing folder — into the browser. That's `pdfs/`, `functions/`,
   `build.py`, and the rest.
7. **Commit changes.**

You should see `pdfs/`, `functions/`, `build.py`, `extract.py`, `template.html`,
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
Open it and you'll see a password prompt that nothing will satisfy yet — that's
correct, and step 3 fixes it.

## 3. Set the password (3 min)

1. In the Pages project → **Settings** → **Environment variables**.
2. **Add variable**, for **Production**:

   | | |
   |---|---|
   | Variable name | `SITE_PASSWORD` |
   | Value | whatever the team will type |
   | Type | **Secret** |

3. Add the same variable for **Preview** too.
4. Go to **Deployments** → **⋯** on the latest one → **Retry deployment**.
   Environment variables only apply to builds that run after they're set.

Now open the URL: any username, that password, and the library loads.

## 4. Check it before sharing

- All 5 case studies appear.
- A **Download** link actually produces a PDF.
- Open a PDF URL directly in a private window — e.g.
  `https://<your-url>/pdfs/anything.pdf`. **It must ask for the password.**
  If a PDF loads without one, stop and check that `functions/` ended up inside
  `dist/` (the build log prints `copied functions/ -> dist/functions`).

That last check is the one that matters. The page being protected while the PDFs
are wide open is exactly the failure mode worth ruling out.

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
| `503 This library is not configured yet` on the site | `SITE_PASSWORD` isn't set, or was set after the last build. Add it and retry the deployment. |

A failed build never takes the site down — the previous deployment stays live
until a new one succeeds.

## Optional — your own domain

Pages project → **Custom domains** → add e.g. `cases.euristiq.com`, then add the
CNAME it shows you at your DNS provider (GoDaddy, for euristiq.com). The password
protection carries over unchanged.
