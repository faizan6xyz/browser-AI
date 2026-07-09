import json
import os
import glob
import re
import time
import requests
from openai import OpenAI
import threading
import shutil
import random
from dotenv import load_dotenv

load_dotenv()
API_key = os.getenv("API_key")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=API_key 
)
NIM_MODEL = "meta/llama-3.1-8b-instruct"
MCP_BASE = "http://localhost:3000/mcp"
MAX_NAV_STEPS = 3 

def extract_snapshot_path(text: str) -> str | None:
    match = re.search(r"\[Snapshot\]\(([^)]+)\)", text)
    return match.group(1) if match else None
matches = []
def find_and_read_snapshot_file(filename: str) -> str:
    matches.clear()
    current_dir = os.getcwd()
    while True:
        candidate = os.path.join(current_dir, ".playwright-mcp", filename)
        if os.path.exists(candidate):
            time.sleep(0.2)
            with open(candidate, "r", encoding="utf-8") as f:
                x = f.read()
                lines = [line.strip() for line in x if line.strip()]
                for i, line in enumerate(lines, 1):
                    if isinstance(line, str) and ("[cursor=pointer]" in line) :
                        matches.append(line)
                return  ", ".join(matches) 
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
    return ""

def find_and_read_latest_snapshot() -> str:
    current_dir = os.getcwd()
    latest_file, latest_mtime = None, 0
    while True:
        pattern = os.path.join(current_dir, ".playwright-mcp", "page-*.yml")
        for f in glob.glob(pattern):
            mtime = os.path.getmtime(f)
            if mtime > latest_mtime:
                latest_mtime, latest_file = mtime, f
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
    if latest_file:
        print(f"    [found snapshot file: {latest_file}]")
        time.sleep(0.2)
        with open(latest_file, "r", encoding="utf-8") as f:
            return f.read()
    return ""

class MCPClient:
    def __init__(self, base_url: str = MCP_BASE):
        self.base_url = base_url
        self._req_id = 0
        self._session_id = None
        self._tools = []
        self._keepalive_thread = None
        self._stop_keepalive = threading.Event()
        self._lock = threading.Lock()

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
            if params:
                payload["params"] = params
            resp = self._do_post(payload)
            if resp.status_code == 404:
                print(f"[MCP] 404 body: {resp.text[:300]!r}")
                print("[MCP] 404 — reconnecting...")
                self._session_id = None
                self._handshake()
                resp = self._do_post(payload)
            resp.raise_for_status()
            if "mcp-session-id" in resp.headers:
                self._session_id = resp.headers["mcp-session-id"]
            return self._parse_sse(resp.text)
    
    def _keepalive_loop(self):
        """Send periodic pings to prevent session timeout"""
        while not self._stop_keepalive.is_set():
            try:
                self._rpc("ping", {})
            except Exception:
                pass
            self._stop_keepalive.wait(timeout=15)
    
    def start(self):
        self._handshake()
        self._stop_keepalive.clear()
        self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._keepalive_thread.start()
        print("[MCP] Handshake complete. Keepalive started.")
    
    def stop(self):
        self._stop_keepalive.set()
        if self._keepalive_thread:
            self._keepalive_thread.join(timeout=5)
        print("[MCP] Done.")

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    def _parse_sse(self, text: str) -> dict:
        results = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
                if "error" in data:
                    raise RuntimeError(f"MCP error: {data['error']}")
                r = data.get("result", {})
                if r:
                    results.append(r)
            except json.JSONDecodeError:
                continue
        merged = {}
        for r in results:
            merged.update(r)
        return merged

    def _do_post(self, payload: dict) -> requests.Response:
        return requests.post(self.base_url, json=payload,
                              headers=self._headers(), timeout=60)

    def _handshake(self):
        payload = {
            "jsonrpc": "2.0", "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nim-nav-agent", "version": "1.0"},
            },
        }
        resp = self._do_post(payload)
        resp.raise_for_status()
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        self._do_post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        print(f"[MCP] Session: {self._session_id}")
    
    def _coerce_args(self, arguments: dict, tool_name: str) -> dict:
        if tool_name == "browser_snapshot":
            arguments.pop("filename", None)
        schema = next((t["function"]["parameters"] for t in self._tools
                        if t["function"]["name"] == tool_name), {})
        props = schema.get("properties", {})
        coerced = {}
        for k, v in arguments.items():
            etype = props.get(k, {}).get("type")
            if etype == "boolean" and isinstance(v, str):
                coerced[k] = v.lower() == "true"
            elif etype == "number" and isinstance(v, str):
                coerced[k] = float(v)
            elif etype == "integer" and isinstance(v, str):
                coerced[k] = int(v)
            else:
                coerced[k] = v
        return coerced

    def list_tools(self) -> list[dict]:
        if self._tools:
            return self._tools
        result = self._rpc("tools/list")
        allowed = {
            "browser_navigate", "browser_snapshot", "browser_type",
            "browser_click", "browser_press_key", "browser_wait_for",
            "browser_scroll", "browser_navigate_back",
        }
        raw = [t for t in result.get("tools", []) if t["name"] in allowed]
        self._tools = [
            {"type": "function", "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            }}
            for t in raw
        ]
        print(f"[MCP] {len(self._tools)} tools exposed: "
              f"{[t['function']['name'] for t in self._tools]}")
        return self._tools

    def call_tool(self, name: str, arguments: dict) -> str:
        arguments = self._coerce_args(arguments, name)
        print(f"    → {name}({json.dumps(arguments)[:150]})")
        for attempt in range(3):
            try:
                result = self._rpc("tools/call", {"name": name, "arguments": arguments})
                return self._process_result(name, result)
            except Exception as e:
                if "404" in str(e) or "Session not found" in str(e):
                    print(f"    [WARN] Session lost (Attempt {attempt+1}). Reconnecting...")
                    self._session_id = None
                    self._handshake()
                    time.sleep(2)
                    continue
                else:
                    return f"### Error\n{str(e)}"
        return "### Error\nFailed after multiple retries."

    def _process_result(self, name: str, result: dict) -> str:
        content = result.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(c["text"])
            elif c.get("type") == "resource" and "resource" in c:
                res_text = c["resource"].get("text", "")
                if res_text:
                    parts.append(res_text)
        text = "\n".join(parts) if parts else ""

        if name == "browser_snapshot":
            if text and len(text) > 20 and not text.startswith("### Snapshot"):
                return text
            if text:
                path = extract_snapshot_path(text)
                if path:
                    file_content = find_and_read_snapshot_file(os.path.basename(path))
                    if file_content:
                        return file_content
            return find_and_read_latest_snapshot() or "Snapshot empty."
        return text if text else "OK"

# Updated Prompt: Removed 'type_search' from allowed actions
NAV_PLANNER_PROMPT = """You are a browser navigation planner. You decide the SINGLE next action to move toward the user's goal. You do not execute anything yourself — you only output a decision as JSON.

GOAL: {goal}

You will be shown the current page's accessibility snapshot (elements, refs, text, URL).

## AVAILABLE ACTIONS (choose exactly one)
- "click": click an element. Requires "ref" — the EXACT ref string from the snapshot (e.g. "e42"). Never invent a ref that isn't in the snapshot.
- "navigate": go to a specific URL. Requires "url" — a full https:// URL. Only use a URL you were given or that you saw in the snapshot. Never guess one.
- "done": the goal is already achieved based on the current snapshot, OR it cannot be achieved with the actions available. Requires "success": true or false.

## RULES
1. Output ONLY a single JSON object, nothing else — no markdown fences, no explanation outside the JSON.
2. Only use a "ref" that appears verbatim in the snapshot you were shown. Never fabricate one.
3. If the snapshot shows a CAPTCHA, "verify you are human", a login wall, or a file-download prompt, output {{"action": "done", "success": false, "reason": "blocked: <short reason>"}}.
4. If you are unsure what's on the page or no clear next step is visible, prefer "navigate" only if you have a known URL; otherwise output "done" with success false and explain why in "reason".
5. Always include a short "reason" field explaining the choice.
6. Do not repeat an identical action you have already taken if the page did not change — choose "done" with success false instead.
7. check for the whole page not just the main content area , if the element on side bar or any other palce than main content area then click it 
8. for click choose the ref where cursor=pointer is there

## OUTPUT FORMAT (strict)
{{"action": "<click|navigate|done>", "ref": "<only for click>", "url": "<only for navigate>", "success": <only for done, true/false>, "reason": "<short reason>"}}

## EXAMPLES

Goal: "Find the pricing page on example.com"
Snapshot shows a nav link "Pricing" with ref "e14":
{{"action": "click", "ref": "e14", "reason": "Pricing link found in nav bar"}}

Goal: "Go to the trash/bin folder"
Snapshot shows only the homepage with no bin link visible, but URL pattern is known:
{{"action": "navigate", "url": "https://drive.google.com/drive/trash", "reason": "Bin link not visible, navigating directly to known trash URL"}}

Snapshot shows a CAPTCHA challenge:
{{"action": "done", "success": false, "reason": "blocked: CAPTCHA detected"}}

Goal achieved — main content area shows the pricing table:
{{"action": "done", "success": true, "reason": "Pricing table visible in main content area"}}

Now look at the snapshot you're given and output your single JSON decision.
"""

def plan_navigation_step(goal: str, snapshot: str) -> dict:
    try:
        response = client.chat.completions.create(
            model=NIM_MODEL,
            messages=[
                {"role": "system", "content": NAV_PLANNER_PROMPT.format(goal=goal)},
                {"role": "user", "content": snapshot[:15000]},
            ],
            max_tokens=200,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
        return json.loads(raw)
    except Exception as e:
        print(f"    [ERROR] Planning failed: {e}")
        return {"action": "done", "success": False}

GOAL_CHECK_PROMPT = """You are an intelligent verification agent. 
Your task is to determine if the user has ACTUALLY ARRIVED at the destination page they requested.

User Goal: "{goal}"
Current Page Snapshot: 
{snapshot}

CRITICAL VERIFICATION RULES:

1. SIDEBAR vs. MAIN CONTENT (THE "GOOGLE DRIVE" RULE):
   - Many apps (like Google Drive, Gmail, Outlook) have a permanent sidebar with links (e.g., "My Drive", "Bin", "Starred").
   - **CRITICAL:** Seeing "Bin" in the sidebar/menu does NOT mean you are in the Bin. It just means the link exists.
   - You are ONLY in the Bin if the **MAIN CONTENT AREA** (the large central part of the screen) shows deleted files, a "Empty Bin" button, or a heading that says "Bin" or "Trash".
   - If the Main Content shows your regular files/folders, you are still on "My Drive", even if "Bin" is highlighted in the sidebar.

2. URL PATH VERIFICATION:
   - Check the URL in the snapshot.
   - If Goal is "Bin": URL should contain "/trash", "/bin", or "/deleted".
   - If URL is still "/my-drive" or "/drive/u/0/", you are NOT in the Bin.

3. CONTENT VS. LINKS:
   - If the goal is to "open" or "go to" a section, you must see the CONTENT of that section.
   - Seeing a LINK or BUTTON that leads to the goal is NOT success.

4. HOMEPAGE TRAP:
   - If the snapshot shows a general feed, "Home", "Trending", or a search bar as the main focus, you are likely still on the Homepage. Return success: false.

5. CONTENT VERIFICATION CHECKLIST:
   - "Open Email": Look for a Sender Name, Subject Line, and Body Text in the main area. 
     If these are present, you are NOT in the Inbox list anymore. You are in the email view.
   - "Inbox List": Look for a list of rows with checkboxes and short summaries.

DECISION PROCESS:
1. Look at the URL. Does it match the goal? (e.g., /trash for Bin)
2. Look at the Main Content Area (not the sidebar). What is displayed there?
3. If Main Content shows regular files/folders → FAIL (Still on My Drive).
4. If Main Content shows deleted items/empty state → SUCCESS.

Reply with ONLY a JSON object:
{{"success": true/false, "reason": "Explain strictly. Mention the URL path and what is in the MAIN CONTENT area. If you only see a sidebar link, say 'Only saw sidebar link, main content is still [X]'."}}
"""

def check_goal_completion(goal: str, snapshot: str) -> dict:
    content_snippet = snapshot[:8000] 
    
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": GOAL_CHECK_PROMPT},
            {"role": "user", "content": f"Goal: {goal}\n\nPage Content:\n{content_snippet}"},
        ],
        max_tokens=100,
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"success": False, "reason": "Failed to parse LLM response"}

def navi(url):
    mcp = MCPClient()
    mcp.start()
    mcp.list_tools()
    mcp.call_tool("browser_navigate", {"url": url})


def run_agent(goal: str, start_url: str) -> str:
    mcp = MCPClient()
    mcp.start()
    mcp.list_tools()
    print(f"\nGoal : {goal}")
    print(f"URL  : {start_url}")
    print("=" * 60)
    
    current_url = start_url
    last_action_signature = "" 
    
    
    for step in range(1, MAX_NAV_STEPS + 1):
        print(f"\n--- Step {step}: Planning ---")
        
        # 1. Get Current State
        snapshot = mcp.call_tool("browser_snapshot", {})
        if not snapshot or snapshot == "Snapshot empty.":
            snapshot = find_and_read_latest_snapshot()
            
        if not snapshot:
            print("STUCK: Could not get snapshot.")
            break
            
        # Update current_url from snapshot if possible (simple regex extraction)
        url_match = re.search(r"Page URL:\s*(https?://[^\s]+)", snapshot)
        if url_match:
            current_url = url_match.group(1)
            print(f"  [Current URL]: {current_url}")

        # 2. Check if we are already done (BEFORE planning next move)
        status = check_goal_completion(goal, snapshot)
        print(f"  [LLM Status]: Success={status.get('success')} | Reason: {status.get('reason', 'Unknown')}")
        
        # --- SAFETY NET: Prevent "Link Confusion" ---
        is_success = status.get("success", False)
        if is_success:
            reason_lower = status.get("reason", "").lower()
            if "link" in reason_lower and not any(word in reason_lower for word in ["heading", "list", "content", "feed", "video"]):
                print("  [SAFETY OVERRIDE] LLM confused a sidebar link with the destination page. Ignoring success.")
                is_success = False
                
        if is_success:
            print(f"\n{'='*60}\nGOAL ACHIEVED: {status['reason']}\n{'='*60}")
            break
            
        # 3. Plan Next Move
        plan = plan_navigation_step(goal, snapshot)
        action = plan.get("action")
        
        # Detect Loop
        current_sig = f"{action}_{plan.get('ref', '')}_{plan.get('query', '')}_{plan.get('url', '')}"
        if current_sig == last_action_signature:
            print("  [LOOP DETECTED] Agent is repeating the same action. Stopping.")
            break
        last_action_signature = current_sig
        
        print(f"  [Plan]: {action} - {plan.get('reason', '')}")
        
        if action == "click":
            ref = plan.get("ref")
            if ref:
                mcp.call_tool("browser_click", {"element": "target", "target": ref})
                mcp.call_tool("browser_wait_for", {"time": 1})
                
                print(f"    → Pressing Enter to open selected item")
                mcp.call_tool("browser_press_key", {"key": "Enter"})
                mcp.call_tool("browser_wait_for", {"time": 3})
                break 
            else:
                print("  [Error] Plan said click but no ref provided.")         
        elif action == "navigate":
            url = plan.get("url")
            if url:
                current_url = url # Optimistically update URL
                mcp.call_tool("browser_navigate", {"url": url})
                mcp.call_tool("browser_wait_for", {"time": 5})
                break 
                
        elif action == "done":
            print(f"  [Agent decided]: Done. Success: {plan.get('success')}")
            break
        else:
            print(f"  [Error] Unknown action: {action}")
            break
    else:
        print("\nMax steps reached. Goal may not be achieved.")
    mcp.stop()
    return current_url
if __name__ == "__main__":
    goal = input("Enter your goal : ").strip()
    start_url = input("Starting URL    : ").strip()
    
    final_url = run_agent(goal, start_url)
    print(f"\n[FINAL] Agent finished on URL: {final_url}")