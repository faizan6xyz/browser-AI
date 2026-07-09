def new(filename):
    if not  filename :
        print("empty snapshot")
    with open(filename , "r", encoding="utf-8") as f :
        lis = [item for item in f.readlines()]
    return lis
        
        
print(new(r".playwright-mcp/page-2026-07-09T22-41-34-999Z.yml"))