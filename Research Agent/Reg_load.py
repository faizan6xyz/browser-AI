import os
import re
import numpy as np
import faiss
import pickle
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi
HF_CACHE = r"C:\Users\faiza\.cache\huggingface\hub"
os.environ["HF_HOME"] = HF_CACHE
os.environ["FASTEMBED_CACHE_PATH"] = HF_CACHE
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_PATH = "SYSTEM/RAG_data"
INDEX_PATH = os.path.join(CHUNK_PATH, "rag_index.faiss")
CHUNKS_PATH = os.path.join(CHUNK_PATH, "chunks.npy")
META_PATH = os.path.join(CHUNK_PATH, "metadata.npy")
BM25_PATH = os.path.join(CHUNK_PATH, "bm25.pkl")
print(f"Initializing RAG System from local cache: {HF_CACHE}...")
model = TextEmbedding(model_name=MODEL_NAME, local_files_only=True)
print("Model loaded successfully.")
if not os.path.exists(INDEX_PATH):
    raise FileNotFoundError("FAISS index not found. Please run Rag_create.py first.")
index = faiss.read_index(INDEX_PATH)
all_chunks = np.load(CHUNKS_PATH, allow_pickle=True).tolist()
print(f"Loaded {len(all_chunks)} chunks from chunks.npy")
if os.path.exists(META_PATH):
    all_metadata = np.load(META_PATH, allow_pickle=True).tolist()
else:
    all_metadata = [{"source": "unknown", "chunk_id": i} for i in range(len(all_chunks))]
if index.ntotal != len(all_chunks):
    raise ValueError(
        f"Mismatch between FAISS index ({index.ntotal} vectors) and "
        f"chunks.npy ({len(all_chunks)} chunks). Rebuild the index."
    )
if os.path.exists(BM25_PATH):
    with open(BM25_PATH, 'rb') as f:
        bm25 = pickle.load(f)
    print("BM25 index loaded from disk.")
else:
    print("Rebuilding BM25 index...")
    def tokenize(text: str):
        return re.findall(r"\w+", text.lower())
    tokenized_chunks = [tokenize(chunk) for chunk in all_chunks]
    bm25 = BM25Okapi(tokenized_chunks)
def embed_text(text: str) -> np.ndarray:
    return np.array(list(model.embed([text])), dtype=np.float32)
def retrieve(query: str, k: int = 5, rrf_k: int = 60):
    n = len(all_chunks)
    # 1. Dense Search (Vector)
    query_embedding = embed_text(query)
    faiss.normalize_L2(query_embedding)
    dense_scores, dense_indices = index.search(query_embedding, k=n)
    dense_indices = dense_indices[0]
    # 2. Sparse Search (BM25)
    def tokenize(text: str):
        return re.findall(r"\w+", text.lower())
    tokenized_query = tokenize(query)
    bm25_scores = bm25.get_scores(tokenized_query)
    bm25_ranked_indices = np.argsort(bm25_scores)[::-1]
    # 3. Reciprocal Rank Fusion (RRF)
    rrf_scores = np.zeros(n)
    for rank, idx in enumerate(dense_indices):
        rrf_scores[idx] += 1.0 / (rrf_k + rank + 1)
    for rank, idx in enumerate(bm25_ranked_indices):
        rrf_scores[idx] += 1.0 / (rrf_k + rank + 1)
    # 4. Final Top-K
    top_indices = np.argsort(rrf_scores)[::-1][:k]
    results = [
        {
            "text": all_chunks[idx],
            "score": float(rrf_scores[idx]),
            "source": all_metadata[idx].get("source", "unknown"),
            "chunk_id": all_metadata[idx].get("chunk_id", idx),
        }
        for idx in top_indices if rrf_scores[idx] > 0
    ]
    return results
if __name__ == "__main__":
    query = "your test query here"
    results = retrieve(query, k=5)