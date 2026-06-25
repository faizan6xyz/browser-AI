from File_manager_agent import get_next_action, _execute, TOOLS, SAFE_ACTIONS
import json
def run_agent(goal, directory):
    full_goal = f"{goal}\nWorking directory: {directory}" if directory.strip() else goal
    history = []
    step = 0
    while True:
        step += 1
        parsed = get_next_action(full_goal, history)
        action = parsed.get("action", "done")
        args   = parsed.get("args", {})
        print(f"\nStep {step} | {action} | {json.dumps(args)}")
        if action == "done" or action not in TOOLS:
            print("Done!" if action == "done" else f"Unknown action: {action}")
            break
        if action not in SAFE_ACTIONS:
            confirm = input("Approve? (y/n): ")
            if confirm.lower() != "y":
                history.append({"role": "assistant", "content": json.dumps(parsed)})
                history.append({"role": "user", "content": "Tool result: Skipped."})
                continue
        result = _execute(action, args)
        print(f"Result: {result}")
        history.append({"role": "assistant", "content": json.dumps(parsed)})
        history.append({"role": "user", "content": f"Tool result: {result}"})
while True:
    task = input("\nTask ('exit' to quit): ")
    if task == "exit":
        break
    directory = input("Directory: ")
    run_agent(task, directory)