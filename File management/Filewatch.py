import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
class FileHistoryHandler(FileSystemEventHandler):
    def __init__(self, log_path: str, ignore_patterns=None):
        self.log_path = Path(log_path).resolve()
        # default ignores: temp files editors create while saving, and the log itself
        self.ignore_patterns = ignore_patterns or [".tmp", "~$", ".crdownload", ".part"]
    def _should_ignore(self, path: str) -> bool:
        try:
            resolved = Path(path).resolve()
        except Exception:
            return True
        if resolved == self.log_path:
            return True  # never log writes to our own log file
        name = resolved.name
        return any(pat in name for pat in self.ignore_patterns)
    def _write(self, entry: dict):
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    def on_created(self, event):
        if self._should_ignore(event.src_path):
            return
        self._write({
            "action": "created",
            "path": event.src_path,
            "is_directory": event.is_directory,
        })
    def on_deleted(self, event):
        if self._should_ignore(event.src_path):
            return
        self._write({
            "action": "deleted",
            "path": event.src_path,
            "is_directory": event.is_directory,
        })
    def on_modified(self, event):
        # directory-level "modified" fires whenever a child changes - pure noise, skip it
        if event.is_directory or self._should_ignore(event.src_path):
            return
        self._write({
            "action": "modified",
            "path": event.src_path,
            "is_directory": event.is_directory,
        })
    def on_moved(self, event):
        if self._should_ignore(event.src_path) or self._should_ignore(event.dest_path):
            return
        same_dir = os.path.dirname(event.src_path) == os.path.dirname(event.dest_path)
        self._write({
            "action": "renamed" if same_dir else "moved",
            "from_path": event.src_path,
            "to_path": event.dest_path,
            "is_directory": event.is_directory,
        })
def watch_folder(folder: str, log_path: str = "file_history.jsonl", recursive: bool = True):
    folder = str(Path(folder).resolve())
    handler = FileHistoryHandler(log_path)
    observer = Observer()
    observer.schedule(handler, folder, recursive=recursive)
    observer.start()
    print(f"Watching: {folder}")
    print(f"Logging to: {Path(log_path).resolve()}")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping watcher...")
        observer.stop()
    observer.join()
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Watch a folder and log file engagement history.")
    parser.add_argument("folder", help="Folder to watch")
    parser.add_argument("--log", default="file_history.jsonl", help="Path to the JSONL log file")
    parser.add_argument("--no-recursive", action="store_true", help="Don't watch subfolders")
    args = parser.parse_args()
    watch_folder(args.folder, args.log, recursive=not args.no_recursive)