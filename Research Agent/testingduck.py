from duckduckgo_search import DDGS
with DDGS() as ddgs:
    results = list(ddgs.text("what is RAG in AI", max_results=3))
    for r in results:
        print(r['title'])
        print(r['href'])
        print(r['body'][:200])
