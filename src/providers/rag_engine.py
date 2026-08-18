"""
Local RAG Engine backed by persistent ChromaDB Vector Store (rag/chroma_db)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
from src.core.config import ROOT_DIR, RAG_DIR, DEFAULT_EMBEDDING_MODEL
from src.providers.rag_exporter import export_hr_rag_file, get_stored_rag_summary


class LocalCriteriaRAG:
    """
    Local RAG Criteria Engine backed by persistent ChromaDB Vector Store (rag/chroma_db).
    Decomposes HR Standard Requirements & Hidden Requirements into 5 dimensions using LLM,
    stores them persistently in ChromaDB vector collection with metadata tags,
    and performs semantic similarity vector retrieval with category metadata filtering.
    """
    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
        self._lock = threading.Lock()
        self.documents: List[Dict[str, Any]] = []
        self.model = None
        self.embedding_type = "dense"
        self.db_dir = RAG_DIR
        os.makedirs(self.db_dir, exist_ok=True)
        self.db_path = os.path.join(self.db_dir, "chroma_db")

        self.chroma_client = None
        self.collection = None

        self._init_chroma_db()

        try:
            from sentence_transformers import SentenceTransformer
            print(f"[LocalRAG] Loading embedding model: {model_name}", file=sys.stderr)
            try:
                self.model = SentenceTransformer(model_name)
            except Exception as load_err:
                print(f"[LocalRAG Warning] Direct load failed ({load_err}). Retrying with local_files_only=True...", file=sys.stderr)
                self.model = SentenceTransformer(model_name, local_files_only=True)
        except Exception as e:
            print(f"[LocalRAG Warning] SentenceTransformer model unavailable ({e}). Using mock/text fallback mode.", file=sys.stderr)
            self.model = None

        self.load_from_db()

    def _init_chroma_db(self):
        """Initializes persistent ChromaDB client and collection. Falls back to mock in-memory store if unavailable."""
        try:
            import chromadb
            self.chroma_client = chromadb.PersistentClient(path=self.db_path)
            self.collection = self.chroma_client.get_or_create_collection(
                name="criteria_rag",
                metadata={"hnsw:space": "cosine"}
            )
            print(f"[LocalRAG] ChromaDB vector store initialized at {self.db_path}", file=sys.stderr)
        except Exception as e:
            print(f"[LocalRAG Warning] ChromaDB not available ({e}). Using mock/in-memory RAG store fallback.", file=sys.stderr)
            self.chroma_client = None
            self.collection = None

    def load_from_db(self):
        """Loads pre-stored criteria from persistent ChromaDB collection or persistent JSON backup."""
        self.documents = []
        if self.collection is not None:
            try:
                results = self.collection.get(include=["documents", "metadatas", "embeddings"])
                if results and results.get("documents"):
                    docs = results["documents"]
                    metas = results.get("metadatas", [])
                    ids = results.get("ids", [])
                    embs = results.get("embeddings") if results.get("embeddings") is not None else []
                    for idx, text in enumerate(docs):
                        meta = metas[idx] if idx < len(metas) and metas[idx] else {}
                        doc_id = ids[idx] if idx < len(ids) else f"doc_{idx}"
                        doc_obj = {
                            "id": doc_id,
                            "text": text,
                            "category": meta.get("category", "unknown"),
                            "type": meta.get("type", "standard")
                        }
                        if idx < len(embs) and embs[idx] is not None:
                            doc_obj["embedding"] = embs[idx]
                        self.documents.append(doc_obj)
                    print(f"[LocalRAG] Loaded {len(self.documents)} persistent requirement criteria items from ChromaDB collection ({self.db_path}).", file=sys.stderr)
                    self._compute_embeddings()
            except Exception as e:
                print(f"[LocalRAG ChromaDB Error] Failed to load from collection: {e}", file=sys.stderr)
        else:
            json_path = os.path.join(self.db_dir, "criteria_rag.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        saved_docs = json.load(f)
                    if isinstance(saved_docs, list):
                        self.documents = saved_docs
                        print(f"[LocalRAG] Loaded {len(self.documents)} persistent requirement criteria items from file backup ({json_path}).", file=sys.stderr)
                        self._compute_embeddings()
                except Exception as e:
                    print(f"[LocalRAG Error] Failed to load fallback JSON: {e}", file=sys.stderr)

    def has_stored_rag(self) -> bool:
        """Returns True if ChromaDB or fallback storage contains stored requirement criteria."""
        return len(self.documents) > 0

    def clear_rag_database(self):
        """Clears all stored RAG criteria from persistent ChromaDB collection/file backup and deletes hr_rag.txt."""
        self.documents = []
        if self.chroma_client is not None:
            try:
                self.chroma_client.delete_collection(name="criteria_rag")
                self.collection = self.chroma_client.get_or_create_collection(
                    name="criteria_rag",
                    metadata={"hnsw:space": "cosine"}
                )
                print(f"[LocalRAG] Cleared all RAG criteria from persistent ChromaDB collection ({self.db_path}).", file=sys.stderr)
            except Exception as e:
                print(f"[LocalRAG ChromaDB Error] Failed to clear collection: {e}", file=sys.stderr)

        json_path = os.path.join(self.db_dir, "criteria_rag.json")
        if os.path.exists(json_path):
            try:
                os.remove(json_path)
            except Exception as e:
                print(f"[LocalRAG Warning] Could not remove criteria_rag.json: {e}", file=sys.stderr)

        hr_rag_path = os.path.join(ROOT_DIR, "hr_rag.txt")
        if os.path.exists(hr_rag_path):
            try:
                os.remove(hr_rag_path)
            except Exception as e:
                print(f"[LocalRAG Warning] Could not remove hr_rag.txt: {e}", file=sys.stderr)

    def get_stored_rag_summary(self) -> Dict[str, Any]:
        """Returns a structured summary of all RAG criteria stored in the persistent database."""
        return get_stored_rag_summary(self)

    def ingest_requirements(self, standard_req: str, hidden_req: str, llm_decomposer_func=None, force_reingest: bool = False):
        """
        Decomposes HR text into atomic criteria chunks with category tags using LLM.
        """
        with self._lock:
            standard_req = (standard_req or "").strip()
            hidden_req = (hidden_req or "").strip()

            if not force_reingest and self.has_stored_rag():
                print(f"[LocalRAG] Reusing persistent ChromaDB database ({len(self.documents)} items in {self.db_path}). SKIPPING LLM requirement categorization step!", file=sys.stderr)
                return

            self.clear_rag_database()

            if not standard_req and not hidden_req:
                print("[LocalRAG] No HR requirements or hidden requirements provided. Documents list will be empty.", file=sys.stderr)
                return

            if llm_decomposer_func is None:
                raise RuntimeError("[LocalRAG Error] llm_decomposer_func is required for requirement decomposition.")

            print("[LocalRAG] Using LLM requirement decomposer...", file=sys.stderr)
            try:
                decomposed = llm_decomposer_func(standard_req, hidden_req)
            except Exception as e:
                raise RuntimeError(f"[LocalRAG Error] LLM requirement decomposition failed: {e}") from e

            if decomposed is None or not isinstance(decomposed, dict):
                raise RuntimeError("[LocalRAG Error] LLM requirement decomposition returned invalid or unparseable result.")

            now_str = datetime.now().isoformat()
            ids = []
            documents = []
            metadatas = []
            item_counter = 0

            for cat, items in decomposed.items():
                if isinstance(items, list):
                    for item in items:
                        cleaned_item = str(item).strip()
                        if cleaned_item:
                            item_counter += 1
                            doc_id = f"crit_{cat}_{item_counter}"
                            req_type = "hidden" if cat == "hidden_culture" else "standard"
                            
                            doc_obj = {
                                "id": doc_id,
                                "text": cleaned_item,
                                "category": cat,
                                "type": req_type
                            }
                            self.documents.append(doc_obj)
                            
                            ids.append(doc_id)
                            documents.append(cleaned_item)
                            metadatas.append({"category": cat, "type": req_type, "created_at": now_str})

            embeddings = []
            if self.model and documents:
                try:
                    dense_embeddings = self.model.encode(documents)
                    embeddings = dense_embeddings.tolist() if hasattr(dense_embeddings, "tolist") else [e.tolist() for e in dense_embeddings]
                    for idx, emb in enumerate(dense_embeddings):
                        if idx < len(self.documents):
                            self.documents[idx]["embedding"] = emb
                except Exception as e:
                    print(f"[LocalRAG Embedding Error] {e}", file=sys.stderr)

            if self.collection is not None and documents:
                try:
                    add_kwargs = {
                        "ids": ids,
                        "documents": documents,
                        "metadatas": metadatas
                    }
                    if embeddings:
                        add_kwargs["embeddings"] = embeddings
                    self.collection.add(**add_kwargs)
                    print(f"[LocalRAG] Successfully ingested & stored {len(documents)} requirement vector embeddings into ChromaDB collection.", file=sys.stderr)
                except Exception as e:
                    print(f"[LocalRAG ChromaDB Error] Failed to insert criteria into ChromaDB collection: {e}", file=sys.stderr)
            else:
                json_path = os.path.join(self.db_dir, "criteria_rag.json")
                try:
                    clean_docs = [{k: v for k, v in d.items() if k != "embedding"} for d in self.documents]
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(clean_docs, f, ensure_ascii=False, indent=2)
                    print(f"[LocalRAG] Saved {len(clean_docs)} criteria items to fallback persistence ({json_path}).", file=sys.stderr)
                except Exception as e:
                    print(f"[LocalRAG Error] Failed to write fallback JSON: {e}", file=sys.stderr)

            self.export_hr_rag_file(standard_req, hidden_req, decomposed)

    def export_hr_rag_file(self, standard_req: str, hidden_req: str, decomposed: Dict[str, List[str]], output_path: str = "hr_rag.txt"):
        """Exports a summary detailing how HR requirements are classified into 5 RAG dimensions."""
        export_hr_rag_file(standard_req, hidden_req, decomposed, output_path)

    def _compute_embeddings(self):
        if self.model and self.documents:
            try:
                unembedded_docs = [doc for doc in self.documents if "embedding" not in doc]
                if unembedded_docs:
                    texts = [doc["text"] for doc in unembedded_docs]
                    embeddings = self.model.encode(texts)
                    for idx, doc in enumerate(unembedded_docs):
                        doc["embedding"] = embeddings[idx]
            except Exception as e:
                raise RuntimeError(f"[LocalRAG Fatal Error] Embedding computation failed: {e}") from e

    def retrieve(self, category: str, query: str, top_k: int = 3) -> List[str]:
        """
        Retrieves criteria items using ChromaDB vector search, dense cosine similarity, or in-memory fallback.
        """
        query = query or ""

        if self.collection is not None and self.collection.count() > 0:
            try:
                query_kwargs = {
                    "where": {"category": category},
                    "n_results": top_k
                }
                if self.model:
                    query_emb = self.model.encode(query)
                    query_emb_list = query_emb.tolist() if hasattr(query_emb, "tolist") else query_emb
                    query_kwargs["query_embeddings"] = [query_emb_list]
                else:
                    query_kwargs["query_texts"] = [query]

                results = self.collection.query(**query_kwargs)
                if results and results.get("documents") and len(results["documents"]) > 0:
                    retrieved_texts = results["documents"][0]
                    if retrieved_texts:
                        return retrieved_texts
            except Exception as e:
                print(f"[LocalRAG Warning] ChromaDB vector retrieval failed ({e}). Falling back to in-memory store.", file=sys.stderr)

        filtered_docs = [doc for doc in self.documents if doc.get("category") == category]
        
        if not filtered_docs:
            return []

        if self.model:
            try:
                import torch
                from sentence_transformers import util

                valid_docs = [doc for doc in filtered_docs if "embedding" in doc]
                if valid_docs:
                    query_embedding = self.model.encode(query, convert_to_tensor=True)
                    doc_embeddings = torch.stack([
                        doc["embedding"] if isinstance(doc["embedding"], torch.Tensor)
                        else torch.tensor(doc["embedding"])
                        for doc in valid_docs
                    ]).to(query_embedding.device)
                    scores = util.cos_sim(query_embedding, doc_embeddings)
                    if scores.dim() > 1:
                        scores = scores[0]
                    
                    scored_docs = sorted(zip(scores.tolist(), valid_docs), key=lambda x: x[0], reverse=True)
                    return [doc["text"] for score, doc in scored_docs[:top_k]]
            except Exception as e:
                print(f"[LocalRAG Warning] Dense vector similarity calculation failed ({e}). Returning un-scored items.", file=sys.stderr)

        # In-memory mock/text fallback
        return [doc["text"] for doc in filtered_docs[:top_k]]
