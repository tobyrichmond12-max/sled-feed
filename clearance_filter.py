#!/usr/bin/env python3
"""
clearance_filter.py — Reusable legal-clearance gate for the SLED feed fleet.

Given a source descriptor, runs five checks and returns CLEAR or ESCALATE with
reasons. It enforces the project's hard legal rules IN CODE (not comments):

  1. robots.txt allows every data path (for our User-Agent).
  2. No login wall on the target data (detects auth redirects / password forms;
     a benign session cookie is NOT treated as a login wall).
  3. PII scan of a real sample response (emails / phones / SSNs / contact-name
     fields). Discrete contact fields are STRIPPABLE -> still CLEAR; PII embedded
     in free-text -> ESCALATE.
  4. Domain check: official government domain (.gov/.mil/.us/whitelist) vs a
     blocklist of private aggregators (DemandStar, BidNet/Periscope, GovWin,
     Bonfire, GovSpend, ...). Aggregator -> ESCALATE.
  5. Anti-bot / rate-limit fingerprint (Cloudflare/Akamai challenge, 403/503
     interstitials, 429s). If serving the data would require DEFEATING a
     protection, ESCALATE (never circumvent — DMCA 1201 theory).

Usage:
  python3 clearance_filter.py mississippi
Exit code 0 = CLEAR, 2 = ESCALATE.
"""
import gzip
import http.cookiejar
import io
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.robotparser import RobotFileParser

# Honest, identifiable bot UA. If a server treats THIS differently from a browser
# UA, that asymmetry is itself an anti-bot signal we want to catch (check 5).
USER_AGENT = ("SLEDFeedBot/0.1 (+https://github.com/sled-feed; "
              "public government procurement aggregator)")
THROTTLE_S = 1.5  # be gentle with government servers

# --- Private aggregators with enforceable ToS: never scrape (rule). -----------
AGGREGATOR_BLOCKLIST = [
    "demandstar.com", "bidnet.com", "bidnetdirect.com", "periscopeholdings.com",
    "govwin.com", "deltek.com", "bonfirehub.com", "gobonfire.com", "govspend.com",
    "smartprocure.com", "publicpurchase.com", "opengov.com", "procurenow.com",
    "ionwave.net", "bidsync.com", "planetbids.com", "vendorregistry.com",
    "mygovwatch.com", "ebidexchange.com", "questcdn.com",
]
# Official non-.gov domains we've affirmatively verified as government-operated.
OFFICIAL_DOTCOM_WHITELIST = ["myfloridamarketplace.com"]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Phone match REQUIRES separators (-, ., space, or parens) between groups, so a
# real "601-432-8244" matches but bare numeric IDs ("3150006868", doc IDs inside
# URLs) do NOT — those were false positives during clearance of MS.
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def _looks_like_url(v):
    return v.strip().lower().startswith(("http://", "https://"))
PII_FIELD_RE = re.compile(r"(name|email|e-mail|phone|fax|mobile|cell|ssn|contact)",
                          re.I)


# ---------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.checks = []          # (name, ok, detail)
        self.notes = []           # actionable directives (e.g. strip fields)

    def add(self, name, ok, detail):
        self.checks.append((name, ok, detail))

    @property
    def verdict(self):
        return "CLEAR" if all(ok for _, ok, _ in self.checks) else "ESCALATE"

    def report(self, source_name):
        v = self.verdict
        bar = "=" * 64
        print(bar)
        print(f"CLEARANCE: {source_name}")
        print(bar)
        for name, ok, detail in self.checks:
            mark = "PASS" if ok else "ESCALATE"
            print(f"  [{mark:>8}] {name}")
            for ln in detail.splitlines():
                print(f"             {ln}")
        if self.notes:
            print("  ----")
            for n in self.notes:
                print(f"  NOTE: {n}")
        print(bar)
        print(f"VERDICT: {v}")
        print(bar)
        return v


# ---------------------------------------------------------------------------
def _opener(cj):
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def _read(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def _fetch(opener, url, method="GET", body=None, extra_headers=None, timeout=30):
    """Return (status, final_url, headers, text). Never raises on HTTP errors."""
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = opener.open(req, timeout=timeout)
        return resp.status, resp.geturl(), dict(resp.headers), _read(resp)
    except urllib.error.HTTPError as e:
        try:
            txt = _read(e)
        except Exception:
            txt = ""
        return e.code, url, dict(e.headers or {}), txt
    except Exception as e:  # noqa: BLE001
        return None, url, {}, f"__ERROR__ {e}"


# ---------------------------------------------------------------------------
# Check 4: domain
def check_domain(src, res):
    host = src["host"].lower()
    for bad in AGGREGATOR_BLOCKLIST:
        if host == bad or host.endswith("." + bad):
            res.add("domain (gov vs private aggregator)", False,
                    f"{host} is a known private aggregator ({bad}); ToS-protected. "
                    "Scrape the underlying official .gov portal instead.")
            return
    gov = (host.endswith(".gov") or host.endswith(".mil")
           or re.search(r"\.[a-z]{2}\.us$", host)
           # non-US official government domains (e.g. UK .gov.uk, AU .gov.au)
           or re.search(r"\.gov\.[a-z]{2}$", host)
           or host in OFFICIAL_DOTCOM_WHITELIST)
    if gov:
        res.add("domain (gov vs private aggregator)", True,
                f"{host} is an official government domain.")
    else:
        res.add("domain (gov vs private aggregator)", False,
                f"{host} is not a recognized government domain and not whitelisted. "
                "Verify government operation before proceeding.")


# Check 1: robots.txt
def check_robots(src, res):
    robots_url = f"https://{src['host']}/robots.txt"
    rp = RobotFileParser()
    cj = http.cookiejar.CookieJar()
    status, _, _, text = _fetch(_opener(cj), robots_url)
    if status != 200 or text.startswith("__ERROR__"):
        # No robots.txt -> not disallowed. Note it explicitly.
        rp.parse([])
        res.notes.append(f"robots.txt returned HTTP {status}; treating as no "
                         "restrictions (nothing disallowed).")
    else:
        rp.parse(text.splitlines())
    blocked = [p for p in src["robots_paths"] if not rp.can_fetch(USER_AGENT, p)]
    # also test with a generic '*' agent the same way (rp already handles UA)
    if blocked:
        res.add("robots.txt allows data paths", False,
                "Disallowed by robots.txt: " + ", ".join(blocked))
    else:
        res.add("robots.txt allows data paths", True,
                "All data paths allowed:\n" + "\n".join(src["robots_paths"]))


# Check 2 + 5: login wall + anti-bot, from fetching the data page
def check_login_and_antibot(src, res):
    cj = http.cookiejar.CookieJar()
    op = _opener(cj)
    status, final_url, headers, text = _fetch(op, src["data_page_url"])
    low = text.lower()

    # --- anti-bot fingerprint (check 5) ---
    server = (headers.get("Server") or "").lower()
    cf = ("cf-mitigated" in {k.lower() for k in headers}
          or "just a moment" in low or "challenge-platform" in low
          or "cf-browser-verification" in low)
    akamai = "ak_bmsc" in str(headers).lower() or "access denied" in low[:500]
    captcha = "captcha" in low or "recaptcha" in low or "hcaptcha" in low
    challenged = status in (403, 503) and ("cloudflare" in server or cf or captcha)
    if cf or akamai or captcha or challenged:
        res.add("anti-bot / no protection circumvention", False,
                f"Bot-protection challenge detected (status {status}, "
                f"server={server!r}). Serving data would require defeating it.")
    else:
        # light, respectful rate probe: 3 GETs of robots (cheap) spaced out
        codes = []
        for _ in range(3):
            time.sleep(THROTTLE_S)
            s2, _, _, _ = _fetch(op, f"https://{src['host']}/robots.txt")
            codes.append(s2)
        rate_limited = any(c == 429 for c in codes)
        if rate_limited:
            res.add("anti-bot / no protection circumvention", False,
                    f"Server returned 429 under gentle access ({codes}); "
                    "aggressive rate-limiting — do not circumvent.")
        else:
            res.add("anti-bot / no protection circumvention", True,
                    f"No Cloudflare/Akamai/captcha challenge; data page HTTP {status}; "
                    f"gentle rate probe {codes} (no 429).")

    # --- login wall (check 2) ---
    auth_redirect = bool(re.search(r"/(login|signin|sign-in|sso|auth|account|"
                                   r"oauth|adfs)\b", urllib.parse.urlparse(final_url).path, re.I))
    pw_form = ("type=\"password\"" in low or "type='password'" in low)
    needs_auth = status in (401,) or auth_redirect or pw_form
    set_cookies = [c.name for c in cj]
    if needs_auth:
        res.add("no login wall on target data", False,
                f"Auth required: status={status}, final_url={final_url}, "
                f"password_form={pw_form}.")
    else:
        # A session cookie is fine — note it so it's not mistaken for a login.
        cookie_note = (f"benign session cookie(s) set without login: {set_cookies}"
                       if set_cookies else "no cookies required")
        res.add("no login wall on target data", True,
                f"Data page reachable without auth (HTTP {status}); {cookie_note}.")


# Check 3: PII scan of a real sample
def _walk_strings(obj, path=""):
    """Yield (fieldpath, string_value) for every string in a nested JSON object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_strings(it, path)
    elif isinstance(obj, str):
        yield path, obj


def check_pii(src, res):
    import json
    spec = src["sample"]
    cj = http.cookiejar.CookieJar()
    op = _opener(cj)
    if spec.get("session_url"):
        _fetch(op, spec["session_url"])          # establish session (no login)
        time.sleep(THROTTLE_S)
    status, _, _, text = _fetch(op, spec["url"], method=spec.get("method", "GET"),
                                body=spec.get("body"),
                                extra_headers=spec.get("headers"))
    if status != 200 or text.startswith("__ERROR__"):
        res.add("PII scan of sample response", False,
                f"Could not fetch a sample to scan (status {status}).")
        return
    try:
        data = json.loads(text)
    except Exception:
        # not JSON — scan raw text
        data = None

    # Fields dropped wholesale (discrete contact fields + auxiliary free-text we
    # do NOT serve, e.g. AdditionalInfo). PII here is fine — it gets stripped.
    strip_fields = set(f.lower() for f in src.get("pii_strip_fields", []))
    # Free-text fields we DO serve (title/category): these MUST be PII-clean.
    keep_text = set(f.lower() for f in src.get("keep_text_fields", []))
    url_fields = set(f.lower() for f in src.get("url_fields", []))

    pii_in_strip = {}           # field -> kinds (OK; will be stripped)
    pii_in_kept = {}            # field -> examples (ESCALATE)
    pii_elsewhere = {}          # unexpected field -> examples (ESCALATE)

    def classify(fieldpath, value):
        leaf = fieldpath.split(".")[-1].lower()
        # Document links are not PII — skip URL values / declared url fields.
        if leaf in url_fields or _looks_like_url(value):
            return
        kinds = []
        if EMAIL_RE.search(value):
            kinds.append("email")
        if SSN_RE.search(value):
            kinds.append("ssn")
        if PHONE_RE.search(value):
            kinds.append("phone")
        field_is_contact = bool(PII_FIELD_RE.search(leaf))
        if not kinds and not field_is_contact:
            return
        if leaf in strip_fields or (field_is_contact and leaf not in keep_text):
            pii_in_strip.setdefault(leaf, set()).update(kinds or ["contact-field"])
        elif leaf in keep_text:
            if kinds:
                pii_in_kept.setdefault(leaf, []).append(value[:80])
        else:
            if kinds:
                pii_elsewhere.setdefault(leaf, []).append(value[:80])

    records = []
    if data is not None:
        rp = spec.get("record_path")
        records = (data.get(rp) if rp and isinstance(data, dict) else data) or []
        for rec in records[:25]:
            for fp, val in _walk_strings(rec):
                classify(fp, val)
    else:
        for kind, rx in (("email", EMAIL_RE), ("ssn", SSN_RE), ("phone", PHONE_RE)):
            if rx.search(text):
                pii_elsewhere.setdefault("(raw response)", []).append(kind)

    # Verdict: PII in a field we SERVE (or an unexpected field) -> ESCALATE.
    # PII confined to strippable/auxiliary fields -> CLEAR (we drop those).
    if pii_in_kept or pii_elsewhere:
        detail = []
        if pii_in_kept:
            detail.append("PII in served free-text fields (cannot separate): "
                          + "; ".join(f"{k}={v[0]!r}" for k, v in pii_in_kept.items()))
        if pii_elsewhere:
            detail.append("PII in unexpected fields: "
                          + "; ".join(f"{k}={v[0]!r}" for k, v in pii_elsewhere.items()))
        res.add("PII scan of sample response", False, "\n".join(detail))
    else:
        found = ", ".join(sorted(pii_in_strip)) or "none detected in sample"
        declared = src.get("pii_strip_fields", [])
        res.add("PII scan of sample response", True,
                f"Scanned {min(len(records),25)} records. PII confined to "
                f"droppable fields ({found}); served fields (title/category) clean.")
        res.notes.append("STRIP these fields before storing/serving: "
                         + ", ".join(declared))


# ---------------------------------------------------------------------------
def run(src):
    res = Result()
    check_domain(src, res)
    time.sleep(THROTTLE_S)
    check_robots(src, res)
    time.sleep(THROTTLE_S)
    check_login_and_antibot(src, res)
    time.sleep(THROTTLE_S)
    check_pii(src, res)
    return res


def main():
    from sources import SOURCES
    if len(sys.argv) < 2 or sys.argv[1] not in SOURCES:
        sys.exit(f"usage: clearance_filter.py <{'|'.join(SOURCES)}>")
    src = SOURCES[sys.argv[1]]
    res = run(src)
    verdict = res.report(src["name"])
    sys.exit(0 if verdict == "CLEAR" else 2)


if __name__ == "__main__":
    main()
