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
from src.core.config import ROOT_DIR, RAG_DIR, DEFAULT_EMBEDDING_MODEL, HR_CHECK_ITEMS_KEY, DEFAULT_IMPORTANCE
from src.core.importance import normalize_importance, split_criterion_item, base_weight
from src.providers.rag_exporter import export_hr_rag_file, get_stored_rag_summary

# Evaluation never builds or changes the HR RAG: HR sets it on the RAG page first, so HR controls exactly what counts
NO_HR_RAG_MESSAGE = (
    "No HR RAG is stored. Set the HR requirements on the website's RAG page (decompose them and review the "
    "Criteria) before running an evaluation; evaluation never builds or changes the HR RAG."
)

# A Nice-to-have only adds bonus points on top of a Category's Must-have and Standard Criteria (docs/adr/0014)
BONUS_ONLY_CATEGORY_MESSAGE = (
    "A Category's Criteria are all Nice-to-have (Ưu tiên). Give it at least one Must-have or Standard Criterion "
    "on the website's RAG page"
)
# Each Verdict finds its Criterion by exact text, so two Criteria with one text in a Category would share a Verdict
DUPLICATE_CRITERION_MESSAGE = "A Category has the same Criterion text twice. Delete or reword one on the website's RAG page"


def hr_rag_problem(categories: Dict[str, List[Any]]) -> str:
    """
    Why a set of Criteria ({category: [criterion]}, each a string or {"text", "importance"}) can't be scored, or ''
    when it can: a Category whose Criteria are all Nice-to-have, or the same text twice in one Category. Blank
    Criteria and HR Check Items are ignored, as they are never stored as Criteria.
    """
    bonus_only, duplicated = [], []
    for cat, items in (categories or {}).items():
        if cat == HR_CHECK_ITEMS_KEY or not isinstance(items, list):
            continue
        criteria = [c for c in (split_criterion_item(item) for item in items) if c[0]]
        if criteria and base_weight(importance for _, importance in criteria) == 0:
            bonus_only.append(cat)
        if len({text for text, _ in criteria}) < len(criteria):
            duplicated.append(cat)
    problems = []
    if bonus_only:
        problems.append(f"{BONUS_ONLY_CATEGORY_MESSAGE} ({', '.join(bonus_only)}).")
    if duplicated:
        problems.append(f"{DUPLICATE_CRITERION_MESSAGE} ({', '.join(duplicated)}).")
    return " ".join(problems)


# Set on every Criterion saved since only HR sets Importance. A saved Criterion without it has an Importance the
# decomposer proposed, which HR may never have reviewed, and a Must-have now rejects candidates (docs/adr/0011)
IMPORTANCE_SET_BY_HR_KEY = "importance_set_by_hr"


def stored_criteria_count() -> int:
    """Items (Criteria and HR Check Items) in the stored HR RAG, read without loading the embedding model."""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=os.path.join(RAG_DIR, "chroma_db"))
        return client.get_or_create_collection(name="criteria_rag", metadata={"hnsw:space": "cosine"}).count()
    except Exception:
        json_path = os.path.join(RAG_DIR, "criteria_rag.json")
        if not os.path.exists(json_path):
            return 0
        with open(json_path, "r", encoding="utf-8") as f:
            saved_docs = json.load(f)
        return len(saved_docs) if isinstance(saved_docs, list) else 0


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
        # HR's original Standard/Hidden Requirements text, kept beside the Criteria so a
        # manual update that omits the text can still write it into hr_rag.txt.
        self.originals_path = os.path.join(self.db_dir, "original_requirements.json")

        self.chroma_client = None
        self.collection = None

        self._init_chroma_db()

        try:
            from sentence_transformers import SentenceTransformer
            print(f"[LocalRAG] Loading embedding model: {model_name} (CPU)", file=sys.stderr)
            # CPU on purpose: vLLM reserves most of the GPU up front, and embedding short Criteria queries
            # on the GPU alongside it ran out of memory and silently degraded retrieval to unranked Criteria
            try:
                self.model = SentenceTransformer(model_name, device="cpu")
            except Exception as load_err:
                print(f"[LocalRAG Warning] Direct load failed ({load_err}). Retrying with local_files_only=True...", file=sys.stderr)
                self.model = SentenceTransformer(model_name, device="cpu", local_files_only=True)
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
                        # HR Check Items are never scored, so they carry no Importance
                        if doc_obj["category"] != HR_CHECK_ITEMS_KEY:
                            doc_obj["importance"] = normalize_importance(meta.get("importance"))
                            doc_obj[IMPORTANCE_SET_BY_HR_KEY] = meta.get(IMPORTANCE_SET_BY_HR_KEY) is True
                        if idx < len(embs) and embs[idx] is not None:
                            doc_obj["embedding"] = embs[idx]
                        self.documents.append(doc_obj)
                    print(f"[LocalRAG] Loaded {len(self.documents)} persistent requirement criteria items from ChromaDB collection ({self.db_path}).", file=sys.stderr)
                    self._compute_embeddings()
            except Exception as e:
                print(f"[LocalRAG ChromaDB Error] Failed to load from collection: {e}", file=sys.stderr)
            self._reset_proposed_importance()
        else:
            json_path = os.path.join(self.db_dir, "criteria_rag.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        saved_docs = json.load(f)
                    if isinstance(saved_docs, list):
                        self.documents = saved_docs
                        for doc in self.documents:
                            if isinstance(doc, dict) and doc.get("category") != HR_CHECK_ITEMS_KEY:
                                doc["importance"] = normalize_importance(doc.get("importance"))
                        print(f"[LocalRAG] Loaded {len(self.documents)} persistent requirement criteria items from file backup ({json_path}).", file=sys.stderr)
                        self._compute_embeddings()
                except Exception as e:
                    print(f"[LocalRAG Error] Failed to load fallback JSON: {e}", file=sys.stderr)
                self._reset_proposed_importance()

    def _reset_proposed_importance(self):
        """
        Once per HR RAG saved before only HR set Importance: every Criterion goes back to Standard and the HR RAG is
        saved again (with IMPORTANCE_SET_BY_HR_KEY), so a Must-have the decomposer proposed never rejects anyone.
        HR then marks the real Must-haves on the RAG page.
        """
        legacy = any(
            isinstance(doc, dict) and doc.get("category") != HR_CHECK_ITEMS_KEY
            and doc.get(IMPORTANCE_SET_BY_HR_KEY) is not True
            and doc.get("importance", DEFAULT_IMPORTANCE) != DEFAULT_IMPORTANCE
            for doc in self.documents
        )
        if not legacy:
            return
        # Plain strings read as Standard; the category order is kept as stored
        categories: Dict[str, List[Any]] = {}
        for doc in self.documents:
            if isinstance(doc, dict) and doc.get("text"):
                categories.setdefault(doc.get("category"), []).append(doc["text"])
        originals = self.load_original_requirements()
        print("[LocalRAG] Resetting every Criterion's Importance to Standard: the stored HR RAG predates HR-only Importance.", file=sys.stderr)
        self.ingest_decomposed_dict(categories, originals["standard_requirements"], originals["hidden_requirements"])

    def has_stored_rag(self) -> bool:
        """Returns True if ChromaDB or fallback storage contains stored requirement criteria."""
        return len(self.documents) > 0

    def require_stored_rag(self):
        """
        Raises RuntimeError(NO_HR_RAG_MESSAGE) unless HR has set the HR RAG, and a RuntimeError when its Criteria
        can't be scored (hr_rag_problem). Saving already refuses such a set; this catches one stored before.
        """
        if not self.has_stored_rag():
            raise RuntimeError(NO_HR_RAG_MESSAGE)
        with self._lock:
            categories: Dict[str, List[Any]] = {}
            for doc in self.documents:
                categories.setdefault(doc.get("category"), []).append(doc)
        problem = hr_rag_problem(categories)
        if problem:
            raise RuntimeError(problem)

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

        if os.path.exists(self.originals_path):
            try:
                os.remove(self.originals_path)
            except Exception as e:
                print(f"[LocalRAG Warning] Could not remove original_requirements.json: {e}", file=sys.stderr)

    def load_original_requirements(self) -> Dict[str, str]:
        """Returns HR's stored original Standard/Hidden Requirements text (empty strings if none)."""
        originals = {"standard_requirements": "", "hidden_requirements": ""}
        if os.path.exists(self.originals_path):
            try:
                with open(self.originals_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    for key in originals:
                        originals[key] = str(saved.get(key) or "")
            except Exception as e:
                print(f"[LocalRAG Warning] Could not read original_requirements.json: {e}", file=sys.stderr)
        return originals

    def _save_original_requirements(self, standard_req: str, hidden_req: str):
        try:
            with open(self.originals_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"standard_requirements": standard_req or "", "hidden_requirements": hidden_req or ""},
                    f, ensure_ascii=False, indent=2
                )
        except Exception as e:
            print(f"[LocalRAG Error] Failed to write original_requirements.json: {e}", file=sys.stderr)

    def get_stored_rag_summary(self) -> Dict[str, Any]:
        """Returns a structured summary of all RAG criteria stored in the persistent database."""
        return get_stored_rag_summary(self)

    def ingest_decomposed_dict(self, decomposed: Dict[str, List[Any]], standard_req: str = "", hidden_req: str = ""):
        """
        Ingests a decomposed dictionary mapping category names to lists of criteria directly into RAG.
        Each Criterion is a plain string (read as Standard) or {"text": ..., "importance": ...}; HR Check Items
        keep only their text. Updates ChromaDB / fallback storage, recomputes vector embeddings, and generates hr_rag.txt.
        """
        with self._lock:
            self.clear_rag_database()
            if not decomposed or not isinstance(decomposed, dict):
                print("[LocalRAG] Decomposed criteria dictionary is empty.", file=sys.stderr)
                return

            self._save_original_requirements(standard_req, hidden_req)

            now_str = datetime.now().isoformat()
            ids = []
            documents = []
            metadatas = []
            item_counter = 0
            # The same items with Importance resolved, written to hr_rag.txt
            normalized: Dict[str, List[Any]] = {}

            for cat, items in decomposed.items():
                if isinstance(items, list):
                    normalized[cat] = []
                    # The decomposer can repeat a text; HR's saves are refused with one (hr_rag_problem)
                    seen_texts = set()
                    for item in items:
                        cleaned_item, importance = split_criterion_item(item)
                        if cleaned_item and cleaned_item not in seen_texts:
                            seen_texts.add(cleaned_item)
                            item_counter += 1
                            doc_id = f"crit_{cat}_{item_counter}"
                            if cat == HR_CHECK_ITEMS_KEY:
                                req_type = "hr_check"
                            else:
                                req_type = "hidden" if cat == "hidden_culture" else "standard"
                            
                            doc_obj = {
                                "id": doc_id,
                                "text": cleaned_item,
                                "category": cat,
                                "type": req_type
                            }
                            meta = {"category": cat, "type": req_type, "created_at": now_str}
                            # HR Check Items are never scored, so they carry no Importance (ADR 0004)
                            if cat == HR_CHECK_ITEMS_KEY:
                                normalized[cat].append(cleaned_item)
                            else:
                                doc_obj["importance"] = importance
                                meta["importance"] = importance
                                doc_obj[IMPORTANCE_SET_BY_HR_KEY] = True
                                meta[IMPORTANCE_SET_BY_HR_KEY] = True
                                normalized[cat].append({"text": cleaned_item, "importance": importance})
                            self.documents.append(doc_obj)
                            
                            ids.append(doc_id)
                            documents.append(cleaned_item)
                            metadatas.append(meta)

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

            self.export_hr_rag_file(standard_req, hidden_req, normalized)

    def ingest_requirements(self, standard_req: str, hidden_req: str, llm_decomposer_func=None, force_reingest: bool = False):
        """
        Decomposes HR text into atomic criteria chunks with category tags using LLM.
        """
        standard_req = (standard_req or "").strip()
        hidden_req = (hidden_req or "").strip()

        if not force_reingest and self.has_stored_rag():
            print(f"[LocalRAG] Reusing persistent ChromaDB database ({len(self.documents)} items in {self.db_path}). SKIPPING LLM requirement categorization step!", file=sys.stderr)
            return

        if not standard_req and not hidden_req:
            print("[LocalRAG] No HR requirements or hidden requirements provided. Documents list will be empty.", file=sys.stderr)
            with self._lock:
                self.clear_rag_database()
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

        self.ingest_decomposed_dict(decomposed, standard_req=standard_req, hidden_req=hidden_req)

    def decompose_only(self, standard_req: str, hidden_req: str, llm_decomposer_func=None) -> Dict[str, Any]:
        """
        Decomposes requirements and saves them into RAG store without running candidate evaluation.
        Returns the structured summary containing categorized items and generated hr_rag.txt.
        """
        self.ingest_requirements(standard_req, hidden_req, llm_decomposer_func=llm_decomposer_func, force_reingest=True)
        return self.get_stored_rag_summary()

    def update_criteria_manually(self, categories: Dict[str, List[Any]], standard_req: Optional[str] = None, hidden_req: Optional[str] = None) -> Dict[str, Any]:
        """
        Updates stored RAG criteria with manual user edits, re-computes embeddings, and updates hr_rag.txt.
        Requirement text left as None falls back to the stored originals, so a Criteria-only
        edit (e.g. from the RAG Workbench) keeps HR's original text in hr_rag.txt.
        Raises ValueError, storing nothing, when the edited Criteria can't be scored (hr_rag_problem).
        """
        problem = hr_rag_problem(categories)
        if problem:
            raise ValueError(problem)
        if standard_req is None or hidden_req is None:
            originals = self.load_original_requirements()
            if standard_req is None:
                standard_req = originals["standard_requirements"]
            if hidden_req is None:
                hidden_req = originals["hidden_requirements"]
        self.ingest_decomposed_dict(categories, standard_req=standard_req, hidden_req=hidden_req)
        return self.get_stored_rag_summary()

    def get_hr_check_items(self) -> List[str]:
        """The stored HR Check Items: requirements set aside for HR to check by hand, never retrieved as Criteria."""
        with self._lock:
            return [doc["text"] for doc in self.documents if doc.get("category") == HR_CHECK_ITEMS_KEY]

    def get_importance_map(self, category: str) -> Dict[str, str]:
        """{criterion_text: importance} for one Category, used only by the deterministic Category scoring."""
        with self._lock:
            return {
                doc["text"]: normalize_importance(doc.get("importance"))
                for doc in self.documents if doc.get("category") == category
            }

    def export_hr_rag_file(self, standard_req: str, hidden_req: str, decomposed: Dict[str, List[Any]], output_path: str = "hr_rag.txt"):
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

    def retrieve(self, category: str, query: str = "", top_k: Optional[int] = None) -> List[str]:
        """
        Retrieves criteria items using ChromaDB vector search, dense cosine similarity, or in-memory fallback.
        If top_k is None, retrieves ALL criteria items belonging to the category without truncation.
        """
        query = query or ""
        filtered_docs = [doc for doc in self.documents if doc.get("category") == category]
        if not filtered_docs:
            return []

        cat_count = len(filtered_docs)
        effective_k = min(top_k, cat_count) if top_k is not None else cat_count

        if self.collection is not None and self.collection.count() > 0:
            try:
                query_kwargs = {
                    "where": {"category": category},
                    "n_results": effective_k
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
                    return [doc["text"] for score, doc in scored_docs[:effective_k]]
            except Exception as e:
                print(f"[LocalRAG Warning] Dense vector similarity calculation failed ({e}). Returning un-scored items.", file=sys.stderr)

        # In-memory mock/text fallback
        return [doc["text"] for doc in filtered_docs[:effective_k]]
