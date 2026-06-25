# Research Agent

An autonomous, tool-using research agent built on **NVIDIA NIM** (`meta/llama-3.1-8b-instruct`) that researches a topic across multiple search rounds and produces a long-form, structured Markdown report — which then gets saved to disk and indexed into a vector DB for RAG retrieval.

It follows a **ReAct-style loop** (Reason → Act → Observe → repeat), but instead of relying on native OpenAI-style function calling, it uses a custom text protocol (`TOOL:` / `INPUT:` / `FINAL ANSWER:`) that the LLM is instructed to follow via the system prompt, which the script then parses manually.

---

## How it works

```
User query
   │
   ▼
[System Prompt: research strategy + report format]
   │
   ▼
┌─────────────────────────────────────────┐
│  Agent Loop (max 15 steps)               │
│                                           │
│  1. LLM call → reply                     │
│  2. parse_response(reply)                │
│       ├── "TOOL:"  → run tool, feed       │
│       │              result back as the   │
│       │              next user message    │
│       ├── "FINAL ANSWER:" → done, save    │
│       └── neither  → nudge: "Continue     │
│                       your research..."   │
└─────────────────────────────────────────┘
   │
   ▼
save_report() → writes .md to ../Data/
              → calls build_index() to embed it into the vector store
```

### Tools available to the agent

| Tool | Purpose | Backing implementation |
|---|---|---|
| `search_web(query, max_results)` | Quick broad search — used first | `Toolsusingduck.search_web` (DuckDuckGo) |
| `search_deep(query)` | Deeper search, more content per result | `Toolsusingduck.search_deep` |
| `search_news(query, max_results)` | Recent news only | `Toolsusingduck.search_news` |

The system prompt enforces a fixed research strategy: broad search → identify sub-topics → ≥3-4 deep searches per sub-topic → news search → cross-reference → only then write the final report (minimum 5-6 tool calls, 800+ word report).

### Report structure (enforced by prompt)

Overview → Background & Context → Key Findings → Deep Dive sections per sub-topic → Conflicting Views → Recent Developments → Key Takeaways → Sources.

---


**Python dependencies:** `openai`, `duckduckgo_search`

```bash
pip install openai duckduckgo_search --break-system-packages
```

---

## Usage

```bash
python research_agent.py
```

```
Enter the query for research (or 'exit' to quit): impact of GST on Indian SMEs
```

The agent will print each step (`--- Step N ---`), show which tool it's calling and with what query, then print the full final report and save it as `Data/impact_of_GST_on_Indian_SMEs_report.md` (filename = first 40 chars of the topic, spaces → underscores).

---

## Known issues / things worth fixing

1. **Hardcoded API key** — the NVIDIA NIM key is committed directly in the source (`client = OpenAI(api_key="nvapi-...")`). Same pattern flagged in the browser agent project — should move to `.env` + `config.py` and rotate the exposed key, since it's now visible in this file.
2. **Fragile text-based tool parsing** — `parse_response()` does brittle string-splitting on `"TOOL:"` / `"INPUT:"`. A model that adds preamble text before the tag, uses different casing, or wraps the JSON in markdown fences will silently fall into the `"unknown"` branch. Given you're running an 8B model (more prone to format drift than larger models), this is the most likely failure point — worth wrapping in stricter regex or switching to NIM's native function-calling/tool-use API if it's supported for this model.
3. **No JSON validation on tool input** — `json.loads(tool_input)` will throw on any malformed JSON the model emits; currently caught generically as `Tool error: {e}` and fed back to the model, which works but burns a step without diagnostic info printed to console.
4. **`max_steps=15` is a hard ceiling** — if the model is still searching at step 15, the function just returns `None` with no partial report saved. Given the prompt asks for 5-6+ searches before finalizing, a complex topic could realistically hit this ceiling — might be worth forcing a "wrap up now" instruction a few steps before the cap rather than failing silently.
5. **`search_count` is tracked but never used** to influence agent behavior (e.g., nudging toward `FINAL ANSWER:` after N searches) — currently it's just a console log.

---

## Quick extension ideas

- Swap the manual `TOOL:`/`INPUT:` protocol for NIM's structured tool-calling if available — removes the parsing fragility entirely.
- Add a step counter passed back into the user-facing message (e.g., `"You have used 8/15 steps"`) so the LLM self-regulates pacing.
- Persist `messages` history per topic so a research session can be resumed instead of restarted from scratch.
