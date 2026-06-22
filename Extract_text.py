import json
import os
import re
import time
import glob
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)
NIM_MODEL = "meta/llama-3.1-8b-instruct"
MCP_BASE = "http://localhost:3000/mcp"
OUTPUT_DIR = "extracted_md"
CHUNK_SIZE = 12000
MAX_WORKERS = 6
MAX_CHUNKS = 15
END_BOUNDARY_HEADINGS = {
    "references", "external links", "see also", "notes",
    "further reading", "bibliography", "citations", "footnotes",
    "notes and references", "navigation menu", "categories",
    "related articles", "you might also like", "comments",
    "newsletter", "subscribe", "share this article", "more from",
}
MIN_TITLE_HEADING_LEVEL = 2
class MCPClient:
    def __init__(self, base_url: str = MCP_BASE):
        self.base_url = base_url
        self._req_id = 0
        self._session_id = None
        self._lock = threading.Lock()

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h
    def _do_post(self, payload: dict) -> requests.Response:
        return requests.post(self.base_url, json=payload,
                              headers=self._headers(), timeout=30)
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

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
            if params:
                payload["params"] = params
            resp = self._do_post(payload)
            if resp.status_code == 404:
                print("[MCP] 404 — reconnecting...")
                self._session_id = None
                self._handshake()
                resp = self._do_post(payload)
            resp.raise_for_status()
            if "mcp-session-id" in resp.headers:
                self._session_id = resp.headers["mcp-session-id"]
            return self._parse_sse(resp.text)

    def _handshake(self):
        payload = {
            "jsonrpc": "2.0", "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "main-content-extractor", "version": "1.0"},
            },
        }
        resp = self._do_post(payload)
        resp.raise_for_status()
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        self._do_post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        print(f"[MCP] Session: {self._session_id}")

    def start(self):
        self._handshake()
    def call_tool(self, name: str, arguments: dict) -> str:
        for attempt in range(3):
            try:
                result = self._rpc("tools/call", {"name": name, "arguments": arguments})
                return self._extract_text(result)
            except Exception as e:
                if "404" in str(e) or "Session not found" in str(e):
                    print(f"    [WARN] Session lost (attempt {attempt+1}). Reconnecting...")
                    self._session_id = None
                    self._handshake()
                    time.sleep(2)
                    continue
                return f"### Error\n{e}"
        return "### Error\nFailed after retries."
    def _extract_text(self, result: dict) -> str:
        content = result.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(c["text"])
            elif c.get("type") == "resource" and "resource" in c:
                res_text = c["resource"].get("text", "")
                if res_text:
                    parts.append(res_text)
        return "\n".join(parts) if parts else ""
def find_and_read_latest_snapshot() -> str:
    current_dir = os.getcwd()
    latest_file, latest_mtime = None, 0
    while True:
        for f in glob.glob(os.path.join(current_dir, ".playwright-mcp", "page-*.yml")):
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
NODE_RE = re.compile(
    r'^\s*-?\s*(?P<role>[a-zA-Z]+)'
    r'(?:\s+"(?P<text>(?:[^"\\]|\\.)*)")?'
    r'(?P<attrs>(?:\s*\[[^\]]+\])*)'
)
LEVEL_RE = re.compile(r'\[level=(\d+)\]')
def parse_nodes(snapshot: str) -> list[dict]:
    nodes = []
    for line in snapshot.splitlines():
        if not line.strip():
            continue
        m = NODE_RE.match(line)
        if not m:
            continue
        text = (m.group("text") or "").strip()
        if not text:
            continue
        role = m.group("role").lower()
        level_match = LEVEL_RE.search(m.group("attrs") or "")
        level = int(level_match.group(1)) if level_match else None
        nodes.append({"role": role, "text": text, "level": level})
    return nodes
def find_main_content_range(nodes: list[dict]) -> tuple[int, int]:
    """
    Returns (start, end) indices into `nodes` that bound the actual article/
    main content — skipping leading nav/sidebar chrome and trailing
    references/footer/nav boilerplate.
    """
    start = 0
    # Find the first heading that looks like a real title (level 1 or 2).
    # Everything before it is almost always nav/header/sidebar chrome.
    for i, n in enumerate(nodes):
        if n["role"] == "heading" and (n["level"] or 99) <= MIN_TITLE_HEADING_LEVEL:
            start = i
            break

    end = len(nodes)
    # From the title onward, find the first heading matching a known
    # end-of-article boundary phrase. Everything from there on gets dropped.
    for i in range(start + 1, len(nodes)):
        n = nodes[i]
        if n["role"] == "heading":
            normalized = n["text"].strip().lower()
            if normalized in END_BOUNDARY_HEADINGS:
                end = i
                break
    return start, end
def nodes_to_text(nodes: list[dict]) -> str:
    out = []
    for n in nodes:
        role, text, level = n["role"], n["text"], n["level"]
        if role == "heading" and level:
            out.append(f"HEADING(L{level}): {text}")
        elif role == "listitem":
            out.append(f"LIST_ITEM: {text}")
        elif role == "link":
            out.append(f"LINK: {text}")
        else:
            out.append(text)
    return "\n".join(out)
def extract_main_content(snapshot: str) -> str:
    nodes = parse_nodes(snapshot)
    start, end = find_main_content_range(nodes)
    main_nodes = nodes[start:end]
    print(f"[Main Content] {len(nodes)} total nodes → "
          f"{len(main_nodes)} nodes kept (index {start} to {end})")
    if main_nodes:
        title_preview = next((n["text"] for n in main_nodes if n["role"] == "heading"), "")
        if title_preview:
            print(f"[Main Content] Article title detected: \"{title_preview}\"")

    return nodes_to_text(main_nodes)
CHUNK_PROMPT = """You are converting cleaned web-page content into clean,
human-readable Markdown. You will be given ONE CHUNK of a larger article
(it may start or end mid-section — that's fine).

Input format notes:
- "HEADING(Lx): ..." is a heading at depth x.
- "LIST_ITEM: ..." is a bullet/list entry.
- "LINK: ..." is link text (treat as plain readable text, not a hyperlink, unless it's clearly an important named reference).
- Anything else is body text/paragraph content.

Rules:
- Turn HEADING lines into proper Markdown headings (##, ###, etc.) matching their depth.
- Turn LIST_ITEM lines into Markdown bullet lists.
- Merge fragmented text into natural, readable paragraphs.
- Do NOT invent content. Only restructure what's actually present.
- Output ONLY the Markdown for this chunk. No preamble, no explanation, no code fences.
"""
MERGE_PROMPT = """You are given several Markdown sections, each produced independently
from consecutive chunks of the SAME article's main content. Merge them into ONE clean,
coherent, human-readable Markdown document.

Rules:
- Remove duplicate headings or repeated lines that appear at chunk boundaries.
- Fix heading hierarchy so it makes sense as a single document (one main title, then
  logically nested subsections).
- Keep the actual content's meaning and order intact — don't rewrite the substance,
  just clean up structure and remove duplication.
- Output ONLY the final Markdown document. No preamble, no explanation, no code fences.
"""
def chunk_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]
def llm_structure_chunk(chunk: str) -> str:
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": CHUNK_PROMPT},
            {"role": "user", "content": chunk},
        ],
        max_tokens=1500,
        temperature=0.2,
    )
    text = response.choices[0].message.content.strip()
    return re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text)
def llm_merge_sections(sections: list[str], url: str) -> str:
    combined_input = "\n\n---CHUNK BOUNDARY---\n\n".join(sections)
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": MERGE_PROMPT},
            {"role": "user", "content": f"Page source: {url}\n\n{combined_input}"},
        ],
        max_tokens=3000,
        temperature=0.2,
    )
    text = response.choices[0].message.content.strip()
    text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text)
    header = (
        f"<!-- Source: {url} -->\n"
        f"<!-- Extracted: {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n\n"
    )
    return header + text.strip() + "\n"
def structure_snapshot_with_llm(snapshot: str, url: str) -> str:
    main_text = extract_main_content(snapshot)
    chunks = chunk_text(main_text, CHUNK_SIZE)
    if len(chunks) > MAX_CHUNKS:
        print(f"[Warn] {len(chunks)} chunks even after main-content filtering — "
              f"truncating to first {MAX_CHUNKS}")
        chunks = chunks[:MAX_CHUNKS]
    print(f"[LLM] Processing {len(chunks)} chunk(s) with {MAX_WORKERS} parallel workers...")
    sections = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(llm_structure_chunk, chunk): i for i, chunk in enumerate(chunks)}
        done_count = 0
        for future in as_completed(futures):
            i = futures[future]
            try:
                sections[i] = future.result()
            except Exception as e:
                print(f"    [ERROR] Chunk {i+1} failed: {e}")
                sections[i] = ""
            done_count += 1
            print(f"    → {done_count}/{len(chunks)} chunks done")
    if len(sections) == 1:
        header = (
            f"<!-- Source: {url} -->\n"
            f"<!-- Extracted: {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n\n"
        )
        return header + (sections[0] or "").strip() + "\n"
    print("    → merging chunks into final document")
    return llm_merge_sections(sections, url)
def save_markdown(markdown: str, title_hint: str) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", title_hint)[:50] or "page"
    path = os.path.join(OUTPUT_DIR, f"{safe_name}_{int(time.time())}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"[Saved] {path}")
    return path
def extract_page_to_markdown(url: str) -> str:
    mcp = MCPClient()
    mcp.start()
    print(f"[Navigate] {url}")
    mcp.call_tool("browser_navigate", {"url": url})
    mcp.call_tool("browser_wait_for", {"time": 2})
    snapshot = mcp.call_tool("browser_snapshot", {})
    if not snapshot or len(snapshot) < 20:
        snapshot = find_and_read_latest_snapshot()
    if not snapshot:
        raise RuntimeError("Could not obtain a snapshot of the page.")
    markdown = structure_snapshot_with_llm(snapshot, url)
    title_hint = url.split("//")[-1].split("/")[0]
    path = save_markdown(markdown, title_hint)
    return path
if __name__ == "__main__":
    url = input("Enter the URL to extract : ").strip()
    output_path = extract_page_to_markdown(url)
    print(f"\nDone. Markdown saved to: {output_path}")