# `MCPClient` Class — Method-by-Method Explanation

This document walks through each method in the `MCPClient` class, which implements a resilient JSON-RPC client for talking to an MCP (Model Context Protocol) server — in this case, one exposing Playwright browser-automation tools over CDP.

---

## `__init__`
Sets up client state: base URL, a request-ID counter, current session ID, cached tool list, a keepalive thread handle, a `threading.Event` to signal the keepalive loop to stop, and a lock to serialize RPC calls (since multiple threads could call `_rpc` concurrently).

## `_rpc(method, params)`
The core JSON-RPC 2.0 request sender. Under the lock, it builds a payload with an auto-incrementing ID, POSTs it, and — critically — if the server returns 404 (session expired/not found), it clears the session ID, re-handshakes, and retries the *same* payload once. It also captures the `mcp-session-id` header if present, and parses the SSE response body into a dict.

## `_keepalive_loop`
Runs in a background thread, sending a `ping` RPC every 15 seconds until `_stop_keepalive` is set. Swallows exceptions silently (ping failures shouldn't crash the loop) — this is what prevents the MCP server from timing out your session between agent actions.

## `start()`
Does the initial handshake, then spins up and starts the keepalive thread as a daemon (so it won't block process exit).

## `stop()`
Signals the keepalive thread to stop and joins it (with a 5s timeout so shutdown doesn't hang).

## `_next_id()`
Simple incrementing counter for JSON-RPC request IDs.

## `_headers()`
Builds request headers — always sends `Content-Type` and an `Accept` header that allows either plain JSON or SSE streams (MCP servers can respond either way), and includes `mcp-session-id` if a session is active.

## `_parse_sse(text)`
Parses a Server-Sent-Events response body. It splits into lines, pulls out `data:` lines, JSON-decodes each payload, raises on any embedded `"error"` field, and collects the `"result"` objects. Multiple result chunks get merged into one dict via `.update()` — note this means later chunks silently overwrite keys from earlier ones if they collide.

## `_do_post(payload)`
Thin wrapper around `requests.post` with a 30s timeout — just centralizes how requests are actually sent so `_rpc` and `_handshake` don't duplicate this logic.

## `_handshake()`
Performs the MCP `initialize` handshake: sends protocol version, empty capabilities, and client info; captures the returned session ID; then sends the required `notifications/initialized` notification to complete the handshake per MCP protocol.

## `_coerce_args(arguments, tool_name)`
Cleans up tool arguments before calling a tool:
- Special-cases `browser_snapshot` to strip out a `filename` arg (probably because the model sometimes hallucinates that param).
- For everything else, looks up the tool's JSON schema and coerces string values to `bool`/`float`/`int` based on the declared type — this compensates for LLMs generating stringified numbers/booleans in tool-call JSON instead of native types.

## `list_tools()`
Fetches the tool list from the server once (`tools/list`), caches it, and filters down to a fixed allow-list of browser-automation tools (navigate, snapshot, type, click, etc.) — presumably to keep the LLM's action space small and reliable rather than exposing every tool the MCP server has. Converts them into OpenAI-style function-calling schema (`{"type": "function", "function": {...}}`).

## `call_tool(name, arguments)`
The main entry point for executing a tool call:
1. Coerces argument types via `_coerce_args`.
2. Logs the call.
3. Retries up to 3 times: calls `tools/call` via `_rpc`, and on failure, checks if it's a session-related error (404/"Session not found") — if so, resets the session, re-handshakes, waits 2s, and retries. Other errors return immediately as a formatted error string instead of retrying.

## `_process_result(name, result)`
Extracts usable text from a tool result's `content` array, handling both `"text"` blocks and `"resource"` blocks (pulling `resource.text`). Has special handling for `browser_snapshot`:
- If the text already looks like a real snapshot (not a placeholder like `"### Snapshot"` and >20 chars), return it directly.
- Otherwise, try to extract a file path from the text, read that snapshot file from disk, and track the filename in `snapshot_filenames` (with `[-1]` being "latest" — this is presumably how other code retrieves "the most recent DOM snapshot").
- Falls back to `find_and_read_latest_snapshot()` if nothing else worked.
- For all other tools, just returns the joined text or `"OK"` if empty.

---

## Overall Pattern

This is a resilient MCP client built specifically for a Playwright-over-CDP browser agent, where the two recurring pain points it's defending against are:

1. **Session expiry/loss (404s)** — handled by transparent reconnect-and-retry in both `_rpc` and `call_tool`.
2. **Snapshot responses coming back as file references** rather than inline content, requiring a read-from-disk fallback chain.

### Worth flagging
`_rpc`'s automatic re-handshake-and-retry on 404, *plus* `call_tool`'s own 3-attempt retry loop with its own reconnect logic, means a persistent session failure could trigger reconnect attempts at two different layers. Not necessarily a bug, but worth being aware of if you're debugging duplicate handshake logs.
