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

STEALTH — why Patchright, and its honest limit
-----------------------------------------------
Plain Playwright Chromium is trivially detectable (``--enable-automation``,
``navigator.webdriver``, ``Runtime.enable``/``Console.enable`` CDP leaks)
and Cloudflare Turnstile blocks it on datacentre IPs — that is exactly
what happened on Render. So the mint uses **Patchright**, a patched
Playwright drop-in: it removes the automation flags, executes JS in
isolated contexts (no ``Runtime.enable`` leak), disables the Console API
leak, and passes Cloudflare's fingerprint checks. On top of that the mint
moves the mouse like a human, scrolls, and waits with random delays
instead of fixed ones, and retries the verifyUser call a few times
(Turnstile can take seconds to complete).

Honest limit: stealth fixes the *browser fingerprint* — it cannot change
the *datacentre IP*. Turnstile scores the IP too, so a pass on Render is
more likely now but NOT guaranteed. If the mint still fails, /health shows
the reason in ``last_key_error``; the fallbacks are the env-var key or a
non-datacentre host.

REFINED MINT (2026-11-06) — the first stealth deploy still failed
("browser mint returned no key"), and reading the reference client
(adrianx26/webgenimg, the only documented working browser flow) showed
why: the page only calls /api/verifyUser and /api/generate AFTER a real
Generate click — the old mint never clicked anything, so the page never
yielded a key at all. The mint now (A) clicks a visible Turnstile widget
if one appears, (B) clicks the "I am over 18" gate if shown, (C) clicks
the Generate button in the generator iframe and captures the key from
the /api/generate request URL (the old listener only watched verifyUser
URLs and missed it), re-checking the widget while waiting, and (D) falls
back to the direct in-page verifyUser fetch x3. Every step is logged to
a trail surfaced in /health as last_mint_steps, so a failure says
exactly where it died (widget? gate? generate click? verifyUser HTTP
status?). If this still fails on Render, the remaining honest
explanation is the datacentre IP itself — stealth cannot change it.

COLAB FINDING (2026-11-06) — on Colab the mint got FURTHER (cf_clearance
present: Turnstile PASSED on Google's IP) but still captured no key:
Generate was clicked, yet no /api/generate request ever fired in 30s.
Prime suspect: the mint clicked Generate with the prompt box EMPTY, and
the page validates the prompt before firing anything. Phase B now fills
a dummy prompt ("a red rose") before clicking Generate. Phase C was
hardened too: the in-page fetch threw every time (a cross-origin fetch
from perchance.org to image-generation.perchance.org hits CORS), so it
now escalates fetch -> context API request (same cookies, no CORS) ->
navigate to the verifyUser URL (the reference client's approach).
The fill itself was then fixed the same day (2026-11-06, 17:17 IST):
live inspection of the real generator page showed the prompt box is a
<textarea class="paragraph-input" data-name="description"> INSIDE the
generator <iframe> — the outer page is a shell, so a top-level search
finds nothing (that is why the first fill timed out). The placeholder
rotates every 3.5s and is never matched on; there is no negative-prompt
box on the page. _fill_prompt now scans perchance.org frames for
``textarea.paragraph-input[data-name="description"]`` then
``textarea[data-name="description"]``.

KEY-CAPTURE WIDENING (2026-11-06) — the fill fix worked (live Colab
trail: prompt filled, Generate clicked, cf_clearance present) yet still
no key: NO request URL carried "userKey=" in 30s. Two hypotheses:
(A) the key travels in a POST body (JSON/form) or a response body, not
the URL; (B) the page calls a different endpoint, or fires nothing at
all. The listener now captures from request URLs, POST bodies, and
/api/* response bodies, and logs every /api/* call (method + path +
key?) in the step trail, so the next live run says definitively
whether generate fired and where the key lives.

RAM note: full Chromium (required — Turnstile blocks Playwright's headless
shell) needs roughly 250-400 MB while it runs. The browser is only launched
on demand (LAZY — never at startup; the 2026-11-06 startup warm-up mint
killed the Render instance into a restart loop, so it was removed), in a
worker thread with a HARD 90s timeout that kills the browser on expiry,
with the renderer capped to one process and a 256 MB V8 heap cap. The
steady-state server stays small and /health always answers instantly.
Patchright uses the same Chromium binary family, so its RAM is in the
same range; Camoufox (Firefox-based, heavier, plus a separate browser
download) was deliberately NOT used for this reason.

UNCENSORED MODE — how Perchance actually selects it
---------------------------------------------------
There is NO separate "uncensored model" parameter in the generate
request, and no model field at all. The NSFW/SFW axis is controlled by
two things, both documented in the reverse-engineered b7kc35yv7u client
(adrianx26/webgenimg, perchance_client.py + extracted_styles.json):

  1. ``subChannel``: ``"nsfw"`` instead of ``"public"`` in the /generate
     body — the backend-level switch (``target_sub_channel = ... "nsfw"
     if adult_mode else "public"``).
  2. Adult prompt composition (``compose_prompt``): if "nsfw" is not
     already in the prompt, append ``", (nsfw:1.2), mature, highly
     detailed"``; if "nsfw" is in the negative prompt, strip the
     anti-NSFW terms (nsfw / nudity / inappropriate / 18+ content).
     The NSFW art styles ("NSFW - Realistic", "NSFW - Anime", and the
     "(Stronger)" variants with ``(((nsfw)))`` weighting) are prompt
     templates that do the same thing by content.

``generate(uncensored=True)`` applies exactly that: subChannel="nsfw"
plus the documented prompt handling, nothing invented.

CAVEAT (unverified pairing): the reference client sends subChannel="nsfw"
paired with channel="b7kc35yv7u" (a different Perchance generator page).
This client keeps channel="ai-text-to-image-generator" and only flips
subChannel. If live uncensored generation is refused (invalid_data) or
comes back filtered, the first thing to try is channel="b7kc35yv7u" for
uncensored requests — that page also shows an "I am over 18 - Show
Content" gate to new browser sessions, which the mint flow would then
need to click.
"""

import json
import logging
import os
import random
import re
import threading
import time
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

BASE = "https://image-generation.perchance.org/api"
GENERATOR_PAGE = "https://perchance.org/ai-text-to-image-generator"

# HARD mint budget (seconds). The mint used to run up to 150s+ with no
# overall cap, and Render's 512 MB free instance died mid-mint (restart
# loop, 502s): either OOM (full Chrome + heavy Perchance SPA) or the
# health check failing while the server was stuck minting. The mint now
# runs in a worker thread with this hard timeout — on expiry the browser
# is killed and the caller gets the clean "no key" error. All phase
# budgets inside _mint_via_browser must fit inside this number.
_MINT_TIMEOUT = 90

# A current desktop Chrome UA — the backend expects a browser-like client.
# Linux UA on purpose: the binary runs on Linux, so navigator.platform
# agrees with the UA (a Windows UA on a Linux binary is itself a tell).
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")

# Realistic desktop viewport. 800x600 (the old value) is a classic
# headless tell; 1366x768 is the most common desktop size in real traffic.
VIEWPORT = {"width": 1366, "height": 768}

# Lean Chromium flags: no sandbox (containers), no /dev/shm (small hosts),
# no GPU, no background services. Full Chromium binary, NOT headless shell
# (Turnstile blocks the shell build).
_BASE_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-translate",
    "--mute-audio",
    "--no-first-run",
    "--disable-features=site-per-process",
    # NOTE: --single-process was here for 512 MB hosts (one process keeps
    # RSS down), but it was REMOVED 2026-11-06: it crashes the FULL Chrome
    # binary at startup ("Cannot use V8 Proxy resolver in single process
    # mode", browser dies before new_page — verified locally: launch with
    # it fails, without it the browser stays alive). It only ever worked
    # with the headless shell, which Turnstile blocks anyway. Multi-process
    # full Chrome for a single mint page runs ~250-400 MB — the range the
    # module docstring already documents. --no-zygote is kept: stable in
    # containers and saves a little RAM.
    "--no-zygote",
    "--disable-software-rasterizer",
    # RAM caps for 512 MB hosts (added 2026-11-06 after the refined mint
    # OOM-killed the Render instance into a restart loop): one renderer
    # process only, and a 256 MB V8 heap cap so the heavy Perchance SPA
    # cannot grow the renderer without bound. 256 MB is enough for
    # Turnstile + one Generate click; the browser is killed on timeout.
    "--renderer-process-limit=1",
    "--js-flags=--max-old-space-size=256",
]

# Patchright path: Patchright already removes --enable-automation and adds
# --disable-blink-features=AutomationControlled itself. Do NOT re-add
# --disable-extensions here — Patchright deliberately removes it (a
# browser with extensions disabled is a detection signal).
PATCHRIGHT_ARGS = _BASE_ARGS + ["--disable-blink-features=AutomationControlled"]

# Plain-Playwright fallback path (only used if Patchright is not
# installed): same lean flags, plus the AutomationControlled blink
# feature; --disable-extensions kept here for RAM (plain Playwright is
# detectable anyway, so the flag costs nothing extra there).
PLAYWRIGHT_ARGS = _BASE_ARGS + [
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
]

_KEY_RE = re.compile(r'"userKey"\s*:\s*"([0-9a-fA-F]{64})"')
_KEY_IN_URL_RE = re.compile(r"userKey=([0-9a-fA-F]{64})")
# Same key in any other encoding (form-data name=, "userKey": with
# different quoting, ...): the literal label, a short run of non-hex
# separators, then the 64 hex chars. Catches encodings the two patterns
# above miss without matching bare hashes (the label must be present).
_KEY_ANY_RE = re.compile(r'userKey[^0-9a-fA-F]{1,12}([0-9a-fA-F]{64})')

# Host whose /api/* calls the mint logs in the step trail. Overridden
# in tests to point at a localhost mock (the mock's /api/* calls must
# be logged the same way the real ones are).
_API_HOST = "perchance.org"


def _load_browser_engine():
    """Return (sync_playwright, engine_name, launch_args).

    Patchright first (stealth-patched Chromium — the only engine with a
    real chance against Turnstile on a datacentre IP). Falls back to
    plain Playwright if Patchright is not installed, so local dev
    without patchright still works.
    """
    try:
        from patchright.sync_api import sync_playwright
        return sync_playwright, "patchright", PATCHRIGHT_ARGS
    except ImportError:
        pass
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright, "playwright", PLAYWRIGHT_ARGS
    except ImportError:
        return None, "none", []


def _humanize(page):
    """Move the mouse and scroll the way a real visitor does, with
    random pauses. Turnstile's managed challenge watches behaviour as
    well as fingerprints; a browser that never moves the mouse is an
    obvious bot. Kept short (a few seconds) so the mint stays fast."""
    w, h = VIEWPORT["width"], VIEWPORT["height"]
    try:
        # A few smooth mouse moves across the page.
        for _ in range(3):
            x = random.randint(80, w - 80)
            y = random.randint(80, h - 80)
            page.mouse.move(x, y, steps=random.randint(8, 20))
            page.wait_for_timeout(random.randint(400, 1200))
        # A small scroll, like someone glancing at the page.
        page.mouse.wheel(0, random.randint(120, 400))
        page.wait_for_timeout(random.randint(600, 1500))
    except Exception:
        pass  # mouse/scroll failing must never kill the mint


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
        # Step-by-step trail of the last browser mint (timestamped,
        # capped). Surfaced via /health as last_mint_steps so a dead key
        # can be diagnosed without Render logs: which step it died on.
        self._mint_steps = []
        # Hard-timeout machinery (2026-11-06 crash fix): the mint runs in
        # a worker thread; _mint_stop tells its wait loops to abort early
        # and _active_browser lets the watchdog kill the browser on
        # timeout. _mint_result is how the worker hands the key back.
        self._mint_stop = threading.Event()
        self._active_browser = None
        self._mint_result = {"key": None}
        # Load a usable key WITHOUT a browser: env var first, then the
        # cached key file from a previous successful mint. This used to be
        # dead code after a `return` in the mint_steps property, so a
        # cached key was never reused and every restart paid for a mint.
        self._load_initial_key()

    def _load_initial_key(self):
        """Pick up a key that needs no browser: PERCHANCE_USER_KEY env
        var wins, else the cached key file from a previous mint."""
        env_key = os.environ.get("PERCHANCE_USER_KEY", "").strip()
        if env_key:
            self._key = env_key
            self._source = "env"
            return
        if os.path.isfile(self._key_file):
            try:
                cached = open(self._key_file).read().strip()
                if cached:
                    self._key = cached
                    self._source = "file"
            except OSError:
                pass

    def _step(self, msg):
        """Record one mint step (timestamped, capped at 40 entries)."""
        ts = time.strftime("%H:%M:%S", time.localtime())
        entry = f"{ts} {msg}"
        self._mint_steps.append(entry)
        if len(self._mint_steps) > 40:
            self._mint_steps = self._mint_steps[-40:]
        logger.info("Perchance mint: %s", msg)

    @property
    def mint_steps(self):
        """Copy of the step trail from the last browser mint attempt."""
        return list(self._mint_steps)

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

    def get_key(self, timeout=_MINT_TIMEOUT):
        """Return a usable key, minting one in a browser if we have none.

        The mint runs in a worker thread with a HARD timeout (default
        90s): if it does not finish in time the browser is killed and
        None is returned, so a generation request can never hang the
        server for minutes or get the instance OOM-killed (the 2026-11-06
        restart loop). A cached env/file key returns instantly, no mint.
        """
        with self._lock:
            if self._key:
                return self._key
            return self._mint_with_timeout(timeout)

    def refresh(self, force=False, timeout=_MINT_TIMEOUT):
        """Force a fresh browser-minted key (used after invalid_key)."""
        with self._lock:
            if not force and self._key:
                return self._key
            return self._mint_with_timeout(timeout)

    def refresh_locked(self, timeout=_MINT_TIMEOUT):
        """Mint a key via headless Chromium. Caller must hold the lock.
        Kept for compatibility — delegates to the threaded mint."""
        return self._mint_with_timeout(timeout)

    def _env_fallback(self):
        """Use the PERCHANCE_USER_KEY env var if one is set (it may have
        appeared since startup). Returns the key or None."""
        env_key = os.environ.get("PERCHANCE_USER_KEY", "").strip()
        if env_key:
            self._key = env_key
            self._source = "env"
            return env_key
        return None

    def _close_active_browser(self):
        """Best-effort kill of the mint's browser (watchdog path, called
        from a different thread than the mint — Playwright may refuse a
        cross-thread close, so this is wrapped; the mint's own internal
        deadline is the real guarantee, this just hurries it)."""
        browser = self._active_browser
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

    def _mint_worker(self):
        """Runs in the worker thread: the browser mint + result handling.
        Never raises — records the failure and returns None via
        _mint_result so the caller always gets a clean answer."""
        self._last_attempt = time.time()
        self._mint_steps = []
        self._step("mint started")
        try:
            key = self._mint_via_browser(timeout=_MINT_TIMEOUT)
        except Exception as e:  # noqa: BLE001 - record, don't crash the call
            self._last_error = f"mint crashed: {type(e).__name__}: {e}"
            self._step(f"mint crashed: {self._last_error}")
            logger.warning("Perchance key mint crashed: %s", self._last_error)
            key = None
        if key:
            self._last_error = None
            self._key = key
            self._source = "browser"
            self._step("key captured OK (source=browser)")
            logger.info("Perchance key minted via browser (source=browser)")
            try:
                with open(self._key_file, "w") as f:
                    f.write(key)
            except OSError:
                pass
            self._mint_result["key"] = key
            return
        if not self._last_error:
            # Build the summary from the step trail so /health shows
            # exactly where the mint died (widget? generate click?
            # verifyUser status?) instead of one generic sentence.
            trail = "; ".join(s.split(" ", 1)[1] for s in self._mint_steps
                              if s.split(" ", 1)[1].startswith(
                                  ("widget:", "gate:", "generate:",
                                   "verifyUser:", "cookies:", "prompt:",
                                   "api:", "key:")))
            detail = f" [{trail}]" if trail else ""
            self._last_error = ("browser mint returned no key "
                                "(Turnstile blocked or page never yielded "
                                f"verifyUser){detail}")
        logger.warning("Perchance key mint failed: %s", self._last_error)
        self._mint_result["key"] = None

    def _mint_with_timeout(self, timeout):
        """Run the browser mint in a worker thread; hard-timeout it.

        Caller must hold the lock (serialises concurrent mints). On
        timeout: signal the mint to stop, try to kill its browser
        immediately, record the timeout, and fall back to the env var.
        Returns the key or None — never hangs past ``timeout`` seconds.
        """
        self._mint_stop.clear()
        self._mint_result = {"key": None}
        worker = threading.Thread(target=self._mint_worker, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            # HARD TIMEOUT — the mint is still running past its budget.
            # Stop it: flag the wait loops, kill the browser now.
            self._mint_stop.set()
            self._close_active_browser()
            self._last_error = (f"browser mint timed out after {timeout}s "
                                "(hard timeout; browser killed)")
            self._step(f"mint timed out after {timeout}s (hard timeout)")
            logger.warning("Perchance key mint timed out after %ss", timeout)
            return self._env_fallback()
        key = self._mint_result["key"]
        if key:
            return key
        return self._env_fallback()

    def invalidate(self):
        """Drop the cached key so the next call mints a fresh one."""
        with self._lock:
            self._key = None
            self._source = "none"

    # -- browser minting -------------------------------------------------
    def _click_turnstile_widget(self, page):
        """Find a Cloudflare Turnstile widget iframe and click it like a
        human. The widget lives in an iframe from
        challenges.cloudflare.com; it may sit on the main page or inside
        the generator iframe, so every frame's document is searched.
        Returns a short status string for the step trail."""
        try:
            for frame in page.frames:
                if self._mint_stop.is_set():
                    return "widget: aborted (mint stopped)"
                try:
                    loc = frame.locator(
                        'iframe[src*="challenges.cloudflare.com"]')
                    if loc.count() == 0:
                        continue
                    box = loc.first.bounding_box(timeout=2000)
                    if not box or box["width"] < 5 or box["height"] < 5:
                        return ("widget: present but hidden "
                                "(managed/invisible mode?)")
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    page.mouse.move(cx, cy, steps=random.randint(6, 12))
                    page.wait_for_timeout(random.randint(300, 800))
                    page.mouse.click(cx, cy)
                    return "widget: clicked"
                except Exception:
                    continue
            # No iframe found — is Turnstile even on this page?
            try:
                present = page.evaluate(
                    "() => !!document.querySelector("
                    "'iframe[src*=\\'challenges.cloudflare.com\\']') || "
                    "!!window.turnstile")
            except Exception:
                present = False
            return ("widget: none visible (managed/invisible mode?)"
                    if not present else "widget: present, click failed")
        except Exception as e:
            return f"widget: check failed ({type(e).__name__})"

    def _click_content_gate(self, page):
        """Click the 'I am over 18 - Show Content' gate if the page shows
        one (the reference client found it on fresh browser sessions).
        Returns a short status string for the step trail."""
        try:
            btn = page.get_by_text("I am over 18", exact=False)
            if btn.count() == 0:
                return "gate: absent"
            clicked = page.evaluate(
                """() => {
                    const b = document.getElementById("showContentBtn");
                    if (b) { b.click(); return true; }
                    return false;
                }""")
            if clicked:
                return "gate: clicked (#showContentBtn)"
            btn.first.click(timeout=5000)
            return "gate: clicked (text match)"
        except Exception as e:
            return f"gate: check failed ({type(e).__name__})"

    def _click_generate_button(self, page, deadline):
        """Click a button whose text contains 'generate' in any frame.
        This triggers the page's own verifyUser/generate calls — the
        userKey appears in the /api/generate request URL. Returns a
        short status string for the step trail.

        Only perchance.org frames are scanned: the page also loads ad
        iframes, and inner_text() on cross-origin ad frames is slow
        (1.5s timeout each) — scanning them burned most of the mint
        budget before the real button was ever reached."""
        try:
            for frame in page.frames:
                if self._mint_stop.is_set():
                    return "generate: aborted (mint stopped)"
                if time.time() > deadline:
                    return "generate: scan timed out"
                try:
                    url = frame.url or ""
                except Exception:
                    continue
                if "perchance.org" not in url:
                    continue
                try:
                    buttons = frame.locator("button")
                    n = buttons.count()
                except Exception:
                    continue
                for i in range(min(n, 12)):
                    if self._mint_stop.is_set():
                        return "generate: aborted (mint stopped)"
                    if time.time() > deadline:
                        return "generate: scan timed out"
                    try:
                        b = buttons.nth(i)
                        text = b.inner_text(timeout=1500)
                    except Exception:
                        continue
                    if "generate" not in text.lower():
                        continue
                    try:
                        b.click(timeout=8000)
                        return ("generate: clicked "
                                f"({text.strip()[:40]!r})")
                    except Exception as e:
                        return ("generate: found "
                                f"{text.strip()[:30]!r} but click failed "
                                f"({type(e).__name__})")
            return "generate: no button found in any frame"
        except Exception as e:
            return f"generate: scan failed ({type(e).__name__})"

    def _fill_prompt(self, page, deadline, prompt_text="a red rose"):
        """Type a dummy prompt into the generator's prompt box BEFORE
        clicking Generate. The page validates the prompt before firing
        /api/generate — with an empty prompt the Generate click does
        nothing and no userKey ever appears (the live Colab mint:
        Turnstile passed (cf_clearance present), Generate clicked,
        30s of silence, no request). Returns a short status string
        for the step trail. Never raises: a missing prompt box must
        not kill the mint (the Generate click is still attempted).

        FACTS (live inspection of the real generator page, 2026-11-06):
        the prompt box is a <textarea> INSIDE the generator <iframe>
        (the outer page is a shell — a search against the top-level
        document finds NOTHING, which is why the old fill timed out).
        Exact attributes: class="paragraph-input",
        data-name="description"; NO id, NO name. The placeholder
        ROTATES to a new random example every 3.5s, so it is NEVER
        used for matching. There is NO negative-prompt box on this
        page (commented out in settings), so none is looked for.

        Scans perchance.org frames (mirroring
        _click_generate_button: ad iframes are skipped) for
        ``textarea.paragraph-input[data-name="description"]`` then
        ``textarea[data-name="description"]``; fills, verifies the
        value stuck, and falls back to press_sequentially typing if
        the SPA ignores fill()."""
        last_fail = None
        try:
            for frame in page.frames:
                if self._mint_stop.is_set():
                    return "prompt: aborted (mint stopped)"
                if time.time() > deadline:
                    return "prompt: scan timed out"
                try:
                    url = frame.url or ""
                except Exception:
                    continue
                if "perchance.org" not in url:
                    continue
                label = url[:70] or "?"
                for selector in (
                        'textarea.paragraph-input[data-name="description"]',
                        'textarea[data-name="description"]'):
                    if self._mint_stop.is_set():
                        return "prompt: aborted (mint stopped)"
                    if time.time() > deadline:
                        return "prompt: scan timed out"
                    try:
                        loc = frame.locator(selector)
                        if loc.count() == 0:
                            continue
                        ta = loc.first
                    except Exception:
                        continue
                    try:
                        ta.click(timeout=5000)
                        ta.fill(prompt_text, timeout=5000)
                        val = ta.input_value(timeout=2000) or ""
                        if prompt_text not in val:
                            # Some SPAs ignore fill() — type it instead.
                            ta.press_sequentially(prompt_text, delay=30)
                            val = ta.input_value(timeout=2000) or ""
                        if prompt_text in val:
                            return (f"prompt: filled {prompt_text!r} "
                                    f"(textarea, frame {label})")
                        last_fail = ("prompt: fill did not stick "
                                     f"(textarea, frame {label})")
                    except Exception as e:
                        last_fail = (f"prompt: fill failed "
                                     f"({type(e).__name__}, frame {label})")
                    # A box was found in this frame (selector 2 is a
                    # superset of selector 1, so it would match the
                    # same box); move on to the next frame.
                    break
            if last_fail:
                return last_fail
            return "prompt: no prompt box found in any frame"
        except Exception as e:
            return f"prompt: check failed ({type(e).__name__})"

    @staticmethod
    def _check_cf_clearance(context):
        """True if Turnstile set the cf_clearance cookie — the tell that
        the challenge actually passed (vs. merely not showing)."""
        try:
            return any(c["name"] == "cf_clearance"
                       for c in context.cookies())
        except Exception:
            return False

    def _mint_via_browser(self, timeout=_MINT_TIMEOUT):
        """Open the generator page in a stealth browser and capture the
        userKey. Returns the key or None.

        Phased flow (learned from the reference client webgenimg, whose
        browser flow is the only documented one that works):

        A. Load the real generator page; let Turnstile's managed
           challenge run. If a Turnstile widget iframe is visible,
           click it like a human; click the "I am over 18" content
           gate if the page shows one. Check the cf_clearance cookie.
        B. FILL A DUMMY PROMPT ("a red rose") in the generator's prompt
           box, THEN click the Generate button in the generator iframe.
           This is the step the old mint was missing twice over: the
           page only calls /api/verifyUser and /api/generate after a
           real Generate click — and it validates the prompt first, so
           a Generate click with an EMPTY prompt fires nothing at all
           (the live Colab mint: Turnstile passed, Generate clicked,
           30s of silence). The key is captured from ANY request URL
           carrying userKey=..., from POST bodies (JSON/form), and
           from /api/* response bodies — the live Colab mint proved
           the URL alone is not where the key lives — and every /api/*
           call is logged, so the trail shows whether generate fired
           at all. The widget is re-checked during the wait — the
           challenge can also appear only after Generate is clicked.
        C. If still no key, verifyUser three different ways: in-page
           fetch (exact error recorded), context API request (same
           cookies, no CORS), navigate to the verifyUser URL (the
           reference client's approach — a navigation is never
           CORS-blocked, and the response listener captures the key
           from the JSON body).

        Every step is recorded in self._mint_steps so /health shows
        exactly where a failed mint died. Overall budget ``timeout``
        seconds (HARD — 90s; the old 150s budget plus unbounded phase
        waits let the mint outlive the host and kill the instance).
        The browser object is stored in self._active_browser so the
        watchdog can kill it on timeout, and every wait loop checks
        self._mint_stop so an abort lands fast. The browser is closed
        in ``finally``.
        """
        sync_playwright, engine_name, launch_args = _load_browser_engine()
        if sync_playwright is None:
            self._last_error = ("No stealth browser installed on this host "
                                "(patchright missing; playwright also missing)")
            self._step(f"engine: none — {self._last_error}")
            logger.warning("Perchance key mint: %s", self._last_error)
            return None

        found = []          # captured keys, in order found
        found_sources = []  # parallel: where each key was found
        verify_statuses = []
        # Every /api/* call the page makes, keyed by (method, path):
        # {"req": n, "key_req": bool, "key_resp": bool, "status": last,
        #  "key_source": str}. First occurrences (and a summary) go to
        # the step trail, so the next live run says definitively
        # whether /api/generate fired at all and where the key lived.
        api_calls = {}

        def _capture(text, source=""):
            """Search text for a userKey (JSON field, query/form param,
            or any other userKey=... encoding). Records the key and
            where it was found. Returns the key or None."""
            if not text:
                return None
            m = (_KEY_RE.search(text) or _KEY_IN_URL_RE.search(text)
                 or _KEY_ANY_RE.search(text))
            if not m:
                return None
            found.append(m.group(1))
            found_sources.append(source or "?")
            return m.group(1)

        def _api_path(url):
            try:
                return urlparse(url).path or "/"
            except Exception:
                return url

        def _log_api_req(method, url, key_found, key_source=""):
            path = _api_path(url)
            entry = api_calls.get((method, path))
            if entry is None:
                api_calls[(method, path)] = {
                    "req": 1, "key_req": key_found, "key_resp": False,
                    "status": None, "key_source": key_source}
                self._step(f"api: {method} {path} "
                           f"(key: {'yes' if key_found else 'no'})")
            else:
                entry["req"] += 1
                if key_found and not entry["key_req"]:
                    entry["key_req"] = True
                    entry["key_source"] = key_source

        def _log_api_resp(method, url, status, key_found, key_source=""):
            path = _api_path(url)
            entry = api_calls.get((method, path))
            if entry is None:
                api_calls[(method, path)] = {
                    "req": 0, "key_req": False, "key_resp": key_found,
                    "status": status, "key_source": key_source}
                if key_found:
                    self._step(f"api: {method} {path} "
                               "response carried key")
            else:
                entry["status"] = status
                if key_found and not entry["key_resp"]:
                    entry["key_resp"] = True
                    if not entry["key_source"]:
                        entry["key_source"] = key_source
                    self._step(f"api: {method} {path} "
                               "response carried key")

        def _api_summary():
            if not api_calls:
                return "api: no /api/* calls seen"
            parts = []
            for (method, path), e in sorted(api_calls.items()):
                s = f"{method} {path} x{e['req']}"
                if e["key_req"]:
                    s += " key:req"
                if e["key_resp"]:
                    s += " key:resp"
                if e["status"] is not None:
                    s += f" resp:{e['status']}"
                if not e["key_req"] and not e["key_resp"]:
                    s += " no-key"
                parts.append(s)
            return "api: " + " | ".join(parts)

        _last_summary = [None]

        def _log_api_summary():
            """Log the /api/* summary, but only when it changed since
            the last time (called after Phase B and at mint end)."""
            s = _api_summary()
            if s != _last_summary[0]:
                _last_summary[0] = s
                self._step(s)

        def _try_verify_fetch(page):
            """Ask for a key directly inside the page context — Turnstile
            cookies are already set by now. Returns True if a key landed.
            The JS wraps the fetch in try/catch and returns the exact
            error string, so a CORS/network failure is recorded (the old
            code only said 'fetch-threw' and the live Colab mint threw
            on every attempt). A __cacheBust param is added to match the
            real client's verifyUser call."""
            try:
                data = page.evaluate(
                    """async () => {
                        try {
                            const r = await fetch(
                              'https://image-generation.perchance.org/api/verifyUser'
                              + '?thread=0&__cacheBust=' + Math.random(),
                              {credentials: 'include'});
                            return 'OK ' + r.status + ' ' + await r.text();
                        } catch (e) {
                            return 'ERR ' + (e && e.message ? e.message : String(e));
                        }
                    }""") or ""
            except Exception as e:
                verify_statuses.append(
                    f"fetch-threw ({type(e).__name__}: {str(e)[:80]})")
                return False
            if data.startswith("ERR "):
                verify_statuses.append(f"fetch-error: {data[4:120]}")
                return False
            m = re.match(r"OK (\d{3})\s?(.*)$", data, re.S)
            status, body = (m.group(1), m.group(2)) if m else ("?", "")
            if "Attention Required" in body or \
                    "challenges.cloudflare.com" in body:
                kind = "cf-challenge-page"
            elif body.lstrip().startswith("{"):
                kind = "json"
            elif not body.strip():
                kind = "empty"
            else:
                kind = "html/other"
            verify_statuses.append(f"{status} {kind}")
            before = len(found)
            _capture(data, "verifyUser fetch")
            return len(found) > before

        def _try_verify_api_request(ctx):
            """Same verifyUser call via the browser context's API
            request: it shares the context's cookies (cf_clearance
            included) but is NOT subject to the page's CORS rules, so
            a cross-origin fetch failure cannot block it. Returns
            True if a key landed."""
            try:
                resp = ctx.request.get(
                    "https://image-generation.perchance.org/api/verifyUser"
                    "?thread=0&__cacheBust=" + str(random.random()),
                    headers={"User-Agent": UA,
                             "Referer": "https://perchance.org/",
                             "Origin": "https://perchance.org"},
                    timeout=15000)
                status = str(resp.status)
                try:
                    body = resp.text()
                except Exception:
                    body = ""
                if "Attention Required" in body or \
                        "challenges.cloudflare.com" in body:
                    kind = "cf-challenge-page"
                elif body.lstrip().startswith("{"):
                    kind = "json"
                elif not body.strip():
                    kind = "empty"
                else:
                    kind = "html/other"
                verify_statuses.append(f"api-req {status} {kind}")
                before = len(found)
                _capture(body, "verifyUser api-request")
                return len(found) > before
            except Exception as e:
                verify_statuses.append(
                    f"api-req threw ({type(e).__name__}: {str(e)[:80]})")
                return False

        def _try_verify_navigate(page):
            """Navigate the page to the verifyUser URL itself (the
            reference client's approach): a navigation is never
            CORS-blocked, and the response listener captures the key
            from the JSON body. Returns True if a key landed."""
            try:
                page.goto(
                    "https://image-generation.perchance.org/api/verifyUser"
                    "?thread=0&__cacheBust=" + str(random.random()),
                    wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1500)
                if found:
                    return True
                verify_statuses.append("navigate: no key in response")
                return False
            except Exception as e:
                verify_statuses.append(
                    f"navigate threw ({type(e).__name__}: {str(e)[:80]})")
                return False

        start = time.time()
        deadline = start + timeout
        try:
            with sync_playwright() as p:
                # CRITICAL: channel="chromium" forces the FULL Chrome
                # binary. Without it, Playwright/Patchright 1.49+ default
                # to the lightweight chromium-headless-shell in headless
                # mode — and Turnstile blocks the shell build outright.
                # (Verified: plain launch looked for
                # chromium_headless_shell-1248; channel="chromium" selects
                # the full Chrome-for-Testing binary in new headless mode.)
                self._step(f"engine: {engine_name} (full chromium)")
                browser = p.chromium.launch(headless=True, args=launch_args,
                                            channel="chromium")
                # Watchdog handle: _mint_with_timeout can kill this
                # browser from another thread if the hard timeout fires.
                self._active_browser = browser
                try:
                    ctx = browser.new_context(
                        user_agent=UA,
                        viewport=VIEWPORT,
                        locale="en-US",
                        # Render's default region is Oregon, US West.
                        timezone_id="America/Los_Angeles",
                    )
                    page = ctx.new_page()

                    def _on_request(req):
                        # Capture from ANY request carrying a userKey:
                        # the URL (the old behaviour), AND the POST
                        # body (JSON or form-encoded — the live Colab
                        # mint clicked Generate and no request URL
                        # carried userKey= in 30s, so the key may
                        # travel in the body instead). Every /api/*
                        # call is logged so the trail shows whether
                        # generate fired at all.
                        url = req.url or ""
                        is_api = "/api/" in url and _API_HOST in url
                        key_here = _capture(url, "request URL")
                        body_key = None
                        if req.method in ("POST", "PUT", "PATCH"):
                            body_key = _capture(
                                _request_body_text(req), "POST body")
                        if is_api:
                            _log_api_req(
                                req.method, url,
                                bool(key_here or body_key),
                                "url" if key_here else
                                ("body" if body_key else ""))

                    def _on_response(resp):
                        url = resp.url or ""
                        if "verifyUser" in url:
                            try:
                                verify_statuses.append(str(resp.status))
                            except Exception:
                                pass
                        if "/api/" not in url or _API_HOST not in url:
                            return
                        # The key may come back in a JSON response
                        # body (a verifyUser/generate reply) rather
                        # than in any request.
                        body = _safe_api_text(resp)
                        key_here = (_capture(body, "response body")
                                    if body else None)
                        try:
                            method = resp.request.method
                        except Exception:
                            method = "?"
                        try:
                            status = resp.status
                        except Exception:
                            status = None
                        _log_api_resp(method, url, status,
                                      bool(key_here),
                                      "response" if key_here else "")

                    page.on("request", _on_request)
                    page.on("response", _on_response)

                    # -- Phase A: load the page, face the challenge -----
                    try:
                        page.goto(GENERATOR_PAGE,
                                  wait_until="domcontentloaded",
                                  timeout=30000)
                        self._step("page: loaded "
                                   f"(title={page.title()[:60]!r})")
                    except Exception as e:
                        self._step(f"page: goto failed "
                                   f"({type(e).__name__}: {e})")
                        raise
                    _humanize(page)
                    try:
                        # The Perchance SPA may never reach networkidle
                        # (ads/analytics keep connections open) — 8s is
                        # enough; the old 15s just burned budget.
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    self._step("page: settled (networkidle or timeout)")
                    self._step(self._click_turnstile_widget(page))
                    self._step(self._click_content_gate(page))
                    _humanize(page)
                    clearance = self._check_cf_clearance(ctx)
                    self._step("cookies: cf_clearance "
                               f"{'present' if clearance else 'absent'}")

                    # -- Phase B: fill a dummy prompt, click Generate,
                    #    wait for the key --------------------------------
                    # The page validates the prompt before firing
                    # /api/generate: with an empty prompt the Generate
                    # click fires nothing and no userKey ever appears
                    # (live Colab mint: Turnstile passed, Generate
                    # clicked, 30s of silence). Fill first, then click.
                    self._step(self._fill_prompt(
                        page, min(deadline, time.time() + 12)))
                    self._step(self._click_generate_button(
                        page, min(deadline, time.time() + 12)))
                    wait_until = min(deadline, time.time() + 30)
                    last_widget_check = 0
                    while (not found and not self._mint_stop.is_set()
                           and time.time() < wait_until):
                        page.wait_for_timeout(1000)
                        now = time.time()
                        # Human-like movement while waiting, and re-check
                        # the widget — the challenge can appear only
                        # AFTER Generate is clicked.
                        if now - last_widget_check >= 10:
                            last_widget_check = now
                            _humanize(page)
                            status = self._click_turnstile_widget(page)
                            if status == "widget: clicked":
                                self._step(status)
                    if self._mint_stop.is_set():
                        self._step("key: aborted (mint stopped)")
                    elif found:
                        src = (found_sources[-1] if found_sources
                               else "page request")
                        self._step(f"key: captured from {src}")
                    else:
                        self._step("key: not in page requests/bodies/"
                                   "responses after Generate click (30s)")
                    _log_api_summary()

                    # -- Phase C: verifyUser, three different ways ------
                    # The old Phase C retried the SAME in-page fetch x3,
                    # but on the live Colab mint every attempt threw (a
                    # cross-origin fetch from perchance.org to
                    # image-generation.perchance.org hits CORS, so it
                    # throws "Failed to fetch"). Phase C now escalates:
                    # (1) in-page fetch (exact error recorded),
                    # (2) context API request (same cookies, no CORS),
                    # (3) navigate to the verifyUser URL (the reference
                    # client's approach — a navigation is never
                    # CORS-blocked, and the response listener captures
                    # the key from the JSON body).
                    methods = [
                        ("fetch",
                         lambda: _try_verify_fetch(page)),
                        ("api-request",
                         lambda: _try_verify_api_request(ctx)),
                        ("navigate",
                         lambda: _try_verify_navigate(page)),
                    ]
                    for name, fn in methods:
                        if found or self._mint_stop.is_set():
                            break
                        if time.time() > deadline - 8:
                            self._step(f"verifyUser: {name} skipped "
                                       "(budget left)")
                            break
                        if fn():
                            self._step(f"verifyUser: {name} returned a key")
                            break
                        self._step(
                            f"verifyUser: {name} no key (last HTTP "
                            f"{verify_statuses[-1] if verify_statuses else '?'})")
                        if (not found and not self._mint_stop.is_set()
                                and name != "navigate"
                                and time.time() < deadline - 8):
                            _humanize(page)
                            page.wait_for_timeout(
                                random.randint(3000, 5000))
                    ctx.close()
                finally:
                    self._active_browser = None
                    browser.close()
            # Final /api/* summary (deduped against the Phase B one).
            _log_api_summary()
        except Exception as e:  # noqa: BLE001 - log the real reason; the
            # old code swallowed this silently, so Render logs showed nothing
            # and /health only said key_cached:false.
            self._last_error = (f"browser mint failed [{engine_name}]: "
                                f"{type(e).__name__}: {e}")
            self._step(f"browser mint failed: {self._last_error}")
            logger.warning("Perchance key mint failed: %s",
                           self._last_error, exc_info=True)
            return None
        if not found:
            self._step("key: NOT captured (all phases exhausted)")
            logger.warning("Perchance key mint: browser ran but no userKey "
                           "was captured (Turnstile may have blocked this "
                           "datacentre IP)")
        return found[-1] if found else None


def _safe_text(resp):
    try:
        return resp.text()
    except Exception:
        return ""


def _request_body_text(req):
    """Best-effort request body as text (POST/PUT/PATCH). Playwright
    exposes it as ``post_data`` (str) or ``post_data_buffer`` (bytes);
    either can be absent. Never raises — a missing body just means
    there is nothing to capture from."""
    try:
        data = req.post_data
    except Exception:
        data = None
    if data:
        return data
    try:
        buf = req.post_data_buffer
    except Exception:
        buf = None
    if buf:
        try:
            return bytes(buf).decode("utf-8", "ignore")
        except Exception:
            return None
    return None


def _safe_api_text(resp):
    """Best-effort body text for an /api/* response. Skips the image
    download endpoint (binary, megabytes) and oversized or clearly
    non-text bodies; never raises. The key may come back in a JSON
    response body rather than in any request."""
    try:
        url = resp.url or ""
    except Exception:
        return ""
    if "downloadTemporaryImage" in url:
        return ""
    try:
        length = resp.headers.get("content-length")
        if length is not None and int(length) > 1_000_000:
            return ""
    except Exception:
        pass
    try:
        ctype = (resp.headers.get("content-type") or "").lower()
    except Exception:
        ctype = ""
    if ctype and ("json" not in ctype and "text" not in ctype
                 and "javascript" not in ctype):
        return ""
    return _safe_text(resp)


# -- uncensored (adult) prompt handling --------------------------------
# Verbatim from webgenimg's compose_prompt (adrianx26/webgenimg): the
# documented adult-mode transform. Applied by generate() when
# uncensored=True, BEFORE the request is sent (and before any retry, so
# both attempts use the composed prompt).
_ANTI_NSFW_RE = re.compile(r"\b(nsfw|nudity|inappropriate|18\+ content)\b",
                           re.I)


def _apply_adult_mode(prompt, negative):
    """Adult-mode prompt composition (documented, not invented).

    If "nsfw" is not already in the prompt, append
    ``", (nsfw:1.2), mature, highly detailed"``; if "nsfw" is in the
    negative prompt, strip the anti-NSFW terms from it. Returns
    ``(prompt, negative)`` with stray double commas cleaned up.
    """
    if "nsfw" not in prompt.lower():
        prompt = f"{prompt}, (nsfw:1.2), mature, highly detailed"
    if "nsfw" in negative.lower():
        negative = _ANTI_NSFW_RE.sub("", negative)
    prompt = re.sub(r",\s*,+", ",", prompt).strip(", ")
    negative = re.sub(r",\s*,+", ",", negative).strip(", ")
    return prompt, negative


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
                 resolution="768x768", guidance_scale=7, uncensored=False):
        """Generate one image. Returns dict with id/bytes/seed/width/height.

        On ``invalid_key`` the key is refreshed once in-browser and the
        request is retried automatically.

        ``uncensored=True`` selects Perchance's uncensored (adult) path
        exactly as the reverse-engineered b7kc35yv7u client documents it:
        subChannel="nsfw" in the generate call plus the adult prompt
        composition (see _apply_adult_mode). There is no separate model
        parameter — this is the mechanism the site itself uses.
        """
        if uncensored:
            prompt, negative_prompt = _apply_adult_mode(prompt,
                                                        negative_prompt)
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
                                           resolution, guidance_scale, key,
                                           uncensored=uncensored)
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
                                           resolution, guidance_scale, new_key,
                                           uncensored=uncensored)

    # -- internals -------------------------------------------------------
    def _generate_once(self, prompt, negative_prompt, seed, resolution,
                       guidance_scale, key, uncensored=False):
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
            # The uncensored switch: "nsfw" instead of "public".
            # Documented in webgenimg's client; see module docstring for
            # the channel-pairing caveat (reference pairs it with
            # channel="b7kc35yv7u").
            "subChannel": "nsfw" if uncensored else "public",
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
