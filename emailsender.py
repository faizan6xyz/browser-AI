import re
import os
import time
matches = []
def find_and_read_snapshot_file(filename: str) -> str:
    matches.clear()
    current_dir = os.getcwd()
    while True:
        candidate = os.path.join(current_dir, ".playwright-mcp", filename)
        if os.path.exists(candidate):
            time.sleep(0.2)
            with open(candidate, "r", encoding="utf-8") as f:
                x = f.readlines()
                lines = [line.strip() for line in x if line.strip()]
                for i, line in enumerate(lines, 1):
                    if isinstance(line, str) and ("Send" in line and "[cursor=pointer]" in line and "options" not in line):
                        matches.append(line)
                return matches
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
    return ""
def ative(name ):
    text_list = find_and_read_snapshot_file(name)
    for item in text_list :
        if "Search" in item :
            match = re.search(r'ref=(\w+)', item)
            if match:
                search = match.group(1)
                print(search,"search")
        if "recipients" in item :
            match = re.search(r'ref=(\w+)', item)
            if match:
                recipients = match.group(1)
                print(recipients,"recipients")
        if "Subject" in item :
            match = re.search(r'ref=(\w+)', item)
            if match:
                Subject = match.group(1)
                print(Subject,"Subject")
        if "Body" in item :
            match = re.search(r'ref=(\w+)', item)
            if match:
                Body = match.group(1)
                print(Body,"Body")
  
            
          
if __name__ == "__main__": 
    tt = find_and_read_snapshot_file("page-2026-07-09T00-00-54-915Z.yml")
    print(tt)