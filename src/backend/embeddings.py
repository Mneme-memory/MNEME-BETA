"""
Embedding Generation Module for Mneme Memory System

This module handles generating vector embeddings for messages using OpenAI.

WHY EMBEDDINGS?
Embeddings are mathematical representations of text that capture semantic meaning.
Similar texts have similar embeddings, enabling "semantic search" - finding messages
by meaning rather than just keywords.

OPENAI TEXT-EMBEDDING-3-SMALL:
- 1536 dimensions
- Optimized for retrieval/search tasks
- Better semantic precision than older models
- Supports EU payment methods (switched from Voyage-3)
- Cost: $0.02 per 1M tokens (very affordable)

ERROR HANDLING (Phase 4.4):
- Automatic retry with exponential backoff
- Rate limit handling
- Graceful degradation on persistent failures

USAGE:
    from embeddings import EmbeddingGenerator

    gen = EmbeddingGenerator(api_key="your_openai_key")
    embedding = gen.generate_embedding("Tell me about the crows")
    # Returns: list of 1536 floats
"""

import json
import os
import urllib.request
from pathlib import Path
from typing import List, Dict, Optional
import time

from .error_handling import (
    retry_with_backoff,
    get_user_friendly_message,
    MnemeAPIError
)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("Warning: openai package not installed. Run: pip install openai")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("Warning: numpy package not installed. Run: pip install numpy")

try:
    import onnxruntime as ort
    ONNXRUNTIME_AVAILABLE = True
except ImportError:
    ONNXRUNTIME_AVAILABLE = False

try:
    from tokenizers import Tokenizer
    TOKENIZERS_AVAILABLE = True
except ImportError:
    TOKENIZERS_AVAILABLE = False


class EmbeddingError(Exception):
    """Custom exception for embedding generation errors."""
    pass


class EmbeddingGenerator:
    """
    Handles embedding generation using OpenAI.

    This class manages:
    - API connection to OpenAI
    - Batch processing for efficiency
    - Rate limit handling
    - Cost tracking
    - Caching to avoid regeneration
    """

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        """
        Initialize the embedding generator.

        Args:
            api_key (str): OpenAI API key
            model (str): Model to use (default: text-embedding-3-small)

        Raises:
            EmbeddingError: If openai package not available
        """
        if not OPENAI_AVAILABLE:
            raise EmbeddingError(
                "openai package not installed. "
                "Install with: pip install openai"
            )

        self.api_key = api_key
        self.model = model
        self.client = OpenAI(api_key=api_key)

        # Cost tracking
        self.tokens_processed = 0
        self.total_cost = 0.0

        # OpenAI text-embedding-3-small pricing
        # text-embedding-3-small: $0.02 per 1M tokens
        # text-embedding-3-large: $0.13 per 1M tokens
        if model == "text-embedding-3-small":
            self.cost_per_million_tokens = 0.02
            self.dimensions = 1536
        elif model == "text-embedding-3-large":
            self.cost_per_million_tokens = 0.13
            self.dimensions = 3072
        else:  # ada-002 or other
            self.cost_per_million_tokens = 0.10
            self.dimensions = 1536

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text (str): Text to embed

        Returns:
            List[float]: Embedding vector (1536 dimensions for text-embedding-3-small)

        Raises:
            EmbeddingError: If embedding generation fails after retries

        ERROR HANDLING:
        - Automatic retry with exponential backoff (1s, 2s, 4s)
        - Converts OpenAI errors to user-friendly messages
        - Max 3 retries before failing

        EXAMPLE:
            embedding = gen.generate_embedding("I love the crows")
            print(len(embedding))  # 1536
        """
        try:
            response = self.client.embeddings.create(
                input=text,
                model=self.model,
                timeout=30.0  # 30 second timeout
            )

            # Track usage
            tokens_used = response.usage.total_tokens
            self.tokens_processed += tokens_used
            cost = (tokens_used / 1_000_000) * self.cost_per_million_tokens
            self.total_cost += cost

            return response.data[0].embedding

        except Exception as e:
            # Convert to user-friendly error
            raise EmbeddingError(get_user_friendly_message(e)) from e

    def generate_embeddings_batch(
        self,
        texts: List[str],
        batch_size: int = 100
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batches.

        Args:
            texts (List[str]): List of texts to embed
            batch_size (int): Number of texts per API call (default 100)

        Returns:
            List[List[float]]: List of embedding vectors

        WHY BATCHING?
        - More efficient (fewer API calls)
        - Better rate limit management
        - Progress tracking for large imports

        EXAMPLE:
            texts = ["Message 1", "Message 2", "Message 3"]
            embeddings = gen.generate_embeddings_batch(texts)
        """
        all_embeddings = []
        total = len(texts)

        print(f"Generating embeddings for {total} texts...")

        for i in range(0, total, batch_size):
            batch = texts[i:i+batch_size]

            try:
                response = self.client.embeddings.create(
                    input=batch,
                    model=self.model
                )

                # Track usage
                tokens_used = response.usage.total_tokens
                self.tokens_processed += tokens_used
                cost = (tokens_used / 1_000_000) * self.cost_per_million_tokens
                self.total_cost += cost

                # Extract embeddings in order
                embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(embeddings)

                processed = min(i + batch_size, total)
                print(f"  ✓ Generated {processed}/{total} embeddings "
                      f"(cost so far: ${self.total_cost:.4f})")

                # Rate limit protection: small delay between batches
                if i + batch_size < total:
                    time.sleep(0.2)

            except Exception as e:
                print(f"  ✗ Error in batch {i//batch_size + 1}: {e}")
                # Return None for failed embeddings
                all_embeddings.extend([None] * len(batch))

        return all_embeddings

    def generate_query_embedding(self, query: str) -> List[float]:
        """
        Generate embedding for a search query.

        Args:
            query (str): Search query text

        Returns:
            List[float]: Embedding vector optimized for search

        NOTE:
        OpenAI embeddings work well for both documents and queries without
        needing separate input types (unlike Voyage).
        """
        return self.generate_embedding(query)

    def cosine_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float]
    ) -> float:
        """
        Calculate cosine similarity between two embeddings.

        Args:
            embedding1 (List[float]): First embedding vector
            embedding2 (List[float]): Second embedding vector

        Returns:
            float: Similarity score (0.0 to 1.0, higher = more similar)

        WHAT IS COSINE SIMILARITY?
        Measures how similar two vectors are by calculating the cosine of the
        angle between them. 1.0 = identical, 0.0 = completely different.

        This is the core of semantic search: comparing query embedding to
        stored message embeddings to find the most relevant ones.
        """
        if not NUMPY_AVAILABLE:
            raise EmbeddingError("numpy required for similarity calculation")

        # Convert to numpy arrays
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)

        # Calculate cosine similarity
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        similarity = dot_product / (norm1 * norm2)

        # Ensure result is between 0 and 1
        return max(0.0, min(1.0, similarity))

    def get_usage_stats(self) -> Dict:
        """
        Get usage statistics for cost tracking.

        Returns:
            dict: Usage stats including tokens processed and total cost

        EXAMPLE:
            stats = gen.get_usage_stats()
            print(f"Total cost: ${stats['total_cost']:.2f}")
        """
        return {
            "tokens_processed": self.tokens_processed,
            "total_cost": self.total_cost,
            "model": self.model,
            "cost_per_million_tokens": self.cost_per_million_tokens,
            "dimensions": self.dimensions
        }


class LocalEmbeddingGenerator:
    """
    Handles embedding generation locally via ONNX, no external API required.

    Uses BAAI/bge-small-en-v1.5 (384 dims, MIT license) via a maintained ONNX
    mirror (Xenova/bge-small-en-v1.5) so new users can run Mneme with only an
    Anthropic API key. Weights (~34MB quantized) are downloaded on first use
    and cached alongside Mneme's data directory.

    Public interface matches EmbeddingGenerator so it's a drop-in swap:
    generate_embedding(text), generate_query_embedding(query),
    cosine_similarity(a, b), .dimensions, .model. Cost is always 0.0.

    MODEL DETAILS (verified against the HF model card, 2026):
    - Repo: Xenova/bge-small-en-v1.5 (ONNX export of BAAI/bge-small-en-v1.5)
    - File: onnx/model_quantized.onnx (~34MB, int8 quantized)
    - Tokenizer: tokenizer.json (WordPiece/BERT-style, HF `tokenizers` lib)
    - Pooling: CLS token (first token of last_hidden_state), then L2 normalize
    - Query prefix (queries only, NOT documents): "Represent this sentence
      for searching relevant passages: " — per the BGE v1.5 model card.
      Documents/passages get no prefix.
    - Max sequence length: 512 tokens (tokenizer truncates)
    """

    HF_REPO = "Xenova/bge-small-en-v1.5"
    ONNX_FILE = "onnx/model_quantized.onnx"
    TOKENIZER_FILE = "tokenizer.json"
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
    MAX_SEQ_LEN = 512

    def __init__(self, models_dir: Optional[str] = None):
        """
        Initialize the local embedding generator.

        Args:
            models_dir: Directory to store/cache downloaded model weights.
                Defaults to a `models/` folder alongside Mneme's data dir.

        NOTE: The ONNX session and tokenizer are lazy-loaded on first use
        (not here) so importing/instantiating this class never blocks
        server startup or requires network access.
        """
        if not ONNXRUNTIME_AVAILABLE:
            raise EmbeddingError(
                "onnxruntime package not installed. "
                "Install with: pip install onnxruntime"
            )
        if not TOKENIZERS_AVAILABLE:
            raise EmbeddingError(
                "tokenizers package not installed. "
                "Install with: pip install tokenizers"
            )

        if models_dir is None:
            try:
                from src.backend.config import get_mneme_home
            except ModuleNotFoundError:
                from config import get_mneme_home
            models_dir = str(get_mneme_home() / "data" / "models")
        self.models_dir = Path(models_dir)

        self.model = "bge-small-en-v1.5"
        self.dimensions = 384
        self.cost_per_million_tokens = 0.0

        # Cost tracking (kept for interface parity with EmbeddingGenerator)
        self.tokens_processed = 0
        self.total_cost = 0.0

        # Lazy-loaded on first use
        self._session = None
        self._tokenizer = None

    def _model_paths(self):
        onnx_path = self.models_dir / "model_quantized.onnx"
        tokenizer_path = self.models_dir / "tokenizer.json"
        return onnx_path, tokenizer_path

    def _download_file(self, url: str, dest: Path):
        """
        Download a file to `dest`, resilient to partial/interrupted downloads.

        Downloads to a `.tmp` sibling first, then renames on success, so a
        crash or network drop mid-download never leaves a corrupt file that
        looks complete.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest.with_suffix(dest.suffix + ".tmp")

        print(f"Downloading local embedding model component: {dest.name} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mneme/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            downloaded = 0
            chunk_size = 1024 * 256
            last_pct_reported = -1
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded * 100 / total)
                        if pct >= last_pct_reported + 10:
                            print(f"  {dest.name}: {pct}% ({downloaded // 1024}KB / {total // 1024}KB)")
                            last_pct_reported = pct

        if total is not None and dest.suffix != ".json":
            actual_size = tmp_path.stat().st_size
            if actual_size < total * 0.95:
                tmp_path.unlink(missing_ok=True)
                raise EmbeddingError(
                    f"Download of {dest.name} appears incomplete "
                    f"({actual_size} of {total} bytes). Will retry next time."
                )

        final_size = tmp_path.stat().st_size
        os.replace(tmp_path, dest)
        print(f"  Done: {dest.name} downloaded ({final_size} bytes)")

    def _ensure_model_files(self):
        onnx_path, tokenizer_path = self._model_paths()

        if not onnx_path.exists():
            print("Downloading local embedding model (~35MB, one-time)...")
            onnx_url = f"https://huggingface.co/{self.HF_REPO}/resolve/main/{self.ONNX_FILE}"
            self._download_file(onnx_url, onnx_path)

        if not tokenizer_path.exists():
            tokenizer_url = f"https://huggingface.co/{self.HF_REPO}/resolve/main/{self.TOKENIZER_FILE}"
            self._download_file(tokenizer_url, tokenizer_path)

    def _ensure_loaded(self):
        """Lazily download (if needed) and load the ONNX session + tokenizer."""
        if self._session is not None and self._tokenizer is not None:
            return

        try:
            self._ensure_model_files()
            onnx_path, tokenizer_path = self._model_paths()

            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self._tokenizer.enable_truncation(max_length=self.MAX_SEQ_LEN)

            self._session = ort.InferenceSession(
                str(onnx_path),
                providers=["CPUExecutionProvider"]
            )
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(
                f"Failed to load local embedding model: {get_user_friendly_message(e)}"
            ) from e

    def _embed(self, text: str) -> List[float]:
        self._ensure_loaded()

        encoding = self._tokenizer.encode(text)
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.array([encoding.attention_mask], dtype=np.int64)

        onnx_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
        input_names = {inp.name for inp in self._session.get_inputs()}
        if "token_type_ids" in input_names:
            onnx_inputs["token_type_ids"] = np.zeros_like(input_ids)

        outputs = self._session.run(None, onnx_inputs)
        # First output is last_hidden_state: shape (batch, seq_len, hidden_dim)
        last_hidden_state = outputs[0]

        # CLS pooling: take the embedding of the first token
        cls_embedding = last_hidden_state[0, 0, :]

        # L2 normalize
        norm = np.linalg.norm(cls_embedding)
        if norm > 0:
            cls_embedding = cls_embedding / norm

        self.tokens_processed += len(encoding.ids)

        return cls_embedding.astype(float).tolist()

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for stored message text (no prefix per BGE v1.5
        model card — only queries get the instruction prefix).

        Returns:
            List[float]: 384-dimensional embedding vector.
        """
        try:
            return self._embed(text)
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(get_user_friendly_message(e)) from e

    def generate_query_embedding(self, query: str) -> List[float]:
        """
        Generate embedding for a search query, using the BGE v1.5
        recommended instruction prefix for retrieval queries.
        """
        try:
            return self._embed(self.QUERY_PREFIX + query)
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(get_user_friendly_message(e)) from e

    def cosine_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float]
    ) -> float:
        """
        Calculate cosine similarity between two embeddings.

        MIXED-DIMENSION SAFETY: if a user flips provider (openai <-> local)
        on an existing database, old and new embeddings may have different
        dimensions (1536 vs 384). Returns 0.0 instead of letting numpy raise,
        so retrieval never crashes — the mismatched pair is just scored as
        unrelated.
        """
        if not NUMPY_AVAILABLE:
            raise EmbeddingError("numpy required for similarity calculation")

        if len(embedding1) != len(embedding2):
            return 0.0

        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        similarity = dot_product / (norm1 * norm2)
        return max(0.0, min(1.0, similarity))

    def get_usage_stats(self) -> Dict:
        """Get usage statistics (cost is always 0.0 for local embeddings)."""
        return {
            "tokens_processed": self.tokens_processed,
            "total_cost": self.total_cost,
            "model": self.model,
            "cost_per_million_tokens": self.cost_per_million_tokens,
            "dimensions": self.dimensions
        }


def create_embedding_generator(config: Dict):
    """
    Build the correct embedding generator from a loaded config dict, honoring
    `retrieval.embedding_provider` ("local" | "openai", default "openai" for
    backward compatibility with configs predating local embeddings).

    This is the single source of truth for provider selection — every entry
    point (server.py, scripts/chat.py, scripts/import_conversation.py) should
    call this instead of constructing EmbeddingGenerator/LocalEmbeddingGenerator
    directly, so a local-embeddings install (no OpenAI key) works everywhere.

    Args:
        config: Loaded config dict (as returned by config.load_config()).

    Returns:
        LocalEmbeddingGenerator or EmbeddingGenerator instance.
    """
    embedding_provider = config.get("retrieval", {}).get("embedding_provider", "openai")
    if embedding_provider == "local":
        return LocalEmbeddingGenerator()

    openai_key = config.get("api_keys", {}).get("openai", "")
    model = config.get("retrieval", {}).get("embeddings_model", "text-embedding-3-small")
    return EmbeddingGenerator(openai_key, model=model)


def embedding_to_json(embedding: List[float]) -> str:
    """
    Convert embedding vector to JSON string for database storage.

    Args:
        embedding (List[float]): Embedding vector

    Returns:
        str: JSON string representation

    WHY JSON?
    SQLite doesn't have a native vector type, so we store embeddings as
    JSON text. This is fine for our scale (<10k messages).

    For larger scale, would use a vector database (FAISS, Chroma, etc.)
    """
    return json.dumps(embedding)


def embedding_from_json(json_str: str) -> List[float]:
    """
    Convert JSON string back to embedding vector.

    Args:
        json_str (str): JSON string from database

    Returns:
        List[float]: Embedding vector
    """
    return json.loads(json_str)


if __name__ == "__main__":
    """
    Test the embedding generator.
    """
    print("Embeddings module loaded successfully!")
    print("\nTo use this module:")
    print("1. Get OpenAI API key from: https://platform.openai.com/")
    print("2. Add to config.json: openai_key")
    print("3. Import and use:")
    print("   from embeddings import EmbeddingGenerator")
    print("   gen = EmbeddingGenerator(api_key='your_key')")
    print("   embedding = gen.generate_embedding('your text')")
