import os
from openai import OpenAI
import json
# file imports
from Searching import run_agent1
from Extract_text import extract_page_to_markdown
from Navigation import run_agent, navi
from typeing import run_agent2
from dotenv import load_dotenv

MODEL_NAME = "meta/llama-3.1-8b-instruct"
load_dotenv()
API_key = os.getenv("API_key")
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=API_key
)


def get_next_step(goal, current_state, previous_steps):
    system_prompt = """
You are a Browser Automation Step Planner. Your ONLY job is to output the SINGLE next
step toward the goal, grounded STRICTLY in the Current State you are shown. You never
execute anything — you only decide.

GOAL: {goal}

═══════════════════════════════════════════
SESSION STATE
═══════════════════════════════════════════
You are ALREADY LOGGED IN to this site/account. Do not plan, suggest, or look for
any login/sign-in/sign-up step. If you see a login form in Current State, it is
NOT a blocker for this session — ignore it and proceed toward the goal as if
authenticated content is available elsewhere on the page/site.

═══════════════════════════════════════════
ABSOLUTE GROUNDING RULE (read this twice)
═══════════════════════════════════════════
Every "target" you output for click/type MUST be a ref string that appears
VERBATIM, character-for-character, in the Current State below. If you cannot find
an exact match, you MUST NOT invent, guess, reuse an old ref, or modify one.
In that case, output "navigate" instead.
Don't use type and click in for search , just use search action for it .

═══════════════════════════════════════════
ACTION REFERENCE — exact field usage per action
═══════════════════════════════════════════
| action        | target                          | value              |
|---------------|----------------------------------|--------------------|
| navigate      | full https:// URL               | null               |
| click         | exact ref from Current State     | null               |
| type          | exact ref from Current State     | text to type       |
| search        | exact ref of search input        | search query text  |
| scroll        | "up" or "down"                   | pixels (integer)   |
| extract_text  | null                             | null               |
| extract_files | null                             | null               |
| finish        | null                             | "true" or "false"  |

Use "finish" when:
- The goal is visibly satisfied in the Current State main content (not sidebar/nav), → value "true"
- A CAPTCHA or other unrecoverable block appears (NOT a login wall — you are already authenticated, so treat any login prompt as a rendering artifact, not a real block), → value "false"
- The same action would just repeat with no new information, → value "false"

═══════════════════════════════════════════
OUTPUT SCHEMA (respond with exactly this, nothing else)
═══════════════════════════════════════════
{{"action": "<one of the 8 above>", "target": "<see table or null>"}}

Format reference only — do not copy these values, they are placeholders:
{{"action": "click", "target": "REF_FROM_STATE"}}
{{"action": "finish", "target": null }}

═══════════════════════════════════════════
FINAL REMINDER
═══════════════════════════════════════════
- sign in is not allowed as a step
- search 'none' is not allowed as a step 
- Output ONE JSON object. No markdown fences. No text before or after it.
- "target" for click/type must be copied verbatim from Current State — never fabricated.
- If the same target/action was just attempted with no change in Current State, choose "finish" with value "false" instead of repeating it.
""".format(goal=goal)

    steps_history = "\n".join([f"{i+1}. {step}" for i, step in enumerate(previous_steps)]) if previous_steps else "No steps taken yet."
    user_prompt = f"""
    Goal: {goal}
    Current State: {current_state}
    Previous Steps Taken:
    {steps_history}
    What is the NEXT single step to take?
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,  # Low temperature for deterministic planning
            max_tokens=300     # bumped up so long refs don't get truncated mid-JSON
        )
        content = response.choices[0].message.content.strip()

        # Strip markdown code fences in case the model ignores the "no fences" instruction
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:]
            content = content.strip()

        return content
    except Exception as e:
        print(f"Error calling NVIDIA NIM: {e}")
        return None


def humanize_step(step_json):
    try:
        data = json.loads(step_json)
    except (json.JSONDecodeError, TypeError):
        return f"Unrecognized step output: {step_json}"
    action = data.get("action")
    target = data.get("target")
    value = data.get("value")
    if action == "navigate":
        return f"go to {target}"
    elif action == "click":
        return f"click {target}"
    elif action == "type":
        return f"Type '{value}' into element {target}"
    elif action == "search":
        return f"search '{value}'"
    elif action == "scroll":
        return f"scroll {target} by {value} pixels"
    elif action == "extract_text":
        return "Extract text from the current page"
    elif action == "extract_files":
        return "Extract files from the current page"
    elif action == "finish":
        if str(value).lower() == "true":
            return "Finish — goal achieved"
        else:
            return "Finish — goal not achieved or blocked"
    else:
        return f"Unknown action: {action}"


def get_page_snapshot(current_url):
    try:
        return extract_page_to_markdown(current_url)
    except Exception as e:
        print(f"Could not capture snapshot: {e}")
        return f"Unable to capture state at {current_url}"


def execute_automation(goal, max_steps=10):
    # Local (not global/module-level) state so repeated calls in the same
    # process don't accumulate steps/human from previous runs.
    steps = []
    human = []

    print(f"Starting Automation for Goal: '{goal}'\n")
    current_url = "https://mail.google.com/mail/u/0/#inbox"  # wherever your browser session actually starts
    current_state = "Browser is open on homepage."
    previous_steps = []

    for i in range(max_steps):
        print(f"--- Step {i+1} ---")
        next_step_json = get_next_step(goal, current_state, previous_steps)
        if not next_step_json:
            print("Failed to get a valid step from the LLM.")
            break

        steps.append(next_step_json)
        previous_steps.append(next_step_json)
        print(f"LLM Decision: {next_step_json}")

        human_step = humanize_step(next_step_json)
        human.append(human_step)
        print(f"Human-readable: {human_step}")

        try:
            data = json.loads(next_step_json)
        except (json.JSONDecodeError, TypeError):
            print(f"Could not parse step JSON, stopping. Raw output was: {next_step_json!r}")
            break

        action = data.get("action")
        target = data.get("target")
        value = data.get("value")

        if action == "finish":
            print("Model signalled finish — stopping.")
            break

        try:
            if action == "navigate":
                current_url = navi(target)
            elif action == "click":
                # Pass the structured target directly to the executor instead of
                # the humanized string, so it doesn't have to re-parse it.
                current_url = run_agent(target, current_url)
            elif action == "search":
                current_url = run_agent1(value, current_url)
            elif action == "type":
                current_url = run_agent2(target, value, current_url)
            elif action == "extract_text" or action == "extract_files":
                # Don't overwrite current_url with page content — keep the URL
                # intact and store the extracted content separately.
                extracted_content = extract_page_to_markdown(current_url)
                current_state = extracted_content
                print("New state captured for next planning step.\n")
                continue
            elif action == "scroll":
                print("Scroll action not yet wired to an executor — skipping.")
            else:
                print(f"Unknown action '{action}', stopping.")
                break
        except Exception as e:
            print(f"Execution failed for action '{action}': {e}")
            break

        current_state = get_page_snapshot(current_url)
        print("New state captured for next planning step.\n")

    return steps, human


if __name__ == "__main__":
    user_goal = input("Whats your goal : ")
    all_steps, all_human = execute_automation(user_goal)
    print("\nRaw steps:", all_steps)
    print("\nHuman-readable steps:")
    for h in all_human:
        print(f"- {h}")