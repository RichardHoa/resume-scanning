"""
Embedding-based evaluator using Sentence Transformers / PyTorch
"""
import sys
import numpy as np

HAS_TORCH_TRANSFORMERS = False
try:
    import torch
    from transformers import AutoTokenizer, AutoModel
    HAS_TORCH_TRANSFORMERS = True
except ImportError:
    pass


def mean_pooling(model_output, attention_mask):
    """Mean Pooling - Take attention mask into account for correct averaging"""
    token_embeddings = model_output[0]
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)


class EmbeddingEvaluator:
    def __init__(self, model_name_or_path='AITeamVN/Vietnamese_Embedding'):
        print(f"Loading embedding model: {model_name_or_path}...", file=sys.stderr)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModel.from_pretrained(model_name_or_path)
        
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")
            
        self.model = self.model.to(self.device)
        self.model.eval()
        self.cache = {}
        print(f"Embedding model loaded on device: {self.device}", file=sys.stderr)

    def get_embeddings(self, texts):
        if not texts:
            return []
        
        uncached = list(set(t for t in texts if t not in self.cache))
        
        batch_size = 16
        for i in range(0, len(uncached), batch_size):
            batch = uncached[i:i+batch_size]
            inputs = self.tokenizer(batch, padding=True, truncation=True, return_tensors='pt', max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self.model(**inputs)
            embeddings = mean_pooling(outputs, inputs['attention_mask']).cpu().numpy()
            for text, emb in zip(batch, embeddings):
                self.cache[text] = emb
                
        return [self.cache[t] for t in texts]

    def get_embedding(self, text):
        cleaned = str(text).strip()
        if not cleaned:
            hidden_size = self.model.config.hidden_size
            return np.zeros(hidden_size)
        return self.get_embeddings([cleaned])[0]


class LexicalEvaluator:
    def __init__(self):
        print("Warning: torch or transformers not found locally. Falling back to LexicalEvaluator (difflib SequenceMatcher).", file=sys.stderr)
        self.device = torch.device("cpu") if HAS_TORCH_TRANSFORMERS else "cpu"

    def get_embeddings(self, texts):
        return []

    def get_embedding(self, text):
        return None
