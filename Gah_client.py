"""
Shared helpers for the Grande Auto Hut bulk scripts
(Bulk_import_products.py, Bulk_upload_images.py, Bulk_import_fitment.py).

Credential safety
-----------------
* Nothing secret is ever stored in the scripts or in the repo.
* Credentials come from, in this order:
    1. environment variables  GAH_EMAIL / GAH_PASSWORD
    2. a git-ignored file named  .env.bulk  (see .env.bulk.example)
    3. an interactive prompt (the password is typed hidden)
  They are deliberately NOT accepted as command-line arguments, because those
  end up in your shell history and in the process list.
* The password is only ever sent to <API>/auth/login/. Passwords, tokens and
  request headers are never printed or written to any log/CSV.
* Plain http:// is refused for anything except localhost, so your login can't
  travel unencrypted.
* Use a dedicated STAFF account for importing (not your admin account). Staff
  can add products/images/fitment but cannot manage users. Change its password
  or deactivate it when you are done.
"""
import getpass
import json
import os
import re
import stat
import sys
import time
from urllib.parse import urlparse

import requests

DEFAULT_API = "https://grande-auto-hut-backend.onrender.com"
ENV_FILE = ".env.bulk"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TOKEN_MAX_AGE = 12 * 60  # access tokens last 15 min on the server; renew early


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def load_env_file(path=ENV_FILE):
    """Load KEY=VALUE lines from a git-ignored file into os.environ.
    Real environment variables always win over the file."""
    if not os.path.isfile(path):
        return
    try:
        mode = os.stat(path).st_mode
        if os.name == "posix" and mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(f"WARNING: {path} is readable by other users. Run: chmod 600 {path}")
    except OSError:
        pass
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


def normalize_api(url):
    """Accepts 'host', 'https://host' or 'https://host/api' and always returns
    'https://host/api'. (The old scripts defaulted to a URL without /api, so
    every call 404'd against production.)"""
    url = (url or DEFAULT_API).strip().rstrip("/")
    if not re.match(r"^https?://", url):
        is_local = re.match(r"^(localhost|127\.0\.0\.1|\[::1\])", url) is not None
        url = ("http://" if is_local else "https://") + url
    if not url.endswith("/api"):
        url += "/api"
    parsed = urlparse(url)
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        sys.exit(
            "Refusing to send credentials over plain http://. "
            "Use https:// (only localhost may use http)."
        )
    return url


def short(response, limit=300):
    """Compact, safe description of an error response (never includes headers)."""
    try:
        text = json.dumps(response.json(), ensure_ascii=False)
    except ValueError:
        text = (response.text or "").strip().replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
class Client:
    def __init__(self):
        load_env_file()
        self.api = normalize_api(os.environ.get("GAH_API_URL"))
        self._email = (os.environ.get("GAH_EMAIL") or "").strip()
        self._password = os.environ.get("GAH_PASSWORD") or ""
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "gah-bulk-tools/2"
        self._logged_in_at = 0.0

    # ---- auth ----------------------------------------------------------
    def _ensure_credentials(self):
        if not self._email:
            self._email = input("Staff email: ").strip()
        if not self._password:
            self._password = getpass.getpass("Password (hidden): ")

    def login(self):
        self._ensure_credentials()
        self.session.headers.pop("Authorization", None)
        for attempt in range(1, 7):
            try:
                r = self.session.post(
                    f"{self.api}/auth/login/",
                    json={"email": self._email, "password": self._password},
                    timeout=(15, 120),
                )
            except (requests.ConnectionError, requests.Timeout):
                print("  server not responding yet (it may be waking up), retrying...")
                time.sleep(min(5 * attempt, 30))
                continue
            if r.status_code == 429:
                wait = _retry_after(r, default=15)
                print(f"  login rate-limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if r.status_code in (502, 503, 504):
                time.sleep(min(5 * attempt, 30))
                continue
            if r.status_code in (400, 401):
                self._password = ""  # forget the bad password
                sys.exit("Login failed: wrong email or password.")
            r.raise_for_status()
            self.session.headers["Authorization"] = f"Bearer {r.json()['access']}"
            self._logged_in_at = time.time()
            return
        sys.exit("Could not log in (server unavailable or rate-limited). Try again in a minute.")

    def close(self):
        """Forget secrets and drop the HTTP session."""
        self._password = ""
        self.session.headers.pop("Authorization", None)
        self.session.close()

    # ---- requests ------------------------------------------------------
    def url(self, path):
        return f"{self.api}/{path.strip('/')}/"

    def request(self, method, path, *, retries=6, timeout=(15, 120), **kwargs):
        """HTTP call with: automatic re-login when the 15-minute token expires,
        waiting out 429 throttling, and retrying cold-start / network errors.
        Pass file contents as bytes (not open file objects) so they can be re-sent."""
        if time.time() - self._logged_in_at > TOKEN_MAX_AGE:
            self.login()
        url = self.url(path)
        relogged = False
        r = None
        for attempt in range(1, retries + 2):
            try:
                r = self.session.request(method, url, timeout=timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(min(3 * attempt, 30))
                continue
            if r.status_code == 401 and not relogged:
                relogged = True
                self.login()
                continue
            if r.status_code == 429:
                time.sleep(_retry_after(r, default=5 * attempt))
                continue
            if r.status_code in (502, 503, 504):
                time.sleep(min(3 * attempt, 30))
                continue
            if r.status_code == 403:
                sys.exit(
                    "Permission denied (403). This account must have the Staff or Admin role."
                )
            return r
        if r is not None:
            return r
        sys.exit(f"Could not reach {self.api} after several attempts.")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def fetch_all(self, path, params=None):
        """Every row of a list endpoint, paginated or not. Uses page numbers
        instead of the 'next' link (behind a proxy 'next' can be an http:// URL)."""
        rows, page = [], 1
        while True:
            q = dict(params or {})
            if page > 1:
                q["page"] = page
            r = self.get(path, params=q)
            if r.status_code == 404 and page > 1:
                break
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            rows += data.get("results", [])
            if not data.get("next"):
                break
            page += 1
        return rows

    def fetch_products(self):
        """All products INCLUDING inactive ones (the default list hides them,
        which made re-runs try to re-create hidden products)."""
        return self.fetch_all("products", {"include_inactive": "true"})


def _retry_after(response, default=5):
    try:
        return max(1, min(int(float(response.headers.get("Retry-After", default))) + 1, 65))
    except (TypeError, ValueError):
        return default