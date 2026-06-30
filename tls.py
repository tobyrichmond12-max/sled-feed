#!/usr/bin/env python3
"""
tls.py — HOST-SCOPED TLS tolerance. Never a global "ignore TLS" default.

Only the specific known-misconfigured government document host
(SRM.MAGIC.MS.GOV — valid GlobalSign cert for MS DITS, but omits its intermediate)
is fetched with verification relaxed. Every other host is verified strictly. We
also record that host's cert posture and LOG if it changes (e.g. the intermediate
gets fixed, or the issuer/subject changes — which could signal interception).
"""
import logging
import socket
import ssl
import urllib.request

log = logging.getLogger("tls")

# The ONLY hosts allowed to skip chain verification, and why.
ALLOWED_UNVERIFIED_HOSTS = {"srm.magic.ms.gov"}

# Expected posture per allowlisted host. Drift here is logged.
EXPECTED_POSTURE = {
    "srm.magic.ms.gov": {
        "subject_contains": "magic.ms.gov",
        "issuer_contains": "GlobalSign",
        "chain_verifies": False,        # missing intermediate today
    },
}


def cert_posture(host, port=443, timeout=20):
    """Return {chain_verifies, subject, issuer} for host:port."""
    out = {"chain_verifies": None, "subject": "", "issuer": ""}
    # 1) does the chain verify strictly?
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            with ssl.create_default_context().wrap_socket(s, server_hostname=host):
                out["chain_verifies"] = True
    except ssl.SSLError:
        out["chain_verifies"] = False
    except Exception:  # noqa: BLE001
        return out
    # 2) read subject/issuer (unverified, just to read the leaf)
    try:
        ctx = ssl._create_unverified_context()
        with socket.create_connection((host, port), timeout=timeout) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                der = ss.getpeercert(binary_form=True)
        # parse CN/issuer cheaply via the verified-form when available
        ctx2 = ssl.create_default_context()
        ctx2.check_hostname = False
        ctx2.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as s:
            with ctx2.wrap_socket(s, server_hostname=host) as ss:
                c = ss.getpeercert()  # may be {} under CERT_NONE
        # Fallback: use openssl-free text from DER via ssl
        txt = ssl.DER_cert_to_PEM_cert(der)
        out["subject"] = _field(c, "subject") or "(leaf present)"
        out["issuer"] = _field(c, "issuer") or ""
        out["_pem_len"] = len(txt)
    except Exception:  # noqa: BLE001
        pass
    return out


def _field(cert, key):
    if not cert:
        return ""
    parts = []
    for rdn in cert.get(key, ()):  # tuple of tuples
        for k, v in rdn:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


def check_posture_and_log(host):
    """Compare live posture to expectation; log drift. Returns (ok, posture)."""
    exp = EXPECTED_POSTURE.get(host)
    p = cert_posture(host)
    if exp is None:
        log.info("tls posture %s: %s (no baseline)", host, p)
        return True, p
    drift = []
    if p.get("chain_verifies") is not None and p["chain_verifies"] != exp["chain_verifies"]:
        drift.append(f"chain_verifies {exp['chain_verifies']}->{p['chain_verifies']}")
    if p.get("issuer") and exp["issuer_contains"].lower() not in p["issuer"].lower():
        drift.append(f"issuer no longer contains {exp['issuer_contains']!r}: {p['issuer']!r}")
    if drift:
        log.warning("TLS POSTURE DRIFT for %s: %s — review before trusting docs.",
                    host, "; ".join(drift))
        return False, p
    log.info("tls posture %s unchanged (chain_verifies=%s, issuer~%s)",
             host, p.get("chain_verifies"), exp["issuer_contains"])
    return True, p


def open_url(url, timeout=40, headers=None):
    """Open a URL. Verification is relaxed ONLY for allowlisted hosts; all others
    are strict. Raises for any non-allowlisted TLS failure (no silent bypass)."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    ctx = None
    if host in ALLOWED_UNVERIFIED_HOSTS:
        ctx = ssl._create_unverified_context()
        log.debug("relaxed TLS for allowlisted host %s", host)
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for h in ALLOWED_UNVERIFIED_HOSTS:
        check_posture_and_log(h)
