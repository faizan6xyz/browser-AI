from File_manager_agent import (
    empty_state, get_next_action, _execute, 
    TOOLS, SAFE_ACTIONS, log_line , json
)
def run_cli_agent(goal: str, directory: str):
    state = empty_state()
    state["goal"]      = goal
    state["full_goal"] = f"{goal}\nWorking directory: {directory}" if directory.strip() else goal
    state["running"]   = True
    print(f"\n{'='*60}")
    print(f"  Goal      : {goal}")
    print(f"  Directory : {directory or 'Not specified'}")
    print(f"{'='*60}\n")
    while state["running"] and not state["done"]:
        print("  Asking AI what to do...")
        parsed = get_next_action(state["full_goal"], state["history"])
        action = parsed.get("action", "done")
        args   = parsed.get("args", {})
        reason = parsed.get("reason", "")
        impact = parsed.get("impact", "")
        state["step"] += 1
        print(f"\n── Step {state['step']} ──")
        print(f"  Action  : {action}")
        print(f"  Args    : {json.dumps(args, ensure_ascii=False)}")
        print(f"  Reason  : {reason}")
        if action == "done":
            print("\n  Goal achieved!")
            state["running"] = False
            state["done"]    = True
            break
        if action not in TOOLS:
            print(f"  Unknown action '{action}' — stopping.")
            state["running"] = False
            break
        if action in SAFE_ACTIONS:
            result = _execute(action, args)
            print(f"  Result  :\n{result}")
            state["history"].append({"role": "assistant", "content": json.dumps(parsed)})
            state["history"].append({"role": "user",      "content": f"Tool result: {result}"})
            continue  
        print(f"\n┌─────────────────────────────────────────┐")
        print(f"│  THIS ACTION REQUIRES YOUR APPROVAL     │")
        print(f"├─────────────────────────────────────────┤")
        print(f"│  Action : {action:<30}│")
        print(f"│  Args   : {json.dumps(args, ensure_ascii=False):<30}│")
        print(f"├─────────────────────────────────────────┤")
        print(f"│  What will happen:                      │")
        print(f"│  {impact:<41}│")
        print(f"└─────────────────────────────────────────┘")
        choice = input("\n  Proceed? (y/n/stop): ").strip().lower()
        if choice == "y":
            result = _execute(action, args)
            print(f"  Result  :\n{result}")
            state["history"].append({"role": "assistant", "content": json.dumps(parsed)})
            state["history"].append({"role": "user",      "content": f"Tool result: {result}"})
        elif choice == "stop":
            print("  Stopping agent.")
            state["running"] = False
            break
        else:
            print("  Skipped.")
            state["history"].append({"role": "assistant", "content": json.dumps(parsed)})
            state["history"].append({"role": "user",      "content": "Tool result: User skipped this action."})
if __name__ == "__main__":
    while True:
        task = input("\nEnter the task ('exit' to quit): ").strip()
        if task.lower() == "exit":
            break
        directory = input("State the directory for the work: ").strip()
        run_cli_agent(task, directory)