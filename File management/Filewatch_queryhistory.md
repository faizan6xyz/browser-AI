# How `file_watcher.py` and `query_history.py` Work

## `file_watcher.py` — the watcher

**What it does:** Sits and watches a folder (and all subfolders) continuously, and every time something happens to a file — created, deleted, edited, renamed, or moved — it writes one line of JSON describing that event to a log file.

**How it works under the hood:**

1. **OS-level event source, not polling.** It doesn't loop and check "did anything change?" every second (that'd be slow and could miss fast changes). Instead, `watchdog` registers with your operating system's native file-change notification API — on Windows that's `ReadDirectoryChangesW`, a Windows kernel feature that tells any program "wake me up when something changes in this directory tree." So the OS itself pushes events to your script the instant they happen.

2. **The `Observer` + `EventHandler` split.** `watchdog` separates "watching" from "reacting":
   - `Observer` is the thing that talks to the OS and runs in its own background thread, listening for raw change notifications.
   - `FileHistoryHandler` (the class in the script) is the *reaction* — it defines what to do for each event type: `on_created`, `on_deleted`, `on_modified`, `on_moved`. The Observer calls these methods automatically whenever the matching OS event arrives.
   - `observer.schedule(handler, folder, recursive=True)` is what wires them together — "watch this folder tree, and call this handler when anything happens."

3. **Why rename and move are the same event.** When you rename a file or drag it to another folder, the OS doesn't report "delete + create" — it reports a single rename/move notification that includes *both* the old path and the new path. `watchdog` exposes that as one `on_moved` event with `event.src_path` (old) and `event.dest_path` (new). The code just checks whether the parent folder is the same:
   ```python
   same_dir = os.path.dirname(src_path) == os.path.dirname(dest_path)
   ```
   Same folder → label it "renamed." Different folder → "moved." That's the whole trick — no guessing, no comparing file contents, just reading what the OS already told us.

4. **Writing to the log.** Every event becomes a Python dict (e.g. `{"action": "renamed", "from_path": ..., "to_path": ..., "timestamp": ...}`), gets serialized with `json.dumps()`, and appended as one line to `file_history.jsonl`. "JSON Lines" just means each line is a complete, independent JSON object — so the file can grow forever and you never need to load the whole thing into memory to add to it; you just open in append mode and write a line.

5. **Ignoring noise.** The handler filters out: events on the log file itself (otherwise the watcher would log itself logging, infinitely), directory-level "modified" events (these fire constantly whenever *anything inside* a folder changes — pure noise), and common temp-file patterns like `.tmp`/`~$` that editors create transiently while saving.

6. **Why it keeps running.** `observer.start()` kicks off that background thread, and the main thread just sleeps in a loop (`while True: time.sleep(1)`) so the program doesn't exit — it's waiting to be interrupted with Ctrl+C, at which point it cleanly stops the observer.

## `query_history.py` — the lineage reconstructor

**What it does:** Reads the JSONL log and answers "show me everything that's ever happened to *this specific file*" — even if that file has been renamed or moved multiple times since it was first created.

**How it works:**

The hard part is that a file's identity isn't its path — its path changes, but it's still "the same file." So given a *current* path, the script walks **backwards through time**:

1. Start with the path you gave it (e.g. `sub/final.txt`).
2. Scan all events looking for any `renamed`/`moved` event whose `to_path` matches a path you already know about.
3. If found, that event's `from_path` is an *earlier name* for the same file — add it to the known set.
4. Repeat until no new earlier paths are found (this is why it's a `while changed:` loop — it keeps expanding the set until it stops growing).

So for a file currently at `sub/final.txt`, it starts there, finds the move event that produced it (`final.txt` → `sub/final.txt`), adds `final.txt` to the set, then finds the rename event that produced *that* (`draft.txt` → `final.txt`), adds `draft.txt` — and stops, since nothing produced `draft.txt`.

5. Once it has the full set of paths this file has ever had, it filters the entire log for any event mentioning *any* of those paths — created, modified, the renames/moves themselves — sorts by timestamp, and that's your continuous timeline.

It's essentially a tiny **graph traversal**: each rename/move event is an edge connecting an old path to a new path, and you're walking that chain backward to find the root, then collecting every event attached to any node along the path.
