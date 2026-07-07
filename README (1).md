# browser-AI

An LLM-driven browser automation agent. It plans one step at a time toward a natural-language goal, then executes that step in a real Chrome browser via the Playwright MCP server over the Chrome DevTools Protocol (CDP).

Instead of hard-coded scripts, the agent looks at the current page state, decides the single next action (navigate, click, type, search, scroll, extract, or finish), and hands that action off to a dedicated executor module. Steps repeat until the goal is satisfied or the run is stopped.

## How it works

1. **`Workflow.py`** is the orchestrator. It sends the goal + current page state + step history to an LLM (via the NVIDIA NIM API) and asks for exactly one next step back as JSON: `{"action": ..., "target": ..., "value": ...}`.
2. That JSON step is converted into a human-readable instruction (e.g. `"click e14"`, `"search 'wireless headphones'"`).
3. Based on the action type, `Workflow.py` dispatches to the matching executor:
   - **`Navigation.py`** – navigate to a URL, click an element, or finish the run
   - **`Searching.py`** – fill and submit search boxes
   - **`typeing.py`** – type text into a given element
   - **`Extract_text.py`** – pull the current page's content out as markdown
4. Every "target" the model outputs for click/type must be a `ref` that appears verbatim in the current page snapshot — the prompt is written to force this grounding and fall back to `navigate` if no matching ref exists, instead of letting the model hallucinate a selector.
5. The loop continues (up to `max_steps`) until the model returns `finish`.

## Project structure

```
browser-AI/
├── Workflow.py          # Orchestrator: LLM planning loop + step dispatch
├── Navigation.py        # navigate / click / finish execution over MCP
├── Searching.py         # search-box execution
├── typeing.py           # type-into-element execution
├── Extract_text.py      # page -> markdown extraction
├── Formfilling.py       # form-filling (in progress, not yet working)
├── single_step.py        # standalone single-step runner / debugging harness
├── HTTP_workflow.txt     # notes on the MCP HTTP call flow
├── explain.txt           # design notes + known 404/session bug write-up
├── File management/      # related file-manager agent
└── Research Agent/        # related research agent
```

## Requirements

- Python 3.10+
- Google Chrome, launched with remote debugging enabled (default setup uses port `9222`)
- A running [Playwright MCP](https://github.com/microsoft/playwright-mcp) server connected to that Chrome instance via `--cdp-endpoint`
- An NVIDIA NIM API key (used to call the planning model, e.g. `nvidia/llama-3.1-nemotron-nano-8b-v1`)

Python packages:
```
openai
python-dotenv
```
*(plus whatever MCP client library `Navigation.py` / `Searching.py` / `typeing.py` use to talk to the MCP server — add it here once pinned)*

## Setup

1. Launch Chrome with a remote debugging port and a dedicated profile:
   ```bash
   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome-debug-profile"
   ```
2. Start the Playwright MCP server pointed at that CDP endpoint:
   ```bash
   npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
   ```
3. Create a `.env` file in the project root:
   ```
   API_key=your_nvidia_nim_api_key
   ```
4. Install Python dependencies:
   ```bash
   pip install openai python-dotenv
   ```

## Usage

```bash
python Workflow.py
```

You'll be prompted for a goal in plain English:

```
Whats your goal : find the cheapest flight from Delhi to Mumbai next Friday
```

The agent will print each planned step, its human-readable form, and then execute it in the connected Chrome window.

## Known issues

- **Recurring 404 on tool calls after a successful handshake.** The MCP session appears to establish (`initialize` succeeds) but the very first real tool call afterward can 404. Suspected causes, in order of likelihood:
  1. `--cdp-endpoint` mode not reliably persisting session state across separate HTTP requests.
  2. A stale/zombie MCP server process from a previous run still bound to the port, so `initialize` and the follow-up `tools/call` land on different processes.
  3. A race between the `initialize` response and the `notifications/initialized` call not capturing a rotated session ID.
  4. An aggressively short server-side session timeout (less likely, since the 404 shows up almost immediately).
- **Form filling isn't wired up yet** — `Formfilling.py` exists but isn't integrated into the main workflow loop.

## Roadmap

- Fix MCP session persistence / reconnect handling
- Integrate `Formfilling.py` into the main loop
- Add retry/backoff around MCP tool calls
- Add automated logging of full step + state history per run

## Related agents in this repo

- **`Research Agent/`** – a NIM-backed research agent built on the same agentic-loop pattern
- **`File management/`** – a file-manager agent, also NIM-backed

## License

Add a license of your choice (MIT recommended for personal/portfolio projects).
