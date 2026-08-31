const TITLE_B64 = "Ym96eWEgdnBu"; // "bozya vpn"
const REPO = "zaigraevstepan7-afk/bozya_vpn";
const SOURCES = {
  happ: [
    `https://raw.githubusercontent.com/${REPO}/main/output/happ-bs.txt`,
    `https://raw.githubusercontent.com/${REPO}/cursor/zipka-bs-whitelist-d429/output/happ-bs.txt`,
  ],
  pattng: [
    `https://raw.githubusercontent.com/${REPO}/main/output/pattng-bs.json`,
    `https://raw.githubusercontent.com/${REPO}/cursor/zipka-bs-whitelist-d429/output/pattng-bs.json`,
  ],
};

async function fetchFirst(urls) {
  let last = null;
  for (const url of urls) {
    const res = await fetch(url, { cf: { cacheTtl: 60, cacheEverything: true } });
    if (res.ok) {
      return await res.text();
    }
    last = res;
  }
  throw new Error("upstream " + (last ? last.status : "unreachable"));
}

function uriBody(text) {
  const uris = text
    .split(/\r?\n/)
    .map((ln) => ln.trim())
    .filter((ln) => ln && !ln.startsWith("#"));
  return uris.join("\n") + "\n";
}

function happHeaders(filename, contentType) {
  return {
    "content-type": contentType,
    "profile-title": "base64:" + TITLE_B64,
    "profile-update-interval": "1",
    "content-disposition": 'attachment; filename="' + filename + '"',
    "access-control-expose-headers":
      "profile-title, profile-update-interval, content-disposition, subscription-userinfo",
    "access-control-allow-origin": "*",
    "cache-control": "no-store",
  };
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    try {
      if (path === "/pattng" || path === "/pattng-bs.json") {
        const json = await fetchFirst(SOURCES.pattng);
        return new Response(json, {
          headers: happHeaders("bozya vpn.json", "application/json; charset=utf-8"),
        });
      }
      const raw = await fetchFirst(SOURCES.happ);
      const plaintext = uriBody(raw);
      // Same as vpnmx: base64 body + profile-title header.
      const body = btoa(unescape(encodeURIComponent(plaintext)));
      return new Response(body + "\n", {
        headers: happHeaders("bozya vpn.txt", "text/plain; charset=utf-8"),
      });
    } catch (err) {
      return new Response(String(err), { status: 502 });
    }
  },
};
