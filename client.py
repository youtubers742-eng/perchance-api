# -*- coding: utf-8 -*-
"""Perchance image-generation client + automatic userKey management.

Reverse-engineered from the Perchance generator page
(https://perchance.org/ai-text-to-image-generator). There is NO official
public API — this replays the browser's own calls to the internal backend
``https://image-generation.perchance.org/api``:

  POST /api/generate   (query: userKey, requestId, adAccessCode, __cacheBust)
                       (JSON body: prompt, negativePrompt, seed, resolution,
                        guidanceScale, channel, subChannel, userKey,
                        adAccessCode, requestId)
  GET  /api/downloadTemporaryImage?imageId=...   (raw image bytes)
       — or use the ``imageDownloadUrl`` field from the generate response.

Response ``status`` values: ``success`` / ``queued`` (poll, sleep 4s) /
``invalid_key`` / ``invalid_data``.

THE KEY PROBLEM
---------------
The ``userKey`` (64 hex chars) is issued by Perchance only to a real browser
that has passed Cloudflare Turnstile. A key copied from a *different*
browser/machine does NOT work — the backend returns ``invalid_key``. So the
key MUST be minted on the same machine that calls the API. ``KeyManager``
does exactly that: on first use (and whenever the backend says
``invalid_key``) it launches headless Chromium via Playwright, opens the
generator page, lets Turnstile pass, and captures the key from the
``/api/verifyUser`` call. The key is cached in memory and in ``userkey.txt``
so restarts reuse it while it is still valid (hours-days).

If the browser flow fails (no Chromium installed, Turnstile blocks it, ...),
the manager falls back to the ``PERCHANCE_USER_KEY`` env var / ``userkey.txt``
— i.e. a key you paste in by hand. If neither works, generation raises a
clear error instead of silently failing.

RAM note: full Chromium (required — Turnstile blocks Playwright's headless
shell) needs roughly 250-400 MB while it runs. The browser is only launched
on demand for a few seconds, then closed, so the steady-state server stays
small. On a 512 MB host (e.g. Render free) the refresh may OOM — in that
case set PERCHANCE_USER_KEY by hand instead.
"""

import json
import logging
import os
import random
import re
import threading
import time

import httpx

logger = logging.getLogger(__name__)

BASE = "https://image-generation.perchance.org/api"
GENERATOR_PAGE = "https://perchance.org/ai-text-to-image-generator"

# A current desktop Chrome UA — the backend expects a browser-like client.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Lean Chromium flags: no sandbox (containers), no /dev/shm (small hosts),
# no GPU, no background services. Full Chromium binary, NOT headless shell
# (Turnstile blocks the shell build).
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-translate",
    "--mute-audio",
    "--no-first-run",
    "--disable-features=site-per-process",
    # 512 MB hosts (Render free): one process + no zygote keeps Chromium's
    # RSS down so the mint survives instead of OOM-killed mid-Turnstile.
    "--single-process",
    "--no-zygote",
    "--disable-software-rasterizer",
]

_KEY_RE = re.compile(r'"userKey"\s*:\s*"([0-9a-fA-F]{64})"')
_KEY_IN_URL_RE = re.compile(r"userKey=([0-9a-fA-F]{64})")


class InvalidKeyError(RuntimeError):
    """The backend rejected the userKey (expired / wrong machine)."""


class PerchanceError(RuntimeError):
    """Any other Perchance-side failure (network, queue timeout, ...)."""


class KeyManager:
    """Holds the current userKey; mints a fresh one via a real browser."""

    def __init__(self, key_file="userkey.txt"):
        self._lock = threading.Lock()
        self._key_file = key_file
        self._key = None
        self._source = "none"  # env | file | browser | none
        # Last mint attempt, for diagnosis via /health (previously the
        # browser failure was swallowed silently and nothing logged why).
        self._last_error = None
        self._last_attempt = None
        # 1) explicit env var wins
        env_key = os.environ.get("PERCHANCE_USER_KEY", "").strip()
        if env_key:
            self._key = env_key
            self._source = "env"
            return
        # 2) cached key from a previous run
        if os.path.isfile(key_file):
            try:
                cached = open(key_file).read().strip()
                if cached:
                    self._key = cached
                    self._source = "file"
            except OSError:
                pass

    @property
    def key(self):
        return self._key

    @property
    def source(self):
        return self._source

    @property
    def last_error(self):
        """Human-readable reason the last browser mint failed (None if the
        last attempt succeeded or none ran yet)."""
        return self._last_error

    @property
    def last_attempt(self):
        """Epoch seconds of the last browser mint attempt (None if none)."""
        return self._last_attempt

    def set_key(self, key):
        """Store a key in memory and persist it for the next restart."""
        key = (key or "").strip()
        if not key:
            return
        self._key = key
        self._source = "manual"
        try:
            with open(self._key_file, "w") as f:
                f.write(key)
        except OSError:
            pass

    def get_key(self):
        """Return a usable key, minting one in a browser if we have none."""
        with self._lock:
            if self._key:
                return self._key
            return self.refresh_locked()

    def refresh(self, force=False):
        """Force a fresh browser-minted key (used after invalid_key)."""
        with self._lock:
            if not force and self._key:
                return self._key
            # FIX: this used to call self._refresh_locked(), which does not
            # exist — every invalid_key retry died with AttributeError
            # instead of minting a fresh key.
            return self.refresh_locked()

    def refresh_locked(self):
        """Mint a key via headless Chromium. Caller must hold the lock."""
        # Never mint from an env/file key we already invalidated: clear it.
        self._last_attempt = time.time()
        try:
            key = self._mint_via_browser()
        except Exception as e:  # noqa: BLE001 - record, don't crash the call
            self._last_error = f"mint crashed: {type(e).__name__}: {e}"
            logger.warning("Perchance key mint crashed: %s", self._last_error)
            key = None
        if key:
            self._last_error = None
            self._key = key
            self._source = "browser"
            logger.info("Perchance key minted via browser (source=browser)")
            try:
                with open(self._key_file, "w") as f:
                    f.write(key)
            except OSError:
                pass
            return key
        if not self._last_error:
            self._last_error = ("browser mint returned no key "
                                "(Turnstile blocked or page never yielded "
                                "verifyUser)")
        logger.warning("Perchance key mint failed: %s", self._last_error)
        # Browser path failed — fall back to env var if one appeared.
        env_key = os.environ.get("PERCHANCE_USER_KEY", "").strip()
        if env_key:
            self._key = env_key
            self._source = "env"
            return env_key
        return None

    def invalidate(self):
        """Drop the cached key so the next call mints a fresh one."""
        with self._lock:
            self._key = None
            self._source = "none"

    # -- browser minting -------------------------------------------------
    def _mint_via_browser(self, timeout=120):
        """Open the generator page in headless Chromium and capture the
        userKey from the /api/verifyUser call. Returns the key or None."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._last_error = "Playwright not installed on this host"
            logger.warning("Perchance key mint: %s", self._last_error)
            return None  # Playwright not installed — env key is the only way.

        found = []

        def _capture(text):
            if not text:
                return
            m = _KEY_RE.search(text)
            if m:
                found.append(m.group(1))
            else:
                m = _KEY_IN_URL_RE.search(text)
                if m:
                    found.append(m.group(1))

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
                try:
                    ctx = browser.new_context(
                        user_agent=UA,
                        viewport={"width": 800, "height": 600},
                    )
                    page = ctx.new_page()
                    # Capture the key from any verifyUser request/response.
                    page.on("request", lambda req: _capture(req.url)
                            if "verifyUser" in req.url else None)
                    page.on("response", lambda resp: _capture(_safe_text(resp))
                            if "verifyUser" in resp.url else None)
                    page.goto(GENERATOR_PAGE, wait_until="domcontentloaded",
                              timeout=timeout * 1000)
                    # Let Cloudflare Turnstile run and the page settle.
                    try:
                        page.wait_for_load_state("networkidle", timeout=30000)
                    except Exception:
                        pass
                    page.wait_for_timeout(6000)
                    if not found:
                        # Ask for a key directly inside the page context —
                        # Turnstile cookies are already set by now.
                        try:
                            data = page.evaluate(
                                """async () => {
                                    const r = await fetch(
                                      'https://image-generation.perchance.org/api/verifyUser?thread=0',
                                      {credentials: 'include'});
                                    return await r.text();
                                }""")
                            _capture(data)
                        except Exception:
                            pass
                    ctx.close()
                finally:
                    browser.close()
        except Exception as e:  # noqa: BLE001 - log the real reason; the
            # old code swallowed this silently, so Render logs showed nothing
            # and /health only said key_cached:false.
            self._last_error = (f"browser mint failed: "
                                f"{type(e).__name__}: {e}")
            logger.warning("Perchance key mint failed: %s",
                           self._last_error, exc_info=True)
            return None
        if not found:
            logger.warning("Perchance key mint: browser ran but no userKey "
                           "was captured from verifyUser (Turnstile may "
                           "have blocked this datacentre IP)")
        return found[-1] if found else None


def _safe_text(resp):
    try:
        return resp.text()
    except Exception:
        return ""


class PerchanceClient:
    """Thin client for the Perchance image backend.

    Generates are serialised with a lock (the backend queues per IP anyway
    and parallel calls just burn the 2-day per-IP request budget faster).
    """

    def __init__(self, key_manager=None, poll_timeout=180, http_timeout=120):
        self.keys = key_manager or KeyManager()
        self.poll_timeout = poll_timeout
        self.http_timeout = http_timeout
        self._gen_lock = threading.Lock()
        self._http = self._build_http_client(http_timeout)

    @staticmethod
    def _build_http_client(http_timeout):
        """Build the HTTP client. Some hosts set malformed proxy env vars
        (e.g. bracketed IPv6 in NO_PROXY, which httpx cannot parse) — if
        the default client blows up on them, fall back to ignoring the
        environment entirely. The Perchance backend is reached directly."""
        kwargs = dict(
            headers={
                "User-Agent": UA,
                "Referer": "https://image-generation.perchance.org/embed",
                "Origin": "https://image-generation.perchance.org",
            },
            timeout=http_timeout,
            follow_redirects=True,
        )
        try:
            return httpx.Client(**kwargs)
        except httpx.InvalidURL:
            return httpx.Client(trust_env=False, **kwargs)

    # -- public ----------------------------------------------------------
    def generate(self, prompt, negative_prompt="", seed=-1,
                 resolution="768x768", guidance_scale=7):
        """Generate one image. Returns dict with id/bytes/seed/width/height.

        On ``invalid_key`` the key is refreshed once in-browser and the
        request is retried automatically.
        """
        with self._gen_lock:
            key = self.keys.get_key()
            if not key:
                raise PerchanceError(
                    "No Perchance userKey available: automatic browser "
                    "refresh failed and no PERCHANCE_USER_KEY is set. "
                    "Set PERCHANCE_USER_KEY to a key copied from a desktop "
                    "browser session on THIS machine, or install Chromium "
                    "so the server can mint one itself.")
            try:
                return self._generate_once(prompt, negative_prompt, seed,
                                           resolution, guidance_scale, key)
            except InvalidKeyError:
                # Key died mid-flight — mint a fresh one and retry once.
                self.keys.invalidate()
                new_key = self.keys.refresh(force=True)
                if not new_key or new_key == key:
                    raise InvalidKeyError(
                        "Perchance rejected the userKey and a fresh key "
                        "could not be minted. Set PERCHANCE_USER_KEY "
                        "manually (copy it from a desktop browser on this "
                        "machine) and retry.")
                return self._generate_once(prompt, negative_prompt, seed,
                                           resolution, guidance_scale, new_key)

    # -- internals -------------------------------------------------------
    def _generate_once(self, prompt, negative_prompt, seed, resolution,
                       guidance_scale, key):
        rid = str(random.random())
        params = {
            "userKey": key,
            "requestId": rid,
            "adAccessCode": "",
            "__cacheBust": str(random.random()),
        }
        body = {
            "prompt": prompt,
            "negativePrompt": negative_prompt,
            "seed": seed,
            "resolution": resolution,
            "guidanceScale": guidance_scale,
            "channel": "ai-text-to-image-generator",
            "subChannel": "public",
            "userKey": key,
            "adAccessCode": "",
            "requestId": rid,
        }
        headers = {"Content-Type": "text/plain;charset=UTF-8"}

        deadline = time.time() + self.poll_timeout
        while True:
            data = self._call_generate(params, body, headers)
            status = data.get("status")
            if status == "success":
                return self._download(data)
            if status == "invalid_key":
                raise InvalidKeyError("backend returned invalid_key")
            if status == "invalid_data":
                raise ValueError(
                    "Perchance rejected the request (invalid_data): "
                    f"{str(data)[:200]}")
            # "queued" or anything else: wait and retry the same request.
            if time.time() >= deadline:
                raise PerchanceError(
                    f"Perchance generation timed out after "
                    f"{self.poll_timeout}s (last status: {status})")
            time.sleep(4)

    def _call_generate(self, params, body, headers):
        """POST /generate first (reference implementation); fall back to GET
        (one source documents GET) on 404/405 or a non-JSON reply."""
        try:
            resp = self._http.post(
                f"{BASE}/generate", params=params,
                content=json.dumps(body), headers=headers)
            if resp.status_code in (404, 405):
                raise _UseGet()
            return resp.json()
        except _UseGet:
            pass
        except (ValueError, httpx.HTTPError):
            # Non-JSON reply — try the GET form before giving up.
            pass
        get_params = dict(params)
        get_params.update({
            "prompt": body["prompt"],
            "negativePrompt": body["negativePrompt"],
            "seed": body["seed"],
            "resolution": body["resolution"],
            "guidanceScale": body["guidanceScale"],
            "channel": body["channel"],
            "subChannel": body["subChannel"],
        })
        resp = self._http.get(f"{BASE}/generate", params=get_params)
        resp.raise_for_status()
        return resp.json()

    def _download(self, data):
        image_id = data.get("imageId")
        if not image_id:
            raise PerchanceError(f"success response had no imageId: {data}")
        url = data.get("imageDownloadUrl")
        if url:
            full = url if url.startswith("http") else \
                "https://image-generation.perchance.org" + url
        else:
            full = f"{BASE}/downloadTemporaryImage?imageId={image_id}"
        resp = self._http.get(full)
        resp.raise_for_status()
        return {
            "id": image_id,
            "bytes": resp.content,
            "seed": data.get("seed"),
            "width": data.get("width"),
            "height": data.get("height"),
            "ext": data.get("fileExtension", "jpeg"),
            "maybe_nsfw": data.get("maybeNsfw", False),
        }


class _UseGet(Exception):
    pass
