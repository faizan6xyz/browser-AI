import re
listt=[]
search = chattype = send  = message = "none"

def insta(filename):
    listt.clear()
    search = chattype = send  = message = "none"
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
        if 'textbox' in item :
            match = re.search(r'ref=(\w+)', item)
            if match:
                search = match.group(1)
        if "                - button" in item and "[cursor=pointer]" in item :
            item.strip()
            pattern = r'\[ref=([a-zA-Z0-9]+)\]'
            match = re.search(pattern, item)
            if match:
                message = match.group(1)
        if "                - textbox [active]" in item :
            item.strip()
            pattern = r'\[ref=([a-zA-Z0-9]+)\]'
            match = re.search(pattern, item)
            if match:
                chat = match.group(1)
        if "Send" in item and "send" in item and "[cursor=pointer]" in item :
            item.strip()
            pattern = r'\[ref=([a-zA-Z0-9]+)\]'
            match = re.search(pattern, item)
            if match:
                send = match.group(1)

if __name__ == "__main__":
    insta('.playwright-mcp/x.yml')