// Password gate for the whole site, PDFs included.
//
// Cloudflare Pages runs this before every request. The password lives in the
// Pages environment variable SITE_PASSWORD (Settings -> Environment variables),
// never in this repository. Any username is accepted; only the password counts.
// If the variable is missing the site refuses to serve anything (503) rather
// than serving the library unprotected.

const REALM = "Euristiq case study library";

function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    diff |= (x[i] || 0) ^ (y[i] || 0);
  }
  return diff === 0;
}

function passwordFrom(request) {
  const header = request.headers.get("Authorization") || "";
  const [scheme, encoded] = header.split(" ");
  if (!encoded || scheme.toLowerCase() !== "basic") return null;
  try {
    const decoded = atob(encoded);
    const i = decoded.indexOf(":");
    return i === -1 ? null : decoded.slice(i + 1);
  } catch {
    return null;
  }
}

export async function onRequest({ request, env, next }) {
  const expected = env.SITE_PASSWORD;
  if (!expected) {
    return new Response(
      "The library is locked: the SITE_PASSWORD environment variable is not set " +
      "in Cloudflare Pages. Set it, then redeploy.",
      { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } }
    );
  }

  const given = passwordFrom(request);
  if (given === null || !timingSafeEqual(given, expected)) {
    return new Response("Password required.", {
      status: 401,
      headers: {
        "WWW-Authenticate": `Basic realm="${REALM}", charset="UTF-8"`,
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  }

  const response = await next();
  const out = new Response(response.body, response);
  out.headers.set("Cache-Control", "private, no-store");
  out.headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  return out;
}
