from duckduckgo_search import DDGS
def search_web(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        output = []
        for r in results:
            output.append(
                f"Title: {r['title']}\n"
                f"URL:   {r['href']}\n"
                f"Info:  {r['body'][:400]}"
            )
        return "\n\n---\n\n".join(output)
    except Exception as e:
        return f"Search error: {e}"
def search_news(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        if not results:
            return "No news found."
        output = []
        for r in results:
            output.append(
                f"Title: {r['title']}\n"
                f"URL:   {r['url']}\n"
                f"Date:  {r['date']}\n"
                f"Info:  {r['body'][:400]}"
            )
        return "\n\n---\n\n".join(output)
    except Exception as e:
        return f"News search error: {e}"
def search_deep(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=8))
        if not results:
            return "No results found."
        output = []
        for r in results:
            output.append(
                f"Title: {r['title']}\n"
                f"URL:   {r['href']}\n"
                f"Info:  {r['body'][:600]}"   # more content per result
            )
        return "\n\n---\n\n".join(output)
    except Exception as e:
        return f"Deep search error: {e}"