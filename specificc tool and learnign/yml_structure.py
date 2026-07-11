import re
listt=[]
search = chat = send  = message = scroll = None
uploader = "malik_esticxs"

def username(filename):
    listt.clear()
    global search , chat , send , message , scroll
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis :        
        if 'link' in item and 'profile picture' in item and '[cursor=pointer]' in item and "dontstockbitch" not in item and uploader not in item:
            pattern = r'link \"([^"]+)\''
            match = re.search(pattern, item)
            if match:
                full_content = match.group(1) 
                username = full_content.split("'s")[0]
                listt.append(username) 
    return list(set(listt)) # return the unique
                
def searchref(filename):
    global search
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis : 
        if 'textbox' in item :
            match = re.search(r'ref=(\w+)', item)
            if match:
                search = match.group(1)
                return search
                
def messageref(filename):
    global message
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
                message = match.group(1)
                return message
                
def chatref(filename):
    global chat
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
            
def sendref(filename):
    global send
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis :
        if "Send" in item and "send" in item and "[cursor=pointer]" in item :
            item.strip()
            pattern = r'\[ref=([a-zA-Z0-9]+)\]'
            match = re.search(pattern, item)
            if match:
                send = match.group(1)
                return send


def scrollref(filename):
    lastvalue = "none"
    flag = True
    if not  filename :  
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    for item in lis:
        if flag :
            if 'link' in item and 'profile picture' in item and 'malik_esticxs'not  in item and "dontstockbitch" not in item:
                flag = False
                prev.strip()
                pattern = r'\[ref=([a-zA-Z0-9]+)\]'
                match = re.search(pattern, prev)
                if match:
                    scroll = match.group(1)
                    return scroll
            prev = lastvalue 
            lastvalue = item
        
if __name__ == "__main__":
    print(username('.playwright-mcp/x.yml'))
