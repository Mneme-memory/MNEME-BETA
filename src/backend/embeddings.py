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
