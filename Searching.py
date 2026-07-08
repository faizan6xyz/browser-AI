import json
import os
import glob
import re
import requests
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
API_key = os.getenv("API_key")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=API_key 
)
NIM_MODEL    = "meta/llama-3.1-8b-instruct"
MCP_BASE     = "http://localhost:3000/mcp"

def extract_snapshot_path(text: str) -> str | None:
    match = re.search(r'\[Snapshot\]\(([^)]+)\)', text)
    if match:
        return match.group(1)
    return None

def find_and_read_snapshot_file(filename: str) -> str:
    current_dir = os.getcwd()
    while True:
        candidate = os.path.join(current_dir, ".playwright-mcp", filename)
        if os.path.exists(candidate):
            time.sleep(0.2)              # Wait briefly to ensure file is fully written
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
    return ""

def find_and_read_latest_snapshot() -> str:
    current_dir = os.getcwd()
    latest_file = None
    latest_mtime = 0
    while True:
        pattern = os.path.join(current_dir, ".playwright-mcp", "page-*.yml")
        files = glob.glob(pattern)
        for f in files:
            mtime = os.path.getmtime(f)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_file = f
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
    if latest_file:
        print(f"    [found snapshot file: {latest_file}]")
        time.sleep(0.2) # Ensure file write completion
        with open(latest_file, "r", encoding="utf-8") as f:
                x = f.readlines()
                lines = [line.strip() for line in x if line.strip()]
                for i, line in enumerate(lines, 1):
                    if "[cursor=pointer]" in line :
                        return line 
    return ""
QUERY_EXTRACT_PROMPT = """Extract just the search query from the user's goal.
Strip away phrases like "search for", "on youtube", "on google", site names, etc.
Reply with ONLY the search query text, nothing else.

Example:
Goal: "search python tutorials on youtube"
Reply: python tutorials

Goal: "find me research papers about transformers"
Reply: research papers about transformers
"""
def extract_query(goal: str) -> str:
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": QUERY_EXTRACT_PROMPT},
            {"role": "user", "content": goal},
        ],
        max_tokens=30,
        temperature=0,
    )
    return response.choices[0].message.content.strip().strip('"')

class MCPClient:
    def __init__(self, base_url: str = MCP_BASE):
        self.base_url    = base_url
        self._req_id     = 0
        self._session_id = None
        self._tools      = []

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
        if not results:
            return {}
        merged = {}
        for r in results:
            merged.update(r)
        return merged

    def _do_post(self, payload: dict) -> requests.Response:
        return requests.post(
            self.base_url, json=payload,
            headers=self._headers(), timeout=30
        )

    def _handshake(self):
        payload = {
            "jsonrpc": "2.0", "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nim-browser-agent", "version": "1.0"},
            }
        }
        resp = self._do_post(payload)
        resp.raise_for_status()
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self._do_post(notif)
        print(f"[MCP] Session: {self._session_id}")

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params:
            payload["params"] = params
        resp = self._do_post(payload)
        if resp.status_code == 404:
            print("[MCP] 404 — reconnecting...")
            self._session_id = None
            self._handshake()
            
            # OPTIONAL: Verify we are still on the right page after reconnect
            if method == "tools/call" and params.get("name") == "browser_snapshot":
                print("  [Verifying page state after reconnect...]")
                
            resp = self._do_post(payload)
        resp.raise_for_status()
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        return self._parse_sse(resp.text)

    def _coerce_args(self, arguments: dict, tool_name: str) -> dict:
        if tool_name == "browser_snapshot":
            arguments.pop("filename", None)
        schema = next(
            (t["function"]["parameters"] for t in self._tools
             if t["function"]["name"] == tool_name), {}
        )
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

    def start(self):
        self._handshake()
        print("[MCP] Handshake complete.")

    def stop(self):
        print("[MCP] Done.")

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
                "name":        t["name"],
                "description": t.get("description", ""),
                "parameters":  t.get("inputSchema", {"type": "object", "properties": {}}),
            }}
            for t in raw
        ]
        print(f"[MCP] {len(self._tools)} tools exposed to LLM: "
              f"{[t['function']['name'] for t in self._tools]}")
        return self._tools

    def call_tool(self, name: str, arguments: dict) -> str:
        arguments = self._coerce_args(arguments, name)
        print(f"    coerced: {json.dumps(arguments)[:200]}")
        try:
            result  = self._rpc("tools/call", {"name": name, "arguments": arguments})
        except Exception as e:
            print(f"    [RPC Error]: {e}")
            return f"### Error\n{str(e)}"
        
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
                    filename = os.path.basename(path)
                    file_content = find_and_read_snapshot_file(filename)
                    if file_content:
                        return file_content   
            return find_and_read_latest_snapshot() or "Snapshot empty."
        return text if text else "OK"

PICKER_PROMPT = """You are given an accessibility tree snapshot of a webpage.
Find the actual SEARCH INPUT field where a user types text. 
Look for elements with roles like 'combobox', 'textbox', 'searchbox', or 'input'.
DO NOT pick container elements like 'search', 'form', 'region', or 'generic'.

Reply with ONLY the ref value, nothing else. Example reply: e42
If you cannot find it, reply: NONE
"""
def pick_search_ref(snapshot: str) -> str | None:
    response = client.chat.completions.create(
        model    = NIM_MODEL,
        messages = [
            {"role": "system",  "content": PICKER_PROMPT},
            {"role": "user",    "content": snapshot[:15000]},
        ],
        max_tokens  = 10,
        temperature = 0,
    )
    ref = response.choices[0].message.content.strip().strip('"').strip("'")
    print(f"    [LLM picked ref]: {ref}")
    return None if ref.upper() == "NONE" else ref

CONFIRM_PROMPT = """You are given an accessibility tree snapshot of a webpage after a search.
Did the search succeed? Look for signs of success such as:
- A list of search results.
- The actual article/content page for the query.
Reply with one word: YES or NO
"""
def confirm_success(snapshot: str, query: str) -> bool:
    response = client.chat.completions.create(
        model    = NIM_MODEL,
        messages = [
            {"role": "system",  "content": CONFIRM_PROMPT},
            {"role": "user",    "content": f"Query was: {query}\n\nSnapshot:\n{snapshot[:8000]}"},
        ],
        max_tokens  = 5,
        temperature = 0,
    )
    ans = response.choices[0].message.content.strip().upper()
    print(f"    [LLM success check]: {ans}")
    return ans.startswith("Y")

def run_agent1(goal: str, start_url: str) -> str:
    mcp = MCPClient()
    mcp.start()
    mcp.list_tools()
    
    current_url = start_url
    print(f"\nGoal : {goal}")
    print(f"URL  : {start_url}")
    print("=" * 60)
    
    #  Step 2: Get Snapshot 
    print("\n--- Step 2: Snapshot ---")
    mcp.call_tool("browser_wait_for", {"time": 2})
    snapshot = mcp.call_tool("browser_snapshot", {})
    
    if not snapshot or snapshot == "Snapshot empty.":
        snapshot = find_and_read_latest_snapshot()
    if not snapshot:
        print("STUCK: Could not get page snapshot.")
        mcp.stop()
        return current_url
        
    # Extract URL from initial snapshot
    url_match = re.search(r"Page URL:\s*(https?://[^\s]+)", snapshot)
    if url_match:
        current_url = url_match.group(1)

    #  Step 3: Find search ref 
    print("\n--- Step 3: Find search ref ---")
    ref = pick_search_ref(snapshot)
    if not ref:
        print("Could not find search box. Trying '/' key...")
        mcp.call_tool("browser_press_key", {"key": "/"})
        mcp.call_tool("browser_wait_for", {"time": 1})
        snapshot = mcp.call_tool("browser_snapshot", {})
        ref = pick_search_ref(snapshot)
        
    if not ref:
        print("STUCK: Could not locate search input.")
        mcp.stop()
        return current_url
        
    query = extract_query(goal)
    print(f"  Query: {query!r}  →  ref: {ref}")
    
    #  Step 4: Type and submit 
    print("\n--- Step 4: Type and submit ---")
    def attempt_type(target_ref, query_text):
        return mcp.call_tool("browser_type", {
            "element": "search input",
            "target":  target_ref,
            "text":    query_text,
            "submit":  True,
            "slowly":  False,
        })

    type_result = attempt_type(ref, query)
    print(f"  ↩ {type_result[:200]}")
    
    # Error Recovery
    if "Error" in type_result or "404" in type_result:
        print(" Action failed. Re-snapshotting to recover...")
        mcp.call_tool("browser_wait_for", {"time": 2})
        snapshot = mcp.call_tool("browser_snapshot", {})
        if not snapshot: snapshot = find_and_read_latest_snapshot()
        if snapshot:
            new_ref = pick_search_ref(snapshot)
            if new_ref:
                print(f"  [Retrying with new ref: {new_ref}]")
                type_result = attempt_type(new_ref, query)
                print(f"  ↩ Retry: {type_result[:200]}")
                
    # IMPORTANT: Wait longer for search results to load
    print("  Waiting for search results to load...")
    mcp.call_tool("browser_wait_for", {"time": 5}) 
    
    # IMPORTANT: Scroll down to trigger loading of video results in the DOM
    print("  Scrolling down to ensure results are in snapshot...")
    mcp.call_tool("browser_press_key", {"key": "PageDown"})
    mcp.call_tool("browser_wait_for", {"time": 2})

    #  Step 5: Confirm results 
    print("\n--- Step 5: Confirm results ---")
    result_snapshot = mcp.call_tool("browser_snapshot", {})
    
    # Update URL from final snapshot
    url_match = re.search(r"Page URL:\s*(https?://[^\s]+)", result_snapshot)
    if url_match:
        current_url = url_match.group(1)
        
    # If snapshot is huge, we need to be smarter than just [:8000]
    snapshot_content = result_snapshot[:] 
    print(f"  [snapshot: {len(result_snapshot)} chars]")
    print(f"  preview:\n{result_snapshot[:600]}...")
    
    if confirm_success(snapshot_content, query):
        print(f"\n{'='*60}")
        print(f"GOAL ACHIEVED: Searched '{query}' successfully.")
        print(f"{'='*60}")
    else:
        print("\nResults unclear — check the browser window.")
        print("Hint: The search likely worked, but the LLM didn't see the results in the truncated snapshot.")
        
    mcp.stop()
    return current_url

if __name__ == "__main__":
    goal      = input("Enter your goal : ").strip()
    start_url = input("Starting URL    : ").strip()
    
    final_url = run_agent1(goal, start_url)
    print(f"\n[FINAL] Agent finished on URL: {final_url}")