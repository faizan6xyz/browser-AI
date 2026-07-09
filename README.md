# browser-AI

An LLM-driven browser automation agent. An 8B model (NVIDIA NIM — `nvidia/llama-3.1-nemotron-nano-8b-v1`) plans one step at a time toward a natural-language goal, and a set of dedicated executor scripts (via a Playwright MCP server) carry out that step — navigate, click, type, search, scroll, or extract content — until the goal is finished or blocked.

Rather than giving the LLM free-form tool calling, this project uses a **hardcoded step-executor pattern**: the planner outputs a single strict JSON action, a router dispatches it to the matching script, and the loop repeats with updated page state. This trades some flexibility for reliability, which matters a lot when the planner is a small 8B model.

## How it works

1. **`Workflow.py`** — the orchestrator. Feeds the goal, current page state, and history of previous steps to the planner LLM, gets back a single JSON action, converts it to a human-readable string, and routes it to the right executor. Loops until `finish` or `max_steps` is hit.
2. **Planner LLM** — constrained to output exactly one of 8 actions per turn: `navigate`, `click`, `type`, `search`, `scroll`, `extract_text`, `extract_files`, `finish`. Grounding rule: any `click`/`type` target must be a ref string that appears verbatim in the current accessibility-tree snapshot — if it doesn't, the planner is forced to `navigate` instead of hallucinating a target.
3. **Executors** (each talks to the browser through a Playwright MCP server):
   - `Navigation.py` — navigate / click / finish actions
   - `Searching.py` — search-box interactions
   - `typeing.py` — typing into form fields
   - `Extract_text.py` — extracts page content to Markdown
   - `Formfilling.py` — form filling (work in progress, not yet wired into the main loop)
4. **`single_step.py`** — a standalone harness for testing a single planner step / executor call in isolation, without running the full loop.

## Repo layout

```
Workflow.py           # orchestrator + planner prompt + step router
Navigation.py          # navigate / click / finish executor
Searching.py           # search executor
typeing.py             # type executor
Extract_text.py        # page -> markdown extraction
Formfilling.py          # form filling (WIP)
single_step.py          # single-step debug harness
HTTP_workflow.txt        # notes on the HTTP/SSE MCP transport setup
explain.txt              # architecture notes + known 404/session bugs
File management/         # separate agent: file ops with a Gradio UI
Research Agent/           # separate agent: ReAct-style web research agent
```

## Setup

```bash
git clone https://github.com/faizan6xyz/browser-AI.git
cd browser-AI
pip install openai python-dotenv
```

You'll also need a running **Playwright MCP server** (stdio, HTTP, or SSE transport — see `HTTP_workflow.txt` for the HTTP/SSE setup notes) that the executor scripts connect to for actual browser control.

Create a `.env` file:

```
API_key=your_nvidia_nim_api_key
```

## Usage

```bash
python Workflow.py
```

You'll be prompted for a goal (e.g. `find the cheapest flight from Delhi to Mumbai next Friday`). The agent will print each planned step, its human-readable translation, and execute it until it finishes or hits the step limit.

## Known issues

- **MCP session 404s**: the Playwright MCP session sometimes drops immediately after handshake, particularly when running in `--cdp-endpoint` mode (connecting to an already-running Chrome via remote debugging). This mode doesn't reliably persist session state across separate HTTP requests. See `explain.txt` for the full breakdown of suspected causes (stale server processes, session-ID rotation races, short server-side timeouts).
- **Form filling** isn't wired into the main loop yet.

## Sub-projects

- **`File management/`** — a separate file-management agent with a Gradio UI and per-action confirmation before any file operation runs.
- **`Research Agent/`** — a ReAct-style research agent using DuckDuckGo search + NVIDIA NIM for multi-step web research.

## License

No license specified yet — all rights reserved by default until one is added.
