# Perchance Image API 🎨

Free, unlimited AI image generation as an **OpenAI-compatible** REST API —
a self-hosted wrapper around [Perchance.org](https://perchance.org)'s AI
image generator. No sign-up, no API key to pay for, no GPU of your own.

Any AI agent, website, or [Open WebUI](https://openwebui.com) instance can
use it exactly like OpenAI's image API:

```
POST /v1/images/generations   → {"data": [{"b64_json": "..."}]}
GET  /v1/models               → [{"id": "perchance-image"}]
GET  /styles                  → 75 art styles
GET  /health                  → status + key state
GET  /                        → browser demo page (prompt box + generate)
```

## How it works

Perchance has **no official public API**. This server replays the calls the
Perchance generator page makes in your browser:

1. `POST https://image-generation.perchance.org/api/generate` with a
   browser-verified `userKey` (64 hex chars), prompt, style, seed,
   resolution, guidance scale.
2. Poll while `status == "queued"`, then download the image.

### The key problem — and the fix

A `userKey` copied from a **different browser/machine does NOT work** — the
backend answers `invalid_key`. The key must be minted **on the same server**
that calls the API. So this server mints its own key automatically:

- **On startup** (background, non-blocking) and **whenever the backend
  returns `invalid_key`**, it launches a **stealth browser (Patchright —
  a patched Playwright drop-in)** , opens the Perchance generator page,
  moves the mouse and scrolls like a human while Cloudflare Turnstile
  runs, and captures the key from the `/api/verifyUser` call.
- The key is cached in memory and in `userkey.txt` (valid for hours–days).
- If the browser flow fails (no Chromium, Turnstile blocks it, tiny host),
  it falls back to the `PERCHANCE_USER_KEY` env var — a key you paste in
  by hand from a desktop browser **on the same machine**.

> Why Patchright and not plain Playwright? Plain Playwright Chromium is
> trivially fingerprinted (`--enable-automation`, `navigator.webdriver`,
> `Runtime.enable`/`Console.enable` CDP leaks) and Turnstile blocks it on
> datacentre IPs — that is what happened on Render. Patchright patches
> exactly those leaks and claims Cloudflare ✅. Honest limit: stealth fixes
> the *browser fingerprint*, not the *datacentre IP* — a Turnstile pass on
> Render is more likely now, but not guaranteed. If the mint fails,
> `/health` shows the reason in `last_key_error`.

## Deploy

### Option A — Render free (primary, NO card needed)

Render's free tier needs **no credit card**: 750 instance-hours/month,
512 MB RAM, 0.1 CPU, **5 GB/month outbound bandwidth**. The service spins
down after 15 min idle (~1 min cold start on the next request).

1. Push this folder to a GitHub repo.
2. render.com → New → Web Service → connect the repo.
3. Render auto-detects `render.yaml`: it deploys the **Docker** service
   on the **free plan** (declared in the file — without `plan: free` the
   Blueprint defaults to a paid plan). The Docker build installs
   Patchright Chromium; the container runs uvicorn on `$PORT`.
4. Your API is live at `https://perchance-api.onrender.com` (or your
   service name). Open it in a browser for the demo page.

> Bandwidth note: 5 GB/month outbound. Images are ~100–300 KB each, so
> that is roughly 15,000–50,000 images/month — plenty for personal use,
> but don't hot-link the API publicly.

### Option B — Docker (any Docker host)

```bash
docker build -t perchance-api .
docker run -p 8000:8000 perchance-api
# open http://localhost:8000  (demo page)
```

The image includes Patchright Chromium for the auto-key refresh. Needs
~300 MB free RAM while the browser runs (a few seconds per refresh).

### Option C — plain Python (VPS / any always-on host)

```bash
pip install -r requirements.txt
patchright install chromium --with-deps   # for auto-key refresh
uvicorn server:app --host 0.0.0.0 --port 8000
```

### Option D — PaaS via Procfile (Railway, Heroku-style hosts)

Push the repo, set the start command from `Procfile`, and make the build
step run `patchright install chromium` (or set `PERCHANCE_USER_KEY` and
skip the browser entirely).

## Use the API

```bash
HOST=http://localhost:8000

# health + key state
curl $HOST/health

# list styles (75 + 4 NSFW)
curl $HOST/styles

# generate one image (OpenAI shape)
curl -X POST $HOST/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "a steampunk woman", "model": "perchance-image",
       "size": "1024x1024", "n": 1, "style": "Studio Ghibli"}'

# with the OpenAI Python client (any agent can use this)
python -c "
from openai import OpenAI
import base64
c = OpenAI(base_url='$HOST/v1', api_key='not-needed')
img = c.images.generate(model='perchance-image',
    prompt='a cute cat', size='1024x1024')
open('cat.jpg','wb').write(base64.b64decode(img.data[0].b64_json))
"
```

### Parameters (`POST /v1/images/generations`)

| Field | Default | Notes |
|---|---|---|
| `prompt` | — (required) | Image description |
| `model` | `perchance-image` | `perchance-image` (SFW) or `perchance-image-uncensored` (18+, see below) |
| `uncensored` | `false` | `true` = uncensored path — same as using the `-uncensored` model; also auto-enabled by picking an NSFW style |
| `size` | `1024x1024` | Mapped by aspect ratio: square→`768x768`, landscape→`768x512`, portrait→`512x768` |
| `n` | `1` | Count, 1–4 (each ~10–20 s, serialised) |
| `style` | `""` | Exact name from `GET /styles` (e.g. `Studio Ghibli`) — baked into the prompt |
| `negative_prompt` | `""` | Things to exclude (also accepts `negativePrompt`) |
| `seed` | `-1` | `-1` = random; a fixed int reproduces the image |
| `guidance_scale` | `7` | 1–30, prompt adherence |

### Uncensored (18+) mode

Perchance has no separate "uncensored model" parameter — the NSFW/SFW
axis is a **channel** switch in the generate call, documented in the
reverse-engineered b7kc35yv7u client (`adrianx26/webgenimg`):

- `subChannel: "nsfw"` instead of `"public"` in the `/generate` body
- adult prompt handling: if `nsfw` isn't already in the prompt, append
  `, (nsfw:1.2), mature, highly detailed`; anti-NSFW terms
  (`nsfw`, `nudity`, `inappropriate`, `18+ content`) are stripped from
  the negative prompt

Turn it on any of three ways:

```bash
# 1. flag
curl -X POST $HOST/v1/images/generations -H 'Content-Type: application/json' \
  -d '{"prompt": "a portrait", "uncensored": true}'

# 2. model id (what Open WebUI uses — set Model to this)
#    model: perchance-image-uncensored

# 3. pick an NSFW style — "NSFW - Realistic", "NSFW - Anime",
#    "NSFW - Realistic (Stronger)", "NSFW - Anime (Stronger)"
#    (exact templates from the b7kc35yv7u source; the demo page has a
#    🔞 Uncensored checkbox too)
```

Honest note: the API now uses `channel="b7kc35yv7u"` (the reference client's page) for all generations, paired with `subChannel="nsfw"` for uncensored — that is the documented pairing. Live uncensored generation is still untested.

## Open WebUI setup

Admin Panel → Settings → Images:

- Image Generation Engine: **Default (Open AI)**
- API Base URL: `https://<your-host>/v1`
- API Key: `not-needed` (any value — the proxy ignores it)
- Model: `perchance-image`

Then toggle the **Image** switch in any chat.

## Honest limits

- **Max 768 px on a side** — Perchance's backend cap. `1024x1024` requests
  are mapped down to `768x768`.
- **10–20 s per image** (longer under load); requests are serialised, and
  the server sleeps 2 s between images to be gentle.
- **Per-IP request counting** — Perchance tracks AI requests per IP over
  2 days. A shared hosting IP can hit "too many requests". Keep volume low.
- **Key lifetime is hours–days.** Auto-refresh handles it when the
  stealth browser works; otherwise set `PERCHANCE_USER_KEY` by hand.
  Stealth improves the Turnstile pass rate on datacentre IPs but cannot
  guarantee it — if the mint keeps failing, `/health` shows
  `last_key_error` with the reason.
- **Cold starts** on free hosts (e.g. spin-down after 15 min idle) add
  ~1 min to the first request.
- **Live image generation is UNTESTED from the build machine** (Perchance's
  bot verification blocks this machine). The server, endpoints, style
  mapping, and error paths are tested locally — the first real image
  should be verified after deploy.

## Terms — read this

Perchance's Terms of Service §3(5) prohibit accessing the service "through
automated or non-human means, whether through a bot, script or otherwise",
and §5 prohibits circumventing security measures. This wrapper is
reverse-engineered and unofficial. Practical risk is loss of access
(`invalid_key`, rate-limit, IP block), not a lawsuit — but use it at your
own risk, keep request volumes reasonable, and don't hammer it. The
generated images themselves are free for any use, including commercial,
per Perchance's own FAQ.
