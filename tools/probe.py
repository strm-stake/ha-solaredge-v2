#!/usr/bin/env python3
"""Probe the SolarEdge V2 API outside Home Assistant (standard library only).

Use it to confirm authorize parameters, token exchange, endpoint paths,
query parameters and response shapes before relying on the integration.

  python3 probe.py authorize --client-id ID --redirect-uri URI [--extra "scope=SITE_DATA DEVICE_DATA"]
  python3 probe.py exchange  --client-id ID --client-secret SECRET --redirect-uri URI --url "<pasted redirect url>"
  python3 probe.py get /sites/SITE_ID/overview [--param startTime=...]

State (PKCE verifier, tokens) is kept in ./.probe_state.json (contains secrets!).
Do NOT run `get` in parallel with Home Assistant using the same grant: the
refresh token rotates on every refresh and the other consumer would be locked out.
"""

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://monitoringapi.solaredge.com/v2"
AUTHORIZE = "https://connect.solaredge.com/authorize"
STATE = ".probe_state.json"


def load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(state):
    with open(STATE, "w") as f:
        json.dump(state, f, indent=2)


def http(method, url, body=None, headers=None, basic=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data:
        req.add_header("Content-Type", "application/json")
    if basic:
        req.add_header("Authorization", "Basic " + base64.b64encode(basic.encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def cmd_authorize(a):
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = [("client_id", a.client_id), ("response_type", "code"), ("redirect_uri", a.redirect_uri),
              ("external_id", secrets.token_urlsafe(8)), ("code_challenge", challenge),
              ("code_challenge_method", "S256")]
    params += urllib.parse.parse_qsl(a.extra)
    save({**load(), "verifier": verifier})
    print(AUTHORIZE + "?" + urllib.parse.urlencode(params))


def token_call(payload, cid, secret):
    status, text = http("POST", API + "/oauth2/token", {**payload, "client_id": cid, "client_secret": secret})
    if status >= 400:
        print(f"[body-credentials] {status}: {text[:300]}", file=sys.stderr)
        status, text = http("POST", API + "/oauth2/token", payload, basic=f"{cid}:{secret}")
    if status != 200:
        sys.exit(f"token endpoint {status}: {text[:500]}")
    return json.loads(text)


def keep(state, tok, cid, secret):
    state.update(client_id=cid, client_secret=secret, access_token=tok["access_token"],
                 refresh_token=tok.get("refresh_token", state.get("refresh_token")),
                 expires_at=time.time() + float(tok.get("expires_in") or 3600))
    save(state)


def cmd_exchange(a):
    state = load()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(a.url).query)
    code = (q.get("code") or [""])[0]
    if not code:
        sys.exit("no code= in that URL")
    payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": a.redirect_uri}
    if state.get("verifier"):
        payload["code_verifier"] = state["verifier"]
    tok = token_call(payload, a.client_id, a.client_secret)
    keep(state, tok, a.client_id, a.client_secret)
    print("site_id from redirect:", (q.get("site_id") or ["?"])[0])
    print("token fields:", sorted(tok))


def cmd_get(a):
    state = load()
    if time.time() > state.get("expires_at", 0) - 60:
        tok = token_call({"grant_type": "refresh_token", "refresh_token": state["refresh_token"]},
                         state["client_id"], state["client_secret"])
        keep(state, tok, state["client_id"], state["client_secret"])
    url = API + a.path
    if a.param:
        url += "?" + urllib.parse.urlencode([p.split("=", 1) for p in a.param])
    status, text = http("GET", url, headers={"Authorization": "Bearer " + state["access_token"]})
    print(status)
    try:
        print(json.dumps(json.loads(text), indent=2)[:6000])
    except ValueError:
        print(text[:2000])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("authorize")
    s.add_argument("--client-id", required=True)
    s.add_argument("--redirect-uri", required=True)
    s.add_argument("--extra", default="scope=SITE_DATA DEVICE_DATA")
    s.set_defaults(fn=cmd_authorize)
    s = sub.add_parser("exchange")
    s.add_argument("--client-id", required=True)
    s.add_argument("--client-secret", required=True)
    s.add_argument("--redirect-uri", required=True)
    s.add_argument("--url", required=True)
    s.set_defaults(fn=cmd_exchange)
    s = sub.add_parser("get")
    s.add_argument("path")
    s.add_argument("--param", action="append", default=[])
    s.set_defaults(fn=cmd_get)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
