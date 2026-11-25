# LLM Chatbot — Key Failover & Response Caching

## 1. Live URLs

**Not deployed yet.** No live frontend/backend URL has been verified, so none is claimed here. Local build, backend tests and the frontend production build were verified; deployment is blocked only by the lack of real API keys and hosting credentials in this environment.

Planned deployment (simplest option that meets the requirements):

- Backend: Render Web Service (`Dockerfile` from `backend/`), persistent disk mounted at `/data`.
- Frontend: Vercel/Netlify static site built from `frontend/` with `VITE_API_URL` set to the live backend URL.
- Both URLs are public, no login required.

Exact remaining steps are listed at the end of section 2.

## 2. Run locally: with Docker and without

### With Docker (required path)

```bash
cp .env.example .env
# Edit .env and put at least two real API keys in LLM_API_KEYS.
make up
```

- Backend: http://localhost:8000
- Frontend: http://localhost:3000
- SQLite file: `/data/app.db` inside the `data` named volume, so it survives `make down` / restarts.
- `make down` stops and removes the containers (the volume is kept).
- `make test` runs the backend pytest suite.

Note: Docker is not installed in the environment used to prepare this submission, so `make up` / `make down` could not be executed here. The Compose file, both multi-stage Dockerfiles and the Makefile are complete and ready to run.

### Without Docker

Backend (from `backend/`):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
set DATABASE_URL=sqlite:///./data/app.db
set LLM_API_KEYS=key_one,key_two
set ALLOWED_ORIGINS=http://localhost:3000
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend (from `frontend/`, in a second terminal):

```bash
npm install
set VITE_API_URL=http://localhost:8000
npm run dev
```

Then open http://localhost:3000.

### Deployment steps that remain

1. Get two real API keys for the configured model (Google AI Studio keys for `gemini/gemini-2.0-flash` work with LiteLLM).
2. Create a Render Web Service from this repository, root directory `backend`, Docker runtime. Set env vars `LLM_API_KEYS`, `LLM_MODEL`, `DATABASE_URL=sqlite:////data/app.db`, `ALLOWED_ORIGINS=<live frontend URL>`, `ENABLE_FAILURE_SIMULATION=true`. Attach a persistent disk mounted at `/data`.
3. Confirm `GET https://<backend>/health` returns `200` with `keys_configured: 2`.
4. Deploy `frontend/` on Vercel/Netlify with `VITE_API_URL=https://<backend>`; redeploy the backend with `ALLOWED_ORIGINS` set to the exact live frontend origin (comma-separated if there are several).
5. Test the live UI plus the curl commands in section 4 against the live backend URL.

## 3. Design decisions: key fallback, caching, SQLite session storage

**Key fallback.** `LLM_API_KEYS` is split into `(key_1, key)`, `(key_2, key)`, … in order. For every chat request the backend loops over the keys in order and calls `litellm.completion(..., api_key=...)` with the current key. Any provider exception (429 rate limit, quota error, 5xx, or connection error) is caught and the next key is tried; `fallback_attempts` counts the keys that failed before success. If all keys fail, the endpoint returns `503 {"detail": "all providers unavailable"}` and stores nothing. `X-Simulate-Failure` is parsed into a per-request key→status map; the same loop raises the same exception class before the network call, so simulated and real failures take an identical path. Simulation is ignored unless `ENABLE_FAILURE_SIMULATION=true`, never changes global LiteLLM state, and simulated requests bypass the cache so they really reach the provider.

**Caching.** LiteLLM's own in-memory cache is enabled with `litellm.Cache(type="local")`; there is no separate cache implementation. Every completion is passed an explicit `cache_key` derived from a SHA-256 of `{"model": ..., "messages": [...]}` where the message list is the system prompt + all stored history + the new user message. On a cache hit LiteLLM returns the stored response and sets its `cache_hit` hidden param; the backend then reports `LIVE_INFERENCE` or `LLM_CACHE`, sets `key_id=null` and `fallback_attempts=0`, reuses the stored token usage, and measures its own latency around the call.

**SQLite session storage.** A plain `sqlite3` database is created automatically on startup using the schema from the assignment, plus an index on `(session_id, id)` and a tiny `sessions` table so an optional `system_prompt` can persist for a session without ever appearing in message history. Each turn writes the user message and assistant message (with metadata JSON) in one transaction with ISO-8601 UTC timestamps. The client sends only the new message; the backend reconstructs the prompt from SQLite. Failed requests never reach the insert path.

## 4. Verification: how to see failover, cache hits and per-message token usage

Replace `http://localhost:8000` with the live backend URL when testing the deployment.

Health:

```bash
curl -s http://localhost:8000/health
# {"status":"ok","keys_configured":2,"cache_enabled":true}
```

Chat (a live answer with per-request metadata):

```bash
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"s-7f3a","message":"What is the capital of France?"}'
```

Session history (oldest first, no system prompt):

```bash
curl -s http://localhost:8000/sessions/s-7f3a/messages
```

Cache demonstration — the same first message in two **new** sessions. The second response must say `LLM_CACHE`, be identical, have `key_id: null` and be faster:

```bash
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"cache-session-a","message":"Explain caching in one sentence"}'

curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"cache-session-b","message":"Explain caching in one sentence"}'
```

Failover — key_1 fails with 429, key_2 answers (`fallback_attempts` should be 1):

```bash
curl -s -i -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"failover-demo","message":"Give me a unique failover answer"}'
```

All keys failing — expect `503` and no stored messages:

```bash
curl -s -i -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"all-fail-demo","message":"This should fail"}'

curl -s -i http://localhost:8000/sessions/all-fail-demo/messages   # 404
```

Automated verification: `make test` (28 pytest cases covering validation, memory, sessions, SQLite persistence, history, cache accuracy/tokens/latency, failover, all-key failure, simulation switch and provider error classes).

## 5. Setup Used: your editor and AI tools

- Development environment: OpenCode coding agent (Big Pickle model) running in PowerShell on Windows; files edited with OpenCode's file tools.
- AI assistance: OpenCode agent for implementation, test design and documentation. No other code assistants were used.
- Libraries: FastAPI + Uvicorn, LiteLLM (completion, built-in local cache and exception hierarchy), stdlib `sqlite3`, React + Vite, pytest + FastAPI TestClient.
- No real API keys or hosting credentials were available in this environment; placeholders were used everywhere.

## 6. Bonus features (if any): what you added beyond the requirements and why

- Small `sessions` table: needed to make the optional `system_prompt` actually persist for a session, as the PDF requires that it override the default prompt "for this session".
- Subtle CSS fade-in/typing animations in the chat UI: keeps the required loading state obvious without adding any unrequested features.
- An extra `make test` target and one integration test that exercises LiteLLM's real cache via its `mock_response` hook, so cache detection is verified without spending real API credits.
- A `session_chip` in the header displays the generated session ID, which makes manual verification of cache and history tests easier.
