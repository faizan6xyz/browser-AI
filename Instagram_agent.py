import json
import os
import glob
import re
import time
import requests
from openai import OpenAI
import threading
from dotenv import load_dotenv
import pandas as pd
load_dotenv()
API_key = os.getenv("API_key")
# for multiple Mail sending
# email = pd.read_csv("Email.csv")   
# mail_recipt = email["recipt"] 
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=API_key
)
NIM_MODEL = "meta/llama-3.1-8b-instruct"
MCP_BASE = "http://localhost:3000/mcp"
MAX_NAV_STEPS = 3

matches = []
snapshot_filenames = []   # renamed from `filename` — now stores actual filenames, not content

def extract_snapshot_path(text: str) -> str | None:
    # Try multiple patterns
    patterns = [
        r"\[Snapshot\]\(([^)]+)\)",
        r"Snapshot.*?file[:\s]+([^\s]+\.yml)",
        r"path[:\s]+([^\s]+\.yml)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


matches1 = []

def find_and_read_snapshot_file(fname: str) -> list:
    """Returns ALL lines from the snapshot file for debugging."""
    matches1.clear()
    current_dir = os.getcwd()
    while True:
        candidate = os.path.join(current_dir, ".playwright-mcp", fname)
        if os.path.exists(candidate):
            time.sleep(0.2)
            with open(candidate, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                # Return ALL lines, not just filtered ones
                return lines
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
    return []
def ative(name):
    text_list = find_and_read_snapshot_file(name)

    recipients = Subject = Body = Send = None

    for item in text_list:
        if "recipients" in item and "combobox" in item:
            match = re.search(r'ref=(\w+)', item)
            if match:
                recipients = match.group(1)
                print(recipients, "recipients")
        if "Subject" in item or "subject" in item.lower():
            match = re.search(r'ref=(\w+)', item)
            if match:
                Subject = match.group(1)
                print(Subject, "Subject")
        if "Body" in item or "body" in item.lower() or "message" in item.lower():
            match = re.search(r'ref=(\w+)', item)
            if match:
                Body = match.group(1)
                print(Body, "Body")
        if "Send" in item and "[cursor=pointer]" in item and "options" not in item:
            match = re.search(r'ref=(\w+)', item)
            if match:
                Send = match.group(1)
                print(Send, "Send")

    if None in (recipients, Subject, Body, Send):
        print(f"[ative] WARNING: some fields not found -> "
              f"recipients={recipients}, Subject={Subject}, Body={Body}, Send={Send}")

    return recipients, Subject, Body, Send


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
                              headers=self._headers(), timeout=30)

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
                    real_name = os.path.basename(path)
                    snapshot_filenames.append(real_name)   # store actual filename, latest at [-1]
                    file_content = find_and_read_snapshot_file(real_name)
                    if file_content:
                        return file_content
            return find_and_read_latest_snapshot() or "Snapshot empty."
        return text if text else "OK"


def run_agent2(goal: str, start_url: str):
    mcp = MCPClient()
    mcp.start()
    mcp.list_tools()
    print(f"\nGoal : {goal}")
    print(f"URL  : {start_url}")
    print("=" * 60)

    # Navigate first to generate initial snapshot
    print("\n--- Initial Navigation ---")
    time.sleep(2)
    
    # Take snapshot and capture filename
    print("\n--- Taking Initial Snapshot ---")
    snapshot = mcp.call_tool("browser_snapshot", {})
    
    # If still no filename, manually find it
    if not snapshot_filenames:
        print("[WARN] No filename captured, searching manually...")
        current_dir = os.getcwd()
        while True:
            pattern = os.path.join(current_dir, ".playwright-mcp", "page-*.yml")
            files = glob.glob(pattern)
            if files:
                latest = max(files, key=os.path.getmtime)
                real_name = os.path.basename(latest)
                snapshot_filenames.append(real_name)
                print(f"[INFO] Found snapshot file: {real_name}")
                break
            parent = os.path.dirname(current_dir)
            if parent == current_dir:
                break
            current_dir = parent
    
    if not snapshot_filenames:
        print("STUCK: Could not find any snapshot files.")
        mcp.stop()
        return

    for step in range(1, MAX_NAV_STEPS + 1):
        print(f"\n--- Step {step}: Planning ---")

        # Get current state
        snapshot = mcp.call_tool("browser_snapshot", {})
        if not snapshot or snapshot == "Snapshot empty.":
            snapshot = find_and_read_latest_snapshot()
        
        if not snapshot:
            print("STUCK: Could not get snapshot.")
            break

        # Use the LATEST snapshot filename
        latest_filename = snapshot_filenames[-1]
        print(f"[INFO] Using snapshot: {latest_filename}")
        
        recipients, Subject, Body, submit = ative(latest_filename)

        if None in (recipients, Subject, Body, submit):
            print("STUCK: Could not locate one or more form fields in snapshot.")
            print(f"  recipients={recipients}, Subject={Subject}, Body={Body}, Send={submit}")
            break

        print(f"[INFO] Filling form - To: {recipients}, Subject: {Subject}, Body: {Body}, Send: {submit}")
        # for item in mail_recipt :                     for multiple people mail
        mcp.call_tool("browser_type", {
            "target": recipients,
            "text": "test@example.com",
            "slowly": False,
        })
        time.sleep(0.5)

        mcp.call_tool("browser_type", {
            "target": Subject,
            "text": "Test Subject",
            "slowly": False,
        })
        time.sleep(0.5)

        mcp.call_tool("browser_type", {
            "target": Body,
            "text": "Test body content",
            "slowly": False,
        })
        time.sleep(0.5)

        print("[INFO] Clicking send...")
        mcp.call_tool("browser_click", {"target": submit})
        mcp.call_tool("browser_wait_for", {"time": 2})

    mcp.stop()
if __name__ == "__main__":
    run_agent2("email", "https://www.instagram.com/direct/t/18075902687207564/")
