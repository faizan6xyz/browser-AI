import json
import argparse
from pathlib import Path
def load_events(log_path: str):
    events = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
def history_for_path(events: list, current_path: str) -> list:
    current_path = str(Path(current_path).resolve())
    # walk backwards: find every path this file used to have, following
    # renamed/moved events whose `to_path` matches a path we've already found
    path_chain = {current_path}
    changed = True
    while changed:
        changed = False
        for e in events:
            if e["action"] in ("renamed", "moved") and e["to_path"] in path_chain:
                if e["from_path"] not in path_chain:
                    path_chain.add(e["from_path"])
                    changed = True
    relevant = [
        e for e in events
        if e.get("path") in path_chain
        or e.get("from_path") in path_chain
        or e.get("to_path") in path_chain
    ]
    relevant.sort(key=lambda e: e["timestamp"])
    return relevant
def filter_by_action(events: list, action: str) -> list:
    return [e for e in events if e["action"] == action]
def format_event(e: dict) -> str:
    ts = e["timestamp"]
    action = e["action"]
    if action in ("renamed", "moved"):
        return f"[{ts}] {action.upper():<8} {e['from_path']}  ->  {e['to_path']}"
    return f"[{ts}] {action.upper():<8} {e['path']}"
def main():
    parser = argparse.ArgumentParser(description="Query file engagement history.")
    parser.add_argument("--log", default="file_history.jsonl", help="Path to the JSONL log file")
    parser.add_argument("--path", help="Show full lineage/history for this file path")
    parser.add_argument("--action", help="Filter by action: created/deleted/modified/renamed/moved")
    parser.add_argument("--recent", type=int, help="Show the N most recent events overall")
    args = parser.parse_args()
    events = load_events(args.log)
    if args.path:
        result = history_for_path(events, args.path)
        print(f"\nHistory for: {args.path}  ({len(result)} events)\n")
    elif args.action:
        result = filter_by_action(events, args.action)
        print(f"\nEvents with action='{args.action}'  ({len(result)} events)\n")
    elif args.recent:
        result = sorted(events, key=lambda e: e["timestamp"])[-args.recent:]
        print(f"\nMost recent {len(result)} events\n")
    else:
        result = sorted(events, key=lambda e: e["timestamp"])
        print(f"\nAll events  ({len(result)} total)\n")

    for e in result:
        print(format_event(e))
if __name__ == "__main__":
    main()