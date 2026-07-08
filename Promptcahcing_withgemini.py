from google import genai
client = genai.Client(api_key="YOUR_GEMINI_API_KEY")
model_id = "gemini-2.5-flash"

# Create the cache once (your long/static instructions or reference doc)
cache = client.caches.create(
    model=model_id,
    config=genai.types.CreateCachedContentConfig(
        display_name="my-app-instructions",
        system_instruction="You are an assistant for my app. Always respond in JSON...",
        contents=[your_long_reference_doc],  # optional big context
    )
)

# Reuse it on every call — only your new question is billed at full price
response = client.models.generate_content(
    model=model_id,
    contents="Now handle this specific request: ...",
    config={"cached_content": cache.name}
)