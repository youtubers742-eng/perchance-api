# -*- coding: utf-8 -*-
"""Perchance image API — OpenAI-compatible FastAPI server.

Any AI agent, website, or Open WebUI instance can point at this server the
same way it points at OpenAI's image API:

  POST /v1/images/generations   (OpenAI shape, returns b64_json images)
  GET  /v1/models               (lists the "perchance-image" model)
  GET  /styles                  (75 art styles)
  GET  /health                  (status + key state)
  GET  /                        (browser demo page)

Open WebUI setup: Admin → Settings → Images → Engine "Default (Open AI)",
API Base URL = https://<your-host>/v1, API Key = anything (e.g. "not-needed"),
Model = perchance-image.

Run:  uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
"""

import base64
import logging
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from client import InvalidKeyError, KeyManager, PerchanceClient, PerchanceError
from styles import STYLES, apply_style, list_styles

logger = logging.getLogger(__name__)

MODEL_ID = "perchance-image"
MAX_IMAGES_PER_REQUEST = 4          # OpenAI 'n' is clamped to 1..4
MAX_RESOLUTION_SIDE = 768           # Perchance backend cap

app = FastAPI(title="Perchance Image API",
              description="OpenAI-compatible image generation backed by "
                          "Perchance.org (free, no login).",
              version="1.0.0")

_client = PerchanceClient()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def size_to_resolution(size):
    """Map an OpenAI-style size (e.g. '1024x1024') to a Perchance
    resolution by aspect ratio. Perchance only supports 768px on a side."""
    try:
        w_str, h_str = str(size).lower().split("x")
        w, h = int(w_str), int(h_str)
    except Exception:
        return "768x768"
    if w == h:
        return "768x768"
    if w > h:
        return "768x512"   # landscape
    return "512x768"       # portrait


def _extra(req, *names, default=None):
    """Pull an optional field from the request body, including anything the
    client sent via OpenAI extra_body (e.g. negativePrompt, style)."""
    for name in names:
        value = getattr(req, name, None)
        if value not in (None, "", -1):
            return value
        if req.model_extra and name in req.model_extra:
            value = req.model_extra[name]
            if value not in (None, ""):
                return value
    return default


# --------------------------------------------------------------------------
# request model
# --------------------------------------------------------------------------
class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # accept extra_body fields

    prompt: str = Field(..., min_length=1, description="Image description")
    model: str = MODEL_ID
    size: str = "1024x1024"
    n: int = 1
    negative_prompt: str = ""
    style: str = ""
    seed: int = -1
    guidance_scale: float = 7.0


# --------------------------------------------------------------------------
# OpenAI-compatible endpoints
# --------------------------------------------------------------------------
@app.post("/v1/images/generations")
def create_images(req: ImageRequest):
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    style = _extra(req, "style", default="") or ""
    if style and style not in STYLES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown style {style!r}; see GET /styles "
                   f"({len(STYLES)} available)")

    full_prompt = apply_style(style, prompt) if style else prompt
    negative = _extra(req, "negative_prompt", "negativePrompt", default="") or ""
    seed = _extra(req, "seed", default=-1)
    guidance = _extra(req, "guidance_scale", "guidanceScale", default=7.0)
    try:
        guidance = max(1.0, min(30.0, float(guidance)))
    except (TypeError, ValueError):
        guidance = 7.0
    n = max(1, min(MAX_IMAGES_PER_REQUEST, int(req.n or 1)))
    resolution = size_to_resolution(req.size)

    data = []
    try:
        for _ in range(n):
            result = _client.generate(
                prompt=full_prompt,
                negative_prompt=negative,
                seed=int(seed) if seed is not None else -1,
                resolution=resolution,
                guidance_scale=guidance,
            )
            data.append({
                "b64_json": base64.b64encode(result["bytes"]).decode(),
                "revised_prompt": prompt,
            })
            time.sleep(2)  # be gentle with the shared free backend
    except InvalidKeyError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Perchance key rejected and auto-refresh failed: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PerchanceError as e:
        raise HTTPException(status_code=502, detail=f"Perchance error: {e}")
    except Exception as e:  # noqa: BLE001 - surface upstream failures cleanly
        raise HTTPException(status_code=502, detail=f"Generation failed: {e}")

    return {"created": int(time.time()), "data": data}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{
            "id": MODEL_ID,
            "object": "model",
            "created": 0,
            "owned_by": "perchance",
        }],
    }


# --------------------------------------------------------------------------
# helper endpoints
# --------------------------------------------------------------------------
@app.get("/styles")
def get_styles():
    """All 75 art styles. Pass one as `style` in the generation request
    (or as extra_body.style from an OpenAI client)."""
    return {"count": len(STYLES), "styles": list_styles()}


@app.get("/health")
def health():
    km = _client.keys
    return {
        "ok": True,
        "model": MODEL_ID,
        "styles": len(STYLES),
        "key_cached": bool(km.key),
        "key_source": km.source,  # env | file | browser | none
        # Why the last browser mint failed (None = never tried / last ok).
        # Lets anyone diagnose a dead key from /health alone — no need to
        # dig through Render logs, which previously showed nothing.
        "last_key_error": km.last_error,
        "last_key_attempt": km.last_attempt,
        "max_resolution": "768x768",
    }


@app.get("/", response_class=HTMLResponse)
def demo_page():
    """Minimal browser demo — prompt box + style/size pickers + generate."""
    options = "".join(
        f'<option value="{s}">{s}</option>' for s in list_styles())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Perchance Image API — demo</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:640px;margin:24px auto;padding:0 16px}}
input,select,button{{font-size:16px;padding:10px;width:100%;margin:6px 0;box-sizing:border-box}}
button{{background:#111;color:#fff;border:0;border-radius:8px;cursor:pointer}}
img{{max-width:100%;margin-top:12px;border-radius:8px}}
small{{color:#666}}
</style></head><body>
<h1>🎨 Perchance Image API</h1>
<p><small>Free image generation · OpenAI-compatible · model <b>perchance-image</b></small></p>
<input id="prompt" placeholder="Describe your image… e.g. a steampunk woman">
<select id="style"><option value="">No style</option>{options}</select>
<select id="size">
  <option value="1024x1024">Square</option>
  <option value="1024x768">Landscape</option>
  <option value="768x1024">Portrait</option>
</select>
<button id="go" onclick="gen()">Generate (10–20s)</button>
<p id="status"></p>
<div id="out"></div>
<script>
async function gen(){{
  const b=document.getElementById('go'), s=document.getElementById('status');
  b.disabled=true; s.textContent='Generating… please wait (10–20s)';
  document.getElementById('out').innerHTML='';
  try{{
    const r=await fetch('/v1/images/generations',{{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{
        prompt:document.getElementById('prompt').value,
        model:'perchance-image',
        size:document.getElementById('size').value,
        style:document.getElementById('style').value,
        n:1
      }})
    }});
    const j=await r.json();
    if(!r.ok) throw new Error(j.detail||r.status);
    s.textContent='Done ✓';
    j.data.forEach(d=>{{
      const img=document.createElement('img');
      img.src='data:image/jpeg;base64,'+d.b64_json;
      document.getElementById('out').appendChild(img);
    }});
  }}catch(e){{ s.textContent='Error: '+e.message; }}
  b.disabled=false;
}}
</script>
<p><small>API: POST /v1/images/generations · GET /v1/models · GET /styles ·
GET /health — see README.md for Open WebUI setup.</small></p>
</body></html>"""


# --------------------------------------------------------------------------
# startup: warm the userKey in the background (non-blocking) so the first
# real request does not pay the browser-launch cost. If it fails, the first
# generation will retry the refresh on demand.
# --------------------------------------------------------------------------
@app.on_event("startup")
def _warm_key():
    def _warm():
        try:
            _client.keys.get_key()
        except Exception as e:  # noqa: BLE001 - log it; silent pass hid
            # the mint failure until the first real generation failed.
            logger.warning("Perchance startup key warm-up failed: %s", e,
                           exc_info=True)
    threading.Thread(target=_warm, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")))
