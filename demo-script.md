# Demo video script (2–3 minutes)

Use the deployed frontend and backend URLs from README section 1. Keep `ENABLE_FAILURE_SIMULATION=true` on the backend.

| Time | Action | What to say / show |
| --- | --- | --- |
| 0:00–0:15 | Open the app, point at the chat UI | "This is a React + Vite chat UI. A new session ID is generated on each page load and shown in the header. Only the new message is sent; the backend keeps the history in SQLite." |
| 0:15–0:40 | Type "What is the capital of France?" and press Enter | "Here is a live answer. Under every AI reply you can see the source, model, latency, and input/output tokens for this request only." |
| 0:40–1:00 | Send "And what country is it in?" in the same session | "Multi-turn memory: the backend included the earlier user and assistant messages when building this request, using only the new message from the client." |
| 1:00–1:25 | Open a new browser tab (new session) and send the exact first message again | "Same model, same full message list, new session — LiteLLM's built-in cache returns `LLM_CACHE`, an identical reply, `key_id: null`, `fallback_attempts: 0`, and lower latency." |
| 1:25–1:50 | `curl -H 'X-Simulate-Failure: key_1=429'` POST /chat with a unique message | "Now key_1 is forced to return HTTP 429 for this request only. The response is still a real AI answer from key_2, with `fallback_attempts: 1`." |
| 1:50–2:10 | `curl -H 'X-Simulate-Failure: *=429'` POST /chat, then GET the session's history | "When every key fails, the API returns 503 with `all providers unavailable`, and the failed turn is not stored — history returns 404." |
| 2:10–2:25 | Browser/curl `GET /health`, then `GET /sessions/{id}/messages` for a successful session | "Health reports two configured keys and caching enabled. History is oldest first, includes both roles and the assistant metadata, and never includes the system prompt." |
| 2:25–2:40 | Recap | "Everything runs locally with `make up` on ports 8000 and 3000, with a Docker volume at `/data` preserving SQLite across restarts." |
