import os
from openai import OpenAI
import json
# file imports 
from Searching import run_agent1
from Extract_text import extract_page_to_markdown
from Navigation import run_agent
from typeing import run_agent2
from dotenv import load_dotenv
MODEL_NAME = "meta/llama-3.3-70b-instruct"

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
            temperature=0.2, # Low temperature for deterministic planning
            max_tokens=150
        )
        content = response.choices[0].message.content
        return content.strip()
    except Exception as e:
        print(f"Error calling NVIDIA NIM: {e}")
        return None
def humanize_step(step_json):
    """Convert the raw JSON step into a plain-English sentence."""
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
        return f"Type '{value}' into element {target})"
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
steps = []
human = []

def execute_automation(goal, max_steps=10):
    print(f" Starting Automation for Goal: '{goal}'\n")
    current_state = "Browser is open on homepage."
    previous_steps = []
    for i in range(max_steps):
        print(f"--- Step {i+1} ---")
        next_step_json = get_next_step(goal, current_state, previous_steps)
        steps.append(next_step_json)
        if not next_step_json:
            print("Failed to get a valid step from the LLM.")
            break     
        print(f" LLM Decision: {next_step_json}")
        previous_steps.append(next_step_json)
        human_step = humanize_step(next_step_json)
        human.append(human_step)
        print(f" Human-readable: {human_step}")

        if '"finish"' in next_step_json.lower():
            print(" Goal achieved! Automation complete.")
            break
        current_state = f"Completed step {i+1}. Ready for next action."
        print(f"State updated: {current_state}\n")
from Navigation import navi
if __name__ == "__main__":
    user_goal = input("Whats your goal : ")
    execute_automation(user_goal)
    print("\nRaw steps:", steps)
    print("\nHuman-readable steps:")
    lasturl = ""
    for h in human:  # h is a list of strings
        print(f"- {h}")
    for h in human:  # h is a list of strings
        if "navigate" in h :
            lasturl = h.strip().replace("navigate", "").strip()
            navi(lasturl)
        if "go" in h : 
            lasturl = h.strip().replace("go to", "").strip()
            navi(lasturl)
        if "click" in h :
            lasturl = run_agent(h,lasturl)
        if "Search" in h :
            lasturl = run_agent1(h,lasturl)
        if "search" in h :
            lasturl = run_agent1(h,lasturl)
        if "type" in h :
            lasturl = run_agent2(h,lasturl)
        if "text" in h : 
            lasturl = extract_page_to_markdown(lasturl)