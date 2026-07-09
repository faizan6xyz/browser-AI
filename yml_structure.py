import re
def new(filename):
    listt=[]
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis :        
        if 'link' in item and 'profile picture' in item and '[cursor=pointer]' in item and "dontstockbitch" not in item:
            pattern = r'link \"([^"]+)\''
            match = re.search(pattern, item)
            if match:
                full_content = match.group(1) 
                username = full_content.split("'s")[0]
                listt.append(username)
    return listt
        
        
print(new(r".playwright-mcp/page-2026-07-09T22-41-34-999Z.yml"))