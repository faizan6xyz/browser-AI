import re
listt=[]
def username(filename):
    listt.clear()
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
                
        
def search(filename):
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis :     
        if 'textbox' in item :
            match = re.search(r'ref=(\w+)', item)
            if match:
                chat = match.group(1)
                return chat
            
def message(filename):
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis :
        if "                - button" in item and "[cursor=pointer]" in item :
            item.strip()
            pattern = r'\[ref=([a-zA-Z0-9]+)\]'
            match = re.search(pattern, item)
            if match:
                chat = match.group(1)
                return chat

def chattype(filename):
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis :
        if "                - textbox [active]" in item :
            item.strip()
            pattern = r'\[ref=([a-zA-Z0-9]+)\]'
            match = re.search(pattern, item)
            if match:
                chat = match.group(1)
                return chat
            
# username(r".playwright-mcp/x.yml")
# print(listt)
# print(search(r".playwright-mcp/y.yml"))
# print(message(r".playwright-mcp/y.yml"))
print(chattype(r".playwright-mcp/y.yml"))