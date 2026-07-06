import os
from openai import OpenAI
import json
# file imports 
from Searching import run_agent1
from Extract_text import extract_page_to_markdown
from Navigation import run_agent
from typeing import run_agent2
from dotenv import load_dotenv
MODEL_NAME = "nvidia/llama-3.1-nemotron-nano-8b-v1"

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

Do NOT use "click" or "type" for search boxes. Always use "search" for that.

═══════════════════════════════════════════
ACTION REFERENCE — every field below is REQUIRED in every response,
even when a value doesn't apply. Use the literal string "none" (not JSON null,
not an empty string) for any field that doesn't apply to the chosen action.
═══════════════════════════════════════════
| action        | target                          | value              |
|---------------|----------------------------------|--------------------|
| navigate      | full https:// URL               | "none"             |
| click         | exact ref from Current State     | "none"             |
| type          | exact ref from Current State     | text to type       |
| search        | exact ref of search input        | search query text  |
| scroll        | "up" or "down"                   | pixels (integer)   |
| extract_text  | "none"                          | "none"             |
| extract_files | "none"                          | "none"             |
| finish        | "none"                          | "true" or "false"  |

STRICT RULES ON VALUES:
- For "search", value must be a real, non-empty search query string relevant to
  the goal. value "None", "", "null", or a placeholder like "search query" is
  NEVER allowed for the search action.
- For "type", value must be real text to type — never "none" or empty.
- Never output the JSON literal `null` anywhere in your response. Use the
  string "none" instead, exactly as shown in the table.

═══════════════════════════════════════════
WORKED EXAMPLES (these are illustrative only — never copy the refs/values below,
always use the ACTUAL refs and content from the real Current State you are given)
═══════════════════════════════════════════
Example 1 — grounded click:
Current State shows: `[ref=e14] button "Add to Cart"`
Correct output:
{{"action": "click", "target": "e14", "value": "none"}}

Example 2 — search:
Current State shows: `[ref=e3] textbox "Search products"`
Goal: find wireless headphones
Correct output:
{{"action": "search", "target": "e3", "value": "wireless headphones"}}

Example 3 — no matching ref exists yet:
Goal: check today's weather in Paris
Current State: blank/unrelated page, no relevant elements
Correct output:
{{"action": "navigate", "target": "https://www.google.com/search?q=weather+in+paris", "value": "none"}}

Example 4 — goal already satisfied:
Current State main content clearly shows the requested information/result.
Correct output:
{{"action": "finish", "target": "none", "value": "true"}}

═══════════════════════════════════════════
USE "finish" WHEN
═══════════════════════════════════════════
- The goal is visibly satisfied in the Current State main content (not sidebar/nav) → value "true"
- A CAPTCHA or other unrecoverable block appears (NOT a login wall — you are
  already authenticated, so treat any login prompt as a rendering artifact,
  not a real block) → value "false"
- The same action would just repeat with no new information → value "false"

═══════════════════════════════════════════
OUTPUT SCHEMA (respond with exactly this, nothing else)
═══════════════════════════════════════════
{{"action": "<one of the 8 actions above>", "target": "<see table>", "value": "<see table>"}}

═══════════════════════════════════════════
BEFORE YOU RESPOND, SELF-CHECK (do this silently, do not output this checklist)
═══════════════════════════════════════════
1. Does my JSON have exactly three keys: action, target, value? If not, fix it.
2. Did I use the string "none" instead of null/empty anywhere it's required? If not, fix it.
3. If action is "search" or "type", is value a real, specific, non-empty string? If not, fix it.
4. If action is "click" or "type", does target match a ref VERBATIM from Current
   State? If not, change action to "navigate" instead.
5. Is my output ONLY the JSON object — no markdown fences, no explanation, no
   text before or after it?

═══════════════════════════════════════════
FINAL REMINDER
═══════════════════════════════════════════
- Output ONE JSON object with all three keys: action, target, value.
- Never output JSON `null` — use the string "none" for inapplicable fields.
- "target" for click/type must be copied verbatim from Current State — never fabricated.
- "search" and "type" must always have a real, non-empty value — never "none".
- If the same target/action was just attempted with no change in Current State,
  choose "finish" with value "false" instead of repeating it.
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