import os
import re
import json
import shutil
import logging
import pathlib
import datetime
import gradio as gr
from openai import OpenAI
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)
MODEL = "meta/llama-3.1-8b-instruct"
LOG_FILE = "file_agent.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
SYSTEM_PROMPT = """
You are a file management agent. Given a goal and optionally a directory, decide the next single action.

Respond EXACTLY in this JSON format and nothing else:
{
  "action": "tool_name",
  "args": {"arg1": "value1"},
  "reason": "why you are doing this",
  "impact": "plain English description of what will change on disk"
}

Available tools:
- list_files(directory)                    → lists all files with size and extension
- read_file(path)                          → reads first 2000 chars of a text file
- move_file(src, dst)                      → moves file to new location
- copy_file(src, dst)                      → copies file to new location
- rename_file(path, new_name)              → renames a file
- delete_file(path)                        → permanently deletes a file ⚠️
- create_folder(path)                      → creates a new folder
- get_file_info(path)                      → size, extension, modified date
- search_files(directory, keyword)         → finds files by name keyword
- organize_by_type(directory)              → sorts files into subfolders by extension
- find_large_files(directory, min_size_mb) → finds files above size threshold
- find_duplicates(directory)               → finds files with same name in folder
- done                                     → goal is complete

Rules:
- Always use full absolute paths
- Never touch system folders: Windows, Program Files, System32, $Recycle.Bin
- If unsure about a path, use list_files or search_files first
- If goal is already achieved, use done
- Be specific in the 'impact' field — mention file names or folders affected
"""
SAFE_ACTIONS       = {"list_files", "read_file", "get_file_info",
                      "search_files", "find_large_files", "find_duplicates"}
DESTRUCTIVE_ACTIONS = {"move_file", "copy_file", "rename_file",
                       "delete_file", "create_folder", "organize_by_type"}
def list_files(directory: str) -> str:
    if not os.path.exists(directory):
        return f"ERROR: Directory '{directory}' does not exist."
    result, count = [], 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ["Windows", "Program Files", "Program Files (x86)", "System32", "$Recycle.Bin"]]
        for file in files:
            full_path = os.path.join(root, file)
            try:
                size = os.path.getsize(full_path)
                result.append(f"{full_path} [{round(size/1024,1)} KB] [{pathlib.Path(file).suffix}]")
                count += 1
                if count >= 100:
                    result.append("... (showing first 100 files)")
                    return "\n".join(result)
            except Exception:
                continue
    return "\n".join(result) if result else "No files found."
def read_file(path: str) -> str:
    if not os.path.exists(path):
        return f"ERROR: File '{path}' does not exist."
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(2000)
        return content if content else "(empty file)"
    except Exception as e:
        return f"ERROR reading file: {e}"
def move_file(src: str, dst: str) -> str:
    if not os.path.exists(src):
        return f"ERROR: Source '{src}' does not exist."
    try:
        os.makedirs(os.path.dirname(dst) if os.path.dirname(dst) else ".", exist_ok=True)
        shutil.move(src, dst)
        logger.info(f"MOVED: {src} → {dst}")
        return f"Moved: {src} → {dst}"
    except Exception as e:
        return f"ERROR: {e}"
def copy_file(src: str, dst: str) -> str:
    if not os.path.exists(src):
        return f"ERROR: Source '{src}' does not exist."
    try:
        os.makedirs(os.path.dirname(dst) if os.path.dirname(dst) else ".", exist_ok=True)
        shutil.copy2(src, dst)
        logger.info(f"COPIED: {src} → {dst}")
        return f" Copied: {src} → {dst}"
    except Exception as e:
        return f"ERROR: {e}"
def rename_file(path: str, new_name: str) -> str:
    if not os.path.exists(path):
        return f"ERROR: File '{path}' does not exist."
    try:
        parent   = os.path.dirname(path)
        new_path = os.path.join(parent, new_name)
        os.rename(path, new_path)
        logger.info(f"RENAMED: {path} → {new_path}")
        return f" Renamed: {path} → {new_path}"
    except Exception as e:
        return f"ERROR: {e}"
def delete_file(path: str) -> str:
    if not os.path.exists(path):
        return f"ERROR: File '{path}' does not exist."
    try:
        os.remove(path)
        logger.warning(f"DELETED: {path}")
        return f"Deleted: {path}"
    except Exception as e:
        return f"ERROR: {e}"
def create_folder(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
        logger.info(f"CREATED FOLDER: {path}")
        return f" Created folder: {path}"
    except Exception as e:
        return f"ERROR: {e}"
def get_file_info(path: str) -> str:
    if not os.path.exists(path):
        return f"ERROR: '{path}' does not exist."
    try:
        stat     = os.stat(path)
        modified = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"Path      : {path}\n"
            f"Size      : {round(stat.st_size / 1024, 2)} KB\n"
            f"Extension : {pathlib.Path(path).suffix}\n"
            f"Modified  : {modified}\n"
            f"Is file   : {os.path.isfile(path)}"
        )
    except Exception as e:
        return f"ERROR: {e}"
def search_files(directory: str, keyword: str) -> str:
    if not os.path.exists(directory):
        return f"ERROR: Directory '{directory}' does not exist."
    matches, kw = [], keyword.lower()
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if kw in file.lower():
                matches.append(os.path.join(root, file))
    return "\n".join(matches) if matches else f"No files found matching '{keyword}'."
def organize_by_type(directory: str) -> str:
    if not os.path.exists(directory):
        return f"ERROR: Directory '{directory}' does not exist."
    ext_map = {
        ".jpg":"Images",".jpeg":"Images",".png":"Images",".gif":"Images",
        ".bmp":"Images",".webp":"Images",
        ".mp4":"Videos",".mkv":"Videos",".avi":"Videos",".mov":"Videos",".wmv":"Videos",
        ".mp3":"Audio",".wav":"Audio",".flac":"Audio",".aac":"Audio",
        ".pdf":"PDFs",
        ".doc":"Documents",".docx":"Documents",
        ".xls":"Spreadsheets",".xlsx":"Spreadsheets",
        ".ppt":"Presentations",".pptx":"Presentations",
        ".txt":"Text",".md":"Text",".csv":"Text",
        ".zip":"Archives",".rar":"Archives",".7z":"Archives",".tar":"Archives",".gz":"Archives",
        ".py":"Code",".js":"Code",".html":"Code",".css":"Code",".java":"Code",".cpp":"Code",
        ".exe":"Programs",".msi":"Programs",
    }
    moved, errors = [], []
    for file in os.listdir(directory):
        src = os.path.join(directory, file)
        if not os.path.isfile(src):
            continue
        ext         = pathlib.Path(file).suffix.lower()
        folder_name = ext_map.get(ext, "Other")
        dst_folder  = os.path.join(directory, folder_name)
        dst         = os.path.join(dst_folder, file)
        try:
            os.makedirs(dst_folder, exist_ok=True)
            shutil.move(src, dst)
            moved.append(f"{file} → {folder_name}/")
            logger.info(f"ORGANIZED: {src} → {dst}")
        except Exception as e:
            errors.append(f"Could not move {file}: {e}")
    result = f" Organized {len(moved)} files:\n" + "\n".join(moved)
    if errors:
        result += "\n\nErrors:\n" + "\n".join(errors)
    return result if moved else "No files to organize."
def find_large_files(directory: str, min_size_mb: float = 100) -> str:
    if not os.path.exists(directory):
        return f"ERROR: Directory '{directory}' does not exist."
    threshold = min_size_mb * 1024 * 1024
    large = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            path = os.path.join(root, file)
            try:
                size = os.path.getsize(path)
                if size >= threshold:
                    large.append(f"{path} [{round(size/(1024*1024),1)} MB]")
            except Exception:
                continue
    large.sort(key=lambda x: float(re.search(r"\[([\d.]+) MB\]", x).group(1)), reverse=True)
    return "\n".join(large) if large else f"No files larger than {min_size_mb} MB found."
def find_duplicates(directory: str) -> str:
    if not os.path.exists(directory):
        return f"ERROR: Directory '{directory}' does not exist."
    from collections import defaultdict
    name_map = defaultdict(list)
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            name_map[file.lower()].append(os.path.join(root, file))
    dupes = {n: p for n, p in name_map.items() if len(p) > 1}
    if not dupes:
        return "No duplicate filenames found."
    result = []
    for name, paths in dupes.items():
        result.append(f"\n{name}:")
        for p in paths:
            result.append(f"  {p}")
    return "\n".join(result)
TOOLS = {
    "list_files":       list_files,
    "read_file":        read_file,
    "move_file":        move_file,
    "copy_file":        copy_file,
    "rename_file":      rename_file,
    "delete_file":      delete_file,
    "create_folder":    create_folder,
    "get_file_info":    get_file_info,
    "search_files":     search_files,
    "organize_by_type": organize_by_type,
    "find_large_files": find_large_files,
    "find_duplicates":  find_duplicates,
}
def empty_state() -> dict:
    return {
        "history":   [],
        "goal":      "",
        "full_goal": "",
        "log_lines": [],
        "pending":   None,
        "step":      0,
        "running":   False,
        "done":      False,
    }
def get_next_action(full_goal: str, history: list) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": f"GOAL: {full_goal}"}
    ]
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=400,
            temperature=0
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"LLM error: {e}")
        return {"action": "done", "args": {}, "reason": "LLM error", "impact": str(e)}
def log_line(state: dict, msg: str) -> str:
    state["log_lines"].append(msg)
    logger.info(msg)
    return "\n".join(state["log_lines"])
def start_agent(goal: str, directory: str, state: dict):
    """
    Initialise state, call LLM for first action, show it to the user.
    Returns: (output_text, confirm_row_visible, state)
    """
    state = empty_state()
    state["goal"]      = goal
    state["full_goal"] = f"{goal}\nWorking directory: {directory}" if directory.strip() else goal
    state["running"]   = True
    out = log_line(state, f" Goal      : {goal}")
    out = log_line(state, f" Directory : {directory or 'Not specified'}")
    out = log_line(state, f" Model     : {MODEL}")
    out = log_line(state, "=" * 60)
    out = log_line(state, " Asking AI what to do...")
    parsed  = get_next_action(state["full_goal"], state["history"])
    action  = parsed.get("action", "done")
    args    = parsed.get("args", {})
    reason  = parsed.get("reason", "")
    impact  = parsed.get("impact", "")
    state["step"] += 1
    out = log_line(state, f"\n── Step {state['step']} ──")
    out = log_line(state, f" Action  : {action}")
    out = log_line(state, f" Args    : {json.dumps(args, ensure_ascii=False)}")
    out = log_line(state, f" Reason  : {reason}")
    if action == "done":
        out = log_line(state, "\n Goal achieved!")
        state["running"] = False
        state["done"]    = True
        return out, gr.update(visible=False), gr.update(visible=False), state
    if action not in TOOLS:
        out = log_line(state, f"  Unknown action '{action}' — stopping.")
        state["running"] = False
        return out, gr.update(visible=False), gr.update(visible=False), state
    if action in SAFE_ACTIONS:
        result = _execute(action, args)
        out    = log_line(state, f" Result  :\n{result}")
        state["history"].append({"role": "assistant", "content": json.dumps(parsed)})
        state["history"].append({"role": "user",      "content": f"Tool result: {result}"})
        return _advance(state)
    state["pending"] = parsed
    confirm_text = (
        f"┌─────────────────────────────────────────┐\n"
        f"│  THIS ACTION REQUIRES YOUR APPROVAL     │\n"
        f"├─────────────────────────────────────────┤\n"
        f"│  Action  : {action:<30}│\n"
        f"│  Args    : {json.dumps(args, ensure_ascii=False):<30}│\n"
        f"├─────────────────────────────────────────┤\n"
        f"│  What will happen:                      │\n"
        f"│  {impact:<41}│\n"
        f"└─────────────────────────────────────────┘\n"
        f"\nDo you want to proceed?"
    )
    out = log_line(state, f"\n{confirm_text}")
    return (
        out,
        gr.update(visible=True,  value=" Yes, do it"),
        gr.update(visible=True,  value=" No, skip this"),
        state
    )
def confirm_yes(state: dict):
    parsed = state["pending"]
    action = parsed.get("action")
    args   = parsed.get("args", {})
    result = _execute(action, args)
    log_line(state, f" Confirmed & executed.")
    log_line(state, f" Result  :\n{result}")
    state["history"].append({"role": "assistant", "content": json.dumps(parsed)})
    state["history"].append({"role": "user",      "content": f"Tool result: {result}"})
    state["pending"] = None
    return _advance(state)
def confirm_no(state: dict):
    parsed = state["pending"]
    action = parsed.get("action")
    log_line(state, f" Skipped by user: {action}")
    state["history"].append({"role": "assistant", "content": json.dumps(parsed)})
    state["history"].append({
        "role": "user",
        "content": f"User declined action '{action}'. Try a different approach or report findings."
    })
    state["pending"] = None
    return _advance(state)
def _execute(action: str, args: dict) -> str:
    try:
        return TOOLS[action](**args)
    except TypeError as e:
        return f"ERROR: Wrong arguments for {action}: {e}"
    except Exception as e:
        return f"ERROR: {e}"
def _advance(state: dict, max_steps: int = 20):
    if state["step"] >= max_steps:
        log_line(state, "\n  Max steps reached.")
        state["running"] = False
        out = "\n".join(state["log_lines"])
        return out, gr.update(visible=False), gr.update(visible=False), state
    log_line(state, "\n Asking AI what to do next...")
    parsed = get_next_action(state["full_goal"], state["history"])
    action = parsed.get("action", "done")
    args   = parsed.get("args", {})
    reason = parsed.get("reason", "")
    impact = parsed.get("impact", "")
    state["step"] += 1
    log_line(state, f"\n── Step {state['step']} ──")
    log_line(state, f" Action  : {action}")
    log_line(state, f" Args    : {json.dumps(args, ensure_ascii=False)}")
    log_line(state, f" Reason  : {reason}")
    if action == "done":
        log_line(state, "\n All done! Goal achieved.")
        log_line(state, f" Log saved to: {os.path.abspath(LOG_FILE)}")
        state["running"] = False
        state["done"]    = True
        out = "\n".join(state["log_lines"])
        return out, gr.update(visible=False), gr.update(visible=False), state
    if action not in TOOLS:
        log_line(state, f"  Unknown action '{action}' — stopping.")
        state["running"] = False
        out = "\n".join(state["log_lines"])
        return out, gr.update(visible=False), gr.update(visible=False), state
    if action in SAFE_ACTIONS:
        result = _execute(action, args)
        log_line(state, f" Result  :\n{result}")
        state["history"].append({"role": "assistant", "content": json.dumps(parsed)})
        state["history"].append({"role": "user",      "content": f"Tool result: {result}"})
        return _advance(state)
    state["pending"] = parsed
    confirm_text = (
        f"┌─────────────────────────────────────────┐\n"
        f"│  THIS  ACTION REQUIRES YOUR APPROVAL       │\n"
        f"├─────────────────────────────────────────┤\n"
        f"│  Action  : {action:<30}│\n"
        f"│  Args    : {json.dumps(args, ensure_ascii=False):<30}│\n"
        f"├─────────────────────────────────────────┤\n"
        f"│  What will happen:                      │\n"
        f"│  {impact:<41}│\n"
        f"└─────────────────────────────────────────┘\n"
        f"\nDo you want to proceed?"
    )
    log_line(state, f"\n{confirm_text}")
    out = "\n".join(state["log_lines"])
    return (
        out,
        gr.update(visible=True, value="✅ Yes, do it"),
        gr.update(visible=True, value="❌ No, skip this"),
        state
    )
with gr.Blocks(title="File Manager Agent") as app:
    agent_state = gr.State(empty_state())
    gr.Markdown("""
# File Manager Agent
**Powered by NVIDIA NIM (Llama 3.1-8B)** — manages your files using natural language.<br>
Safe actions (search, list, info) run automatically.<br>
Destructive actions (move, delete, organize) always ask you first.
""")
    with gr.Row():
        with gr.Column(scale=2):
            goal_input = gr.Textbox(
                label="What do you want to do?",
                placeholder='e.g. "Organize my Downloads folder by file type"',
                lines=2
            )
            dir_input = gr.Textbox(
                label="Target directory (optional)",
                placeholder=r"e.g. C:\Users\faiza\Downloads",
                lines=1
            )
            run_btn = gr.Button("▶ Run Agent", variant="primary")
        
    output_box = gr.Textbox(
        label="Agent Output",
        lines=28,
        interactive=False,
    )
    with gr.Row():
        yes_btn = gr.Button(" Yes, do it",    variant="primary", visible=False)
        no_btn  = gr.Button(" No, skip this", variant="stop",    visible=False)
    run_btn.click(
        fn=start_agent,
        inputs=[goal_input, dir_input, agent_state],
        outputs=[output_box, yes_btn, no_btn, agent_state]
    )
    yes_btn.click(
        fn=confirm_yes,
        inputs=[agent_state],
        outputs=[output_box, yes_btn, no_btn, agent_state]
    )
    no_btn.click(
        fn=confirm_no,
        inputs=[agent_state],
        outputs=[output_box, yes_btn, no_btn, agent_state]
    )
    gr.Markdown("""
    ---
    > **How it works:** Safe actions (list, search, read) run automatically without asking.<br>
    > Destructive actions (move, delete, copy, organize) always pause and show you exactly<br>
    > what will change before you approve. All actions are logged to `file_agent.log`.
    """)
if __name__ == "__main__":
    print("=" * 60)
    print("  File Manager Agent")
    print(f"  Model  : {MODEL} via NVIDIA NIM")
    print("  UI     : http://127.0.0.1:7860")
    print("=" * 60)
    app.launch(inbrowser=True)