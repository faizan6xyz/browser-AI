import json
import os
import glob
import re
import time
import requests
from openai import OpenAI
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)
NIM_MODEL = "meta/llama-3.1-8b-instruct"
MCP_BASE = "http://localhost:3000/mcp"
ANSWER_KEY: dict = {
}
MAX_PAGES = 25
MAX_QUESTIONS_PER_PAGE = 30
DEBUG = True
def extract_snapshot_path(text: str) -> str | None:
    match = re.search(r"\[Snapshot\]\(([^)]+)\)", text)
    return match.group(1) if match else None
def find_and_read_snapshot_file(filename: str) -> str:
    current_dir = os.getcwd()
    while True:
        candidate = os.path.join(current_dir, ".playwright-mcp", filename)
        if os.path.exists(candidate):
            time.sleep(0.2) # Ensure file is fully written
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
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
                "clientInfo": {"name": "nim-form-agent", "version": "1.0"},
            },
        }
        resp = self._do_post(payload)
        resp.raise_for_status()
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        self._do_post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        print(f"[MCP] Session: {self._session_id}")

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params:
            payload["params"] = params
        resp = self._do_post(payload)
        if resp.status_code == 404:
            print(f"[MCP] 404 body: {resp.text[:200]!r}")
            print("[MCP] 404 — reconnecting...")
            self._session_id = None
            self._handshake()
            resp = self._do_post(payload)
        resp.raise_for_status()
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        return self._parse_sse(resp.text)
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
            "browser_select_option", "browser_hover", "browser_check",
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
        if DEBUG:
            print(f"    → {name}({json.dumps(arguments)[:150]})")
        # Retry logic for 404s
        for attempt in range(2):
            try:
                result = self._rpc("tools/call", {"name": name, "arguments": arguments})
                break # Success
            except Exception as e:
                if "404" in str(e) and attempt == 0:
                    print(f"    [WARN] 404 detected, reconnecting and retrying...")
                    self._session_id = None
                    self._handshake()
                    continue
                else:
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
                    file_content = find_and_read_snapshot_file(os.path.basename(path))
                    if file_content:
                        return file_content
            return find_and_read_latest_snapshot() or "Snapshot empty."
        return text if text else "OK"
EXTRACT_QUESTIONS_PROMPT = """You are given an accessibility tree snapshot of a web page containing a form.
Identify every DISTINCT question/field a user needs to fill in on THIS page only.

CRITICAL RULES FOR GOOGLE FORMS:
1. A single Multiple Choice question will appear as a 'radiogroup' OR 'checkboxgroup'. 
   DO NOT list the question heading or label as a separate 'text' question if a radio/checkbox group with the same text exists.
2. If you see a 'radiogroup' or 'checkboxgroup', that IS the question. Ignore any standalone 'heading' or 'generic' elements with the same text.
3. Only identify an element as type "text" if it is explicitly a 'textbox' or 'input' role AND there is no corresponding radio/checkbox group for that question.
4. Count carefully. Most form pages have only 1-5 questions. 

For each question, determine:
  - "ref": The EXACT ref id of the INTERACTIVE container (the radiogroup, checkboxgroup, or textbox).
  - "type": "radio", "checkbox", "text", "textarea", "dropdown"
  - "question": The question label text.
  - "options": For radio/checkbox/dropdown, list EVERY option with its OWN distinct ref.

Respond with ONLY a JSON array. Example:
[
  {"ref": "e40", "type": "radio", "question": "Favorite color?",
   "options": [{"ref": "e46", "label": "Red"}, {"ref": "e56", "label": "Blue"}]}
]
If no questions, respond with: []
"""
def extract_questions(snapshot: str, debug: bool = False) -> list[dict]:
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": EXTRACT_QUESTIONS_PROMPT},
            {"role": "user", "content": snapshot[:20000]},
        ],
        max_tokens=2000,
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
    if debug:
        print(f"    [DEBUG raw extraction]:\n{raw}\n")
    try:
        questions = json.loads(raw)
        if not isinstance(questions, list):
            return []
    except json.JSONDecodeError:
        print(f"    [WARN] Could not parse questions JSON: {raw[:200]}")
        return []
    # Deduplication logic
    seen_refs = set()
    seen_texts = set()
    deduped = []
    for q in questions[:MAX_QUESTIONS_PER_PAGE]:
        ref = q.get("ref")
        qtext_key = q.get("question", "").strip().lower()
        if not ref:
            continue
        if ref in seen_refs or (qtext_key and qtext_key in seen_texts):
            continue
        seen_refs.add(ref)
        if qtext_key:
            seen_texts.add(qtext_key)
        deduped.append(q)
    return deduped
DECIDE_ANSWER_PROMPT = """You are filling out a form question. Decide the best answer.
Rules:
- For "radio" or "dropdown": reply with ONLY the exact option label text to select.
- For "checkbox": reply with a JSON array of exact option label(s), e.g. ["Option A"].
- For "text" or "textarea": reply with the exact text to type. Keep it short.
- If unanswerable, for radio/dropdown pick the first option; for text reply "N/A".
Reply with ONLY the answer value. No explanation.
"""
def decide_answer(question: dict) -> str | list[str]:
    qtext_lower = question["question"].lower()
    # 1. Check answer key
    for key, value in ANSWER_KEY.items():
        if key.lower() in qtext_lower:
            return value
    # 2. LLM Guess
    user_content = json.dumps({
        "type": question["type"],
        "question": question["question"],
        "options": [o.get("label", o) if isinstance(o, dict) else o
                    for o in question.get("options", [])],
    })
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": DECIDE_ANSWER_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=200,
        temperature=0.2,
    )
    answer = response.choices[0].message.content.strip()
    if question["type"] == "checkbox":
        try:
            parsed = json.loads(answer)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [answer.strip('"[]')]
    return answer.strip().strip('"')
FIND_NAV_PROMPT = """You are given an accessibility tree snapshot of a form page.
Find the navigation button: "Next" or "Submit"/"Send".
Reply with ONLY a JSON object:
{"ref": "<ref id>", "kind": "next"} OR {"ref": "<ref id>", "kind": "submit"} OR {"ref": null, "kind": "none"}
"""
def find_nav_button(snapshot: str) -> dict:
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": FIND_NAV_PROMPT},
            {"role": "user", "content": snapshot[:15000]},
        ],
        max_tokens=50,
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ref": None, "kind": "none"}
CONFIRM_SUBMIT_PROMPT = """You are given an accessibility tree snapshot after submitting a form.
Did the submission succeed? Look for "Thank you", "recorded", or confirmation.
Reply with one word: YES or NO
"""
def confirm_submission(snapshot: str) -> bool:
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": CONFIRM_SUBMIT_PROMPT},
            {"role": "user", "content": snapshot[:8000]},
        ],
        max_tokens=5,
        temperature=0,
    )
    return response.choices[0].message.content.strip().upper().startswith("Y")
CHECK_VALIDATION_PROMPT = """You are given an accessibility tree snapshot of a form page.
Look for VALIDATION/ERROR messages like "This is a required question" or "Please select an option".
Reply with ONLY a JSON array of the question text(s) that have errors. If none, reply: []
"""
def check_validation_errors(snapshot: str) -> list[str]:
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": CHECK_VALIDATION_PROMPT},
            {"role": "user", "content": snapshot[:15000]},
        ],
        max_tokens=300,
        temperature=0,
    )
    raw = re.sub(r"^```json\s*|\s*```$", "", response.choices[0].message.content.strip())
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []
def answer_question(mcp: MCPClient, question: dict, answer) -> bool:
    """Returns True if the action call did not report an error."""
    qtype = question["type"]
    options = question.get("options", [])

    def ref_for_label(label: str) -> str | None:
        for opt in options:
            opt_label = opt.get("label", opt) if isinstance(opt, dict) else opt
            if opt_label.strip().lower() == str(label).strip().lower():
                return opt.get("ref") if isinstance(opt, dict) else question["ref"]
        return None
    success = True
    if qtype in ("radio", "dropdown"):
        target_ref = ref_for_label(answer) or question["ref"]
        if qtype == "dropdown":
            result = mcp.call_tool("browser_select_option", {
                "element": question["question"], "target": target_ref,
                "values": [answer],
            })
        else:
            result = mcp.call_tool("browser_click", {
                "element": f"radio option: {answer}", "target": target_ref,
            })
        success = "Error" not in result and "404" not in result
    elif qtype == "checkbox":
        labels = answer if isinstance(answer, list) else [answer]
        for label in labels:
            target_ref = ref_for_label(label) or question["ref"]
            # Try browser_check first, fallback to click
            result = mcp.call_tool("browser_check", {
                "element": f"checkbox option: {label}", "target": target_ref,
            })
            if "Error" in result:
                result = mcp.call_tool("browser_click", {
                    "element": f"checkbox option: {label}", "target": target_ref,
                })
            if "Error" in result or "404" in result:
                success = False
    elif qtype in ("text", "textarea"):
        result = mcp.call_tool("browser_type", {
            "element": question["question"] or "text field", "target": question["ref"],
            "text": str(answer), "submit": False, "slowly": False,
        })
        success = "Error" not in result and "404" not in result
    return success
def run_form_agent(form_url: str):
    mcp = MCPClient()
    mcp.start()
    mcp.list_tools()
    print(f"\nForm URL: {form_url}")
    print("=" * 60)
    mcp.call_tool("browser_navigate", {"url": form_url})
    mcp.call_tool("browser_wait_for", {"time": 3})
    for page_num in range(1, MAX_PAGES + 1):
        print(f"\n{'='*60}\nPAGE {page_num}\n{'='*60}")
        snapshot = mcp.call_tool("browser_snapshot", {})
        if not snapshot or snapshot == "Snapshot empty.":
            snapshot = find_and_read_latest_snapshot()
        if not snapshot:
            print("STUCK: Could not get page snapshot. Aborting.")
            break
        print("\n--- Extracting questions ---")
        questions = extract_questions(snapshot, debug=DEBUG)
        print(f"  Found {len(questions)} question(s).")
        failed_questions = []
        for i, q in enumerate(questions, 1):
            print(f"\n  Q{i}: [{q['type']}] {q['question']!r}")
            answer = decide_answer(q)
            print(f"    -> answer: {answer!r}")  
            ok = answer_question(mcp, q, answer)
            if not ok:
                failed_questions.append((i, q))
                print(f"    [WARN] Q{i} action reported an error.")
            mcp.call_tool("browser_wait_for", {"time": 0.5})
        if failed_questions:
            print(f"\n--- Retrying {len(failed_questions)} failed question(s) with fresh refs ---")
            mcp.call_tool("browser_wait_for", {"time": 2})
            retry_snapshot = mcp.call_tool("browser_snapshot", {})
            if not retry_snapshot or retry_snapshot == "Snapshot empty.":
                retry_snapshot = find_and_read_latest_snapshot()
            fresh_questions = extract_questions(retry_snapshot)
            for i, original_q in failed_questions:
                match = next((fq for fq in fresh_questions
                              if fq["question"].strip().lower() == original_q["question"].strip().lower()),
                             None)
                if match:
                    answer = decide_answer(match)
                    print(f"  [retry] Q{i} -> answer: {answer!r} (New Ref: {match['ref']})")
                    answer_question(mcp, match, answer)
                else:
                    print(f"  [skip] Could not re-locate Q{i} after refresh.")
                mcp.call_tool("browser_wait_for", {"time": 0.5})
        mcp.call_tool("browser_wait_for", {"time": 1})
        nav_snapshot = mcp.call_tool("browser_snapshot", {})
        if not nav_snapshot or nav_snapshot == "Snapshot empty.":
            nav_snapshot = find_and_read_latest_snapshot()
        print("\n--- Pre-flight validation check ---")
        validation_errors = check_validation_errors(nav_snapshot)
        if validation_errors:
            print(f"  [WARN] Unanswered fields detected: {validation_errors}")
        print("\n--- Looking for Next/Submit button ---")
        nav = find_nav_button(nav_snapshot)
        print(f"  -> {nav}")
        if nav.get("kind") == "none" or not nav.get("ref"):
            print("No Next/Submit button found. Stopping.")
            break
        mcp.call_tool("browser_click", {
            "element": f"{nav['kind']} button", "target": nav["ref"],
        })
        mcp.call_tool("browser_wait_for", {"time": 3})
        if nav["kind"] == "submit":
            print("\n--- Confirming submission ---")
            final_snapshot = mcp.call_tool("browser_snapshot", {})
            if not final_snapshot or final_snapshot == "Snapshot empty.":
                final_snapshot = find_and_read_latest_snapshot()
            if confirm_submission(final_snapshot):
                print(f"\n{'='*60}\nFORM SUBMITTED SUCCESSFULLY\n{'='*60}")
            else:
                print("\nSubmission unclear — check the browser window.")
            break
    else:
        print(f"\nReached MAX_PAGES ({MAX_PAGES}) without finding a Submit button.")
    mcp.stop()
if __name__ == "__main__":
    url = input("Form URL: ").strip()
    run_form_agent(url)