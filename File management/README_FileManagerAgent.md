# File Manager Agent

An AI-powered file management assistant with a Gradio web UI, built on **NVIDIA NIM (Llama 3.1-8B)**. Manage your files using plain English — no commands needed.

---

## Features

- **Natural language file management** — just describe what you want done
- **Safe-by-default** — read-only actions run automatically; destructive actions always ask for approval first
- **Step-by-step reasoning** — the agent explains every action and its impact before executing
- **Full audit log** — every action is written to `file_agent.log`
- **Gradio web UI** — runs locally at `http://127.0.0.1:7860`

---

## Prerequisites

- Python 3.8+
- An [NVIDIA NIM API key](https://integrate.api.nvidia.com)

---

## Installation

```bash
pip install gradio openai
```

---

## Usage

```bash
python file_agent.py
```

Open your browser at `http://127.0.0.1:7860`.

1. **Enter your goal** — e.g. *"Organize my Downloads folder by file type"*
2. **Enter a target directory** (optional) — e.g. `C:\Users\yourname\Downloads`
3. Click **▶ Run Agent**
4. For destructive actions, review the impact summary and click **Yes** or **No**

---

## Available Tools

| Tool | Description | Requires Approval |
|---|---|---|
| `list_files(directory)` | Lists all files with size and extension | No |
| `read_file(path)` | Reads first 2000 chars of a text file | No |
| `get_file_info(path)` | Returns size, extension, and modified date | No |
| `search_files(directory, keyword)` | Finds files by name keyword | No |
| `find_large_files(directory, min_size_mb)` | Finds files above a size threshold | No |
| `find_duplicates(directory)` | Finds files with the same name in a folder | No |
| `move_file(src, dst)` | Moves a file to a new location | **Yes** |
| `copy_file(src, dst)` | Copies a file to a new location | **Yes** |
| `rename_file(path, new_name)` | Renames a file | **Yes** |
| `delete_file(path)` | Permanently deletes a file ⚠️ | **Yes** |
| `create_folder(path)` | Creates a new folder | **Yes** |
| `organize_by_type(directory)` | Sorts files into subfolders by extension | **Yes** |

---

## How It Works

```
User enters goal
       │
       ▼
  LLM decides next action (JSON response)
       │
  ┌────┴────┐
  │         │
Safe?    Destructive?
  │         │
Auto-run  Show approval prompt
  │         │
  └────┬────┘
       │
  Execute tool → feed result back to LLM
       │
  Repeat until "done" or max 20 steps
```

The agent follows a strict loop: decide → (approve if needed) → execute → feed result back → repeat. It always uses full absolute paths and avoids system folders (`Windows`, `Program Files`, `System32`, `$Recycle.Bin`).

---

## File Organization Map

When using `organize_by_type`, files are sorted into these subfolders:

| Folder | Extensions |
|---|---|
| Images | `.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` |
| Videos | `.mp4` `.mkv` `.avi` `.mov` `.wmv` |
| Audio | `.mp3` `.wav` `.flac` `.aac` |
| PDFs | `.pdf` |
| Documents | `.doc` `.docx` |
| Spreadsheets | `.xls` `.xlsx` |
| Presentations | `.ppt` `.pptx` |
| Text | `.txt` `.md` `.csv` |
| Archives | `.zip` `.rar` `.7z` `.tar` `.gz` |
| Code | `.py` `.js` `.html` `.css` `.java` `.cpp` |
| Programs | `.exe` `.msi` |
| Other | Everything else |

---

## Configuration

Edit these constants at the top of `file_agent.py`:

```python
MODEL    = "meta/llama-3.1-8b-instruct"   # NVIDIA NIM model
LOG_FILE = "file_agent.log"               # Log output path
```

To swap the API key or base URL, update the `OpenAI` client initialisation:

```python
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="your-api-key-here"
)
```

---

## Logging

All actions are logged to `file_agent.log` with timestamps and severity levels:

- **INFO** — safe reads, moves, copies, folder creation
- **WARNING** — deletions and LLM errors

---

## Safety Rules

- System folders are never touched: `Windows`, `Program Files`, `System32`, `$Recycle.Bin`
- All destructive actions pause and display exactly what will change before executing
- The agent stops automatically after **20 steps** to prevent runaway loops
- Unknown or malformed actions cause the agent to stop immediately

---

## Project Structure

```
file_agent.py       # Main application
file_agent.log      # Auto-generated action log
```

---

## Example Prompts

- *"Find all files larger than 500 MB in C:\Users\me\Videos"*
- *"Organize my Downloads folder by file type"*
- *"Search for any files named 'resume' on my Desktop"*
- *"Delete all .tmp files in C:\Temp"*
- *"Rename report.docx to final_report_2025.docx"*
