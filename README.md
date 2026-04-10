# Qualys WebRTC Voice Demo

Browser-first Qualys support demo built on the OpenAI Realtime API, FastAPI, and SearchUnify grounding.

The old phone-call media bridge is gone. The browser now creates the WebRTC peer connection locally, while the FastAPI app handles the authenticated OpenAI call setup and serves:

- the desktop demo UI
- secure Realtime call setup so the browser never receives the long-lived OpenAI API key
- SearchUnify-backed grounding tools
- per-session call memory
- health and demo-readiness endpoints

## What the app does

- opens a browser WebRTC session with backend-mediated OpenAI call setup
- keeps the conversation voice-first with live caller and assistant transcript panels
- preserves Qualys support context across turns with backend memory tools
- grounds exact troubleshooting, error details, API facts, and integration questions with SearchUnify when the model decides it needs them
- exposes a polished desktop-first demo interface instead of a phone-call flow

## Security note

This version keeps the long-lived OpenAI API key on the backend.

The browser sends only its SDP offer to `/api/realtime-call`, and the FastAPI server uses the server-side key when it calls OpenAI `POST /v1/realtime/calls`.

That removes the original browser key exposure risk while preserving the same browser-based WebRTC user experience.

Official OpenAI references used for this migration:

- Realtime API reference: https://platform.openai.com/docs/api-reference/realtime
- Realtime conversations guide: https://platform.openai.com/docs/guides/realtime-model-capabilities

## Runtime shape

Browser:

- captures microphone audio
- creates the WebRTC peer connection
- sends the SDP offer to `/api/realtime-call`
- sends and receives Realtime events on the data channel
- handles model tool calls in the browser and forwards them to the FastAPI backend

FastAPI backend:

- serves `/` and `/static/*`
- returns safe browser session config from `/api/realtime-config`
- creates the authenticated OpenAI Realtime call from `/api/realtime-call`
- stores session memory through `/api/tool/remember-context` and `/api/tool/get-context`
- runs SearchUnify lookups through `/api/tool/search`

## Key endpoints

- `GET /`
- `GET /health`
- `GET /api/realtime-config`
- `POST /api/realtime-call`
- `POST /api/session/reset`
- `POST /api/context/transcript`
- `POST /api/tool/remember-context`
- `POST /api/tool/get-context`
- `POST /api/tool/search`
- `GET /demo-readiness`
- `GET /demo-search`

## Environment variables

Required:

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-realtime
VOICE=alloy
ASSISTANT_NAME=Aira
SUPPORT_PRODUCT=Qualys
```

Common UI and session settings:

```env
PORT=3300
PUBLIC_URL=https://your-domain.example/socket/invoke
AI_SPEAKS_FIRST=true
TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
TRANSCRIPTION_LANGUAGE=en
TRANSCRIPTION_NOISE_REDUCTION=near_field
SERVER_VAD_THRESHOLD=0.62
SERVER_VAD_PREFIX_PADDING_MS=300
SERVER_VAD_SILENCE_DURATION_MS=450
```

SearchUnify grounding:

```env
KNOWLEDGE_BACKEND_URL=https://your-instance.searchunify.ai/search/searchResultByPost
KNOWLEDGE_BACKEND_NAME=SearchUnify
KNOWLEDGE_BACKEND_KIND=searchunify_post
SEARCHUNIFY_UID=...
SEARCHUNIFY_ACCESS_TOKEN=...
SEARCHUNIFY_SID=...
SEARCHUNIFY_ORIGIN=https://your-instance.searchunify.ai
SEARCHUNIFY_REFERER=https://your-instance.searchunify.ai/...
SEARCHUNIFY_COOKIE=...
SEARCHUNIFY_RESULTS_PER_PAGE=10
```

Optional search/debug settings:

```env
KNOWLEDGE_RESULT_LIMIT=5
KNOWLEDGE_CACHE_TTL_S=180
KNOWLEDGE_BACKEND_TIMEOUT_S=8
KNOWLEDGE_BACKEND_SSL_INSECURE=true
DEMO_LOOKUP_QUERY=qualys vulnerability findings are not updating
DEMO_LOOKUP_PRODUCT_AREA=vulnerability management detection response
LOG_LEVEL=info
```

## Local development

```sh
cd aws-voice
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Open:

```sh
http://127.0.0.1:3300/
```

## Docker

```sh
cd aws-voice
docker compose up -d --build --force-recreate
```

The compose file mounts `main.py`, `static/`, `.env`, and `README.md` into the container for fast iteration.

## Demo checks

Readiness:

```sh
curl http://127.0.0.1:3300/health
curl "http://127.0.0.1:3300/demo-readiness?probe_search=true"
```

Direct SearchUnify probe:

```sh
curl "http://127.0.0.1:3300/demo-search?query=vulnerability%20findings%20not%20updating&product_area=vulnerability%20management%20detection%20response"
```

## SearchUnify helper

If you copied a SearchUnify request from your browser, you can still import it into `.env` with:

```sh
pbpaste | python3 scripts/import_searchunify_curl.py
```

Or:

```sh
python3 scripts/import_searchunify_curl.py --input-file /path/to/searchunify-curl.txt
```

## Reverse proxy example

The included Nginx config keeps the app mounted internally at `/` and publishes it externally at `/socket/invoke/`.

That means the UI and API become available at paths like:

- `https://your-domain.example/socket/invoke/`
- `https://your-domain.example/socket/invoke/health`
- `https://your-domain.example/socket/invoke/api/realtime-config`
- `https://your-domain.example/socket/invoke/api/realtime-call`

## Production note

The long-lived OpenAI API key no longer reaches the browser. If you take this beyond demo usage, add authentication, rate limiting, and origin controls around `/api/realtime-call`, and consider moving further toward OpenAI short-lived session credentials if you need broader untrusted-client access.
