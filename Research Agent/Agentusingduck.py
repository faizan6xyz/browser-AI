import json
import os
from duckduckgo_search import DDGS
from openai import OpenAI
from Toolsusingduck import search_deep , search_news , search_web
import sys
sys.path.append("..")  # path to the folder containing indexer.py
from Rag_create import build_index
client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = "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"
)
NIM_MODEL = "meta/llama-3.1-8b-instruct"
TOOLS = {
    "search_web":  lambda p: search_web(p["query"], int(p.get("max_results", 5))),
    "search_deep": lambda p: search_deep(p["query"]),
    "search_news": lambda p: search_news(p["query"], int(p.get("max_results", 5))),
}
SYSTEM_PROMPT = """
You are an expert research agent. Your job is to research topics thoroughly 
and produce detailed, well-structured markdown reports that preserve ALL important information.

You have access to these tools:

1. search_web(query, max_results)   — quick broad search, use first
2. search_deep(query)               — deeper search, more content per result  
3. search_news(query, max_results)  — recent news only

═══════════════════════════════════════════
RESEARCH STRATEGY — always follow this order:
═══════════════════════════════════════════

Step 1: Start with search_web to get a broad overview
Step 2: Identify ALL key sub-topics, facts, stats, names, dates from results
Step 3: Use search_deep on EACH important sub-topic (minimum 3-4 deep searches)
Step 4: Use search_news for recent developments
Step 5: Cross-reference facts across multiple sources
Step 6: Only write the final report after at least 5-6 searches

═══════════════════════════════════════════
DATA PRESERVATION RULES — critical, never skip:
═══════════════════════════════════════════

ALWAYS KEEP:
- All statistics, numbers, percentages, dates, and figures
- All names (people, organizations, places, products)
- All technical terms and their explanations
- Cause-and-effect relationships
- Conflicting viewpoints or debates
- Direct quotes that add value
- Step-by-step processes or timelines
- Source URLs for every major claim

ONLY REMOVE:
- Duplicate information that appears across multiple sources
- Obvious filler sentences ("Click here to read more", "Subscribe to our newsletter")
- Advertisements or promotional content
- Repeated boilerplate text from websites
- Off-topic tangents unrelated to the research query

═══════════════════════════════════════════
TOOL CALL FORMAT — respond EXACTLY like this:
═══════════════════════════════════════════

TOOL: tool_name
INPUT: {"param": "value"}

═══════════════════════════════════════════
FINAL REPORT FORMAT — use this structure:
═══════════════════════════════════════════

FINAL ANSWER:
# [Topic] — Research Report

## Overview
[Comprehensive 4-5 paragraph summary — no detail left out]

## Background & Context
[History, origin, why this topic matters]

## Key Findings
[All major facts, stats, figures — use bullet points with sources]
- Finding 1 (Source: url)
- Finding 2 (Source: url)

## Deep Dive: [Sub-topic 1]
[Detailed section — preserve all technical details, numbers, names]

## Deep Dive: [Sub-topic 2]
[Detailed section — preserve all technical details, numbers, names]

## Conflicting Views / Debates
[If sources disagree, present ALL sides with evidence]

## Recent Developments
[Latest news with dates — be specific, not vague]

## Key Takeaways
[5-10 bullet points summarizing the most critical information]

## Sources
- [Source Title](url) — what information was taken from here
- [Source Title](url) — what information was taken from here

═══════════════════════════════════════════
REPORT QUALITY RULES:
═══════════════════════════════════════════

1. NEVER summarize away important details — if a source has a specific 
   stat or fact, include it exactly
2. NEVER use vague language like "some studies show" — always cite which study
3. NEVER shorten sections just to make the report look clean
4. Each section should be as long as the information requires
5. If two sources contradict each other, include BOTH and flag the conflict
6. Minimum report length: 800 words — if shorter, you missed important details
7. More detail is always better than less detail
"""
def parse_response(text: str):
    if "FINAL ANSWER:" in text:
        return "final", text.split("FINAL ANSWER:")[-1].strip()
    if "TOOL:" in text and "INPUT:" in text:
        tool   = text.split("TOOL:")[-1].split("\n")[0].strip()
        input_ = text.split("INPUT:")[-1].split("\n")[0].strip()
        return "tool", (tool, input_)
    return "unknown", text
def save_report(topic: str, content: str):
    folder = "SYSTEM/data"
    filename = topic[:40].replace(" ", "_") + "_report.md"
    filepath = os.path.join(folder, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Research Report: {topic}\n\n")
        f.write(content)
    print(f"\n Report saved → {filename}")
    build_index(filename)
    print("seach saved into the vector DB")
    return filename
def run_research_agent(topic: str, max_steps: int = 15):
    print(f"\n Researching: {topic}")
    print("=" * 50)
    messages     = [{"role": "user", "content": f"Research this topic thoroughly: {topic}"}]
    search_count = 0
    for step in range(max_steps):
        print(f"\n--- Step {step + 1} ---")
        response = client.chat.completions.create(
            model=NIM_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            max_tokens=2000,
            temperature=0.4
        )
        reply = response.choices[0].message.content
        action_type, action_data = parse_response(reply)
        if action_type == "final":
            print("\n" + "=" * 50)
            print(" FINAL REPORT READY")
            print("=" * 50)
            print(action_data)
            save_report(topic, action_data)
            return action_data
        elif action_type == "tool":
            tool_name, tool_input = action_data
            try:
                params = json.loads(tool_input)
                query  = params.get("query", "")
                print(f" [{tool_name}] → '{query}'")
                result = TOOLS[tool_name](params)
                search_count += 1
                print(f" Got results ({search_count} searches done)")
            except Exception as e:
                result = f"Tool error: {e}"
                print(f" Error: {e}")
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user",      "content": f"Search result:\n{result}"})
        else:
            # Agent said something but didn't use a tool or finish , push it to continue
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user",      "content": "Continue your research using the tools."})
    print("\n Max steps reached — forcing final report.")
    return None
if __name__ == "__main__":
    while True:
        prompt = input("Enter the query for research (or 'exit' to quit): ")
        if prompt.lower() == "exit":
            print("Goodbye!")
            break
        run_research_agent(prompt)
