"""
Memory Retrieval Module for Mneme Memory System

This module handles intelligent memory retrieval using:
- Semantic search (vector similarity)
- Time decay calculations
- Importance scoring
- Multi-factor ranking

RETRIEVAL SCORING FORMULA:
Final_Score = (semantic_similarity × 0.4) + (importance_norm × 0.4) + (recency_norm × 0.2)

Importance is normalized relative to the candidate pool (min-max across
all candidates that pass the similarity threshold), not a fixed 0-10 scale.
This prevents score collapse when most candidates cluster at similar importance.

TIME DECAY FORMULA (from spec):
- 0-30 days: ×1.5 (recency bonus)
- 31-90 days: ×1.2
- 91-180 days: ×1.0 (baseline)
- 181-365 days: ×0.95
- After 1 year: ×0.9
- High-importance (8+) never decays below 7.0
- First 200k tokens exempt from decay

USAGE:
    from retrieval import MemoryRetriever

    retriever = MemoryRetriever(db, embedding_generator)
    results = retriever.semantic_search("Tell me about the crows")
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Union, Sequence
import json
import re


class RetrievalError(Exception):
    """Custom exception for retrieval errors."""
    pass


class MemoryRetriever:
    """
    Handles intelligent memory retrieval from the database.

    This class combines:
    - Semantic search (vector similarity)
    - Importance scores (with time decay)
    - Recency weighting
    - Multi-factor ranking
    """

    def __init__(
        self,
        database,
        embedding_generator,
        similarity_threshold=0.25,
        semantic_weight=0.4,
        importance_weight=0.4,
        recency_weight=0.2,
        entity_match_weight=0.15,
        graph_db=None,
    ):
        """
        Initialize the memory retriever.

        Args:
            database: Database instance
            embedding_generator: EmbeddingGenerator instance
            similarity_threshold: Minimum similarity to include results (default: 0.25)
            semantic_weight: Weight for semantic similarity (default: 0.4)
            importance_weight: Weight for importance score (default: 0.4)
            recency_weight: Weight for recency (default: 0.2)
            entity_match_weight: Weight for entity name/alias match in query (default: 0.15)
                                 Only active when graph_db is provided. Other weights are
                                 scaled down proportionally so all four always sum to 1.
            graph_db: GraphDatabase instance — enables entity-augmented retrieval (optional)
        """
        self.db = database
        self.embedder = embedding_generator
        self.graph_db = graph_db

        # Retrieval parameters (from config or defaults)
        self.similarity_threshold = similarity_threshold

        # If entity matching is active, redistribute weights so they sum to 1.
        # entity_match steals its share proportionally from the other three.
        if graph_db and entity_match_weight > 0:
            self.entity_match_weight = entity_match_weight
            scale = 1.0 - entity_match_weight
            base_sum = semantic_weight + importance_weight + recency_weight
            self.semantic_weight = semantic_weight / base_sum * scale
            self.importance_weight = importance_weight / base_sum * scale
            self.recency_weight = recency_weight / base_sum * scale
        else:
            self.entity_match_weight = 0.0
            self.semantic_weight = semantic_weight
            self.importance_weight = importance_weight
            self.recency_weight = recency_weight

    @staticmethod
    def calculate_time_decay_multiplier(
        message_timestamp: str,
        is_initial_context: bool = False
    ) -> float:
        """
        Calculate time decay multiplier for a message.

        Args:
            message_timestamp (str): ISO 8601 timestamp
            is_initial_context (bool): If True, no decay applied

        Returns:
            float: Multiplier (0.9 to 1.5)

        TIME DECAY TABLE (from spec):
        | Age Range    | Multiplier | Notes                  |
        |--------------|------------|------------------------|
        | 0-30 days    | ×1.5       | Recency bonus          |
        | 31-90 days   | ×1.2       | Slight bonus           |
        | 91-180 days  | ×1.0       | Baseline               |
        | 181-365 days | ×0.95      | Minor decay            |
        | After 1 year | ×0.9       | Moderate decay         |

        SPECIAL RULES:
        - Initial context (first 200k tokens): Always 1.0 (no decay)
        - This preserves foundational conversation context
        """
        # Initial context never decays
        if is_initial_context:
            return 1.0

        # Calculate age in days
        msg_time = datetime.fromisoformat(message_timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        age_days = (now - msg_time).days

        # Apply decay based on age
        if age_days <= 30:
            return 1.5  # Recent bonus
        elif age_days <= 90:
            return 1.2  # Slight bonus
        elif age_days <= 180:
            return 1.0  # Baseline
        elif age_days <= 365:
            return 0.95  # Minor decay
        else:
            return 0.9  # Moderate decay

    def calculate_effective_importance(
        self,
        base_importance: float,
        message_timestamp: str,
        is_initial_context: bool = False
    ) -> float:
        """
        Calculate importance score with time decay applied.

        Args:
            base_importance (float): Original importance (1-10)
            message_timestamp (str): ISO 8601 timestamp
            is_initial_context (bool): True if in first 200k tokens

        Returns:
            float: Effective importance with decay

        EXAMPLE:
        - Base importance: 8.0
        - Age: 400 days
        - Not initial context
        - Multiplier: 0.9
        - Effective: 8.0 × 0.9 = 7.2

        PROTECTION:
        High-importance messages (≥8.0) never decay below 7.0
        """
        # Get decay multiplier
        multiplier = self.calculate_time_decay_multiplier(
            message_timestamp,
            is_initial_context
        )

        # Apply multiplier
        effective = base_importance * multiplier

        # High-importance protection
        if base_importance >= 8.0 and effective < 7.0:
            effective = 7.0

        return effective

    def calculate_retrieval_score(
        self,
        semantic_similarity: float,
        importance_score: float,
        recency_multiplier: float,
        importance_range: tuple = None,
        entity_match_score: float = 0.0,
    ) -> float:
        """
        Calculate final retrieval score using spec formula.

        Args:
            semantic_similarity (float): 0.0-1.0, cosine similarity
            importance_score (float): 1.0-10.0, with decay applied
            recency_multiplier (float): 0.9-1.5, from decay table
            importance_range (tuple): (min, max) of effective importance
                across all candidates. Used for candidate-relative
                normalization. Falls back to 0-10 if None or degenerate.
            entity_match_score (float): 0.0-1.0, confidence from entity-message
                link when an entity name/alias from the query matches this message.
                0.0 for messages with no entity match. Only contributes when
                entity_match_weight > 0 (i.e. graph_db was provided).

        Returns:
            float: Final score (0-1 scale)

        FORMULA (entity matching active):
        Final_Score = (semantic × ~0.34) + (importance × ~0.34) + (recency × ~0.17) + (entity_match × 0.15)

        FORMULA (no graph_db / entity matching off):
        Final_Score = (semantic × 0.4) + (importance × 0.4) + (recency × 0.2)

        NORMALIZATION:
        Importance is normalized relative to the candidate pool, not a
        fixed 0-10 scale. This prevents score collapse when most
        candidates cluster at similar importance (e.g. all at 10.0).
        """
        # Candidate-relative importance normalization
        if importance_range and (importance_range[1] - importance_range[0]) > 0.01:
            lo, hi = importance_range
            normalized_importance = (importance_score - lo) / (hi - lo)
        else:
            # Degenerate range (all same importance) — fall back to absolute
            normalized_importance = importance_score / 10.0

        # Clamp to [0, 1]
        normalized_importance = max(0.0, min(1.0, normalized_importance))

        # Normalize recency multiplier to 0-1 scale
        # Range is 0.9 to 1.5, so normalize within that
        normalized_recency = (recency_multiplier - 0.9) / 0.6

        # Apply weights
        final_score = (
            (semantic_similarity * self.semantic_weight) +
            (normalized_importance * self.importance_weight) +
            (normalized_recency * self.recency_weight) +
            (entity_match_score * self.entity_match_weight)
        )

        return final_score

    def semantic_search(
        self,
        query: str,
        limit: int = 20,
        tier: Optional[Union[str, Sequence[str]]] = None,
        months_back: Optional[int] = 6,
        verbose: bool = False
    ) -> List[Dict]:
        """
        Search for memories using semantic similarity.

        Args:
            query (str): Search query
            limit (int): Maximum results
            tier (str or list/tuple of str, optional): Filter by tier. Pass a
                list (e.g. ["active", "standard"]) to search multiple tiers.
            months_back (int, optional): Limit to last N months

        Returns:
            List[Dict]: Ranked memories with scores

        PROCESS:
        1. Generate query embedding
        2. Get all messages with embeddings
        3. Calculate similarity for each
        4. Apply importance decay
        5. Calculate final scores
        6. Rank and filter
        7. Return top N

        EXAMPLE:
            results = retriever.semantic_search("tell me about the crows")
            for result in results:
                print(f"{result['score']:.2f}: {result['content'][:50]}")
        """
        # Generate query embedding
        print(f"Searching for: {query}")
        query_embedding = self.embedder.generate_query_embedding(query)

        # Tokenize query for match scoring (3+ char words, stopwords removed)
        _STOPWORDS = {
            'the','and','for','are','was','were','you','that','this','with','from',
            'have','had','has','not','but','they','what','she','him','his','her',
            'its','our','can','will','would','could','should','did','does','been',
            'being','about','when','there','their','then','than','some','any','all',
            'one','two','also','just','get','got','use','used','via','per','let',
        }
        query_tokens = set(re.findall(r'\b[a-z]{3,}\b', query.lower())) - _STOPWORDS

        # Find entity IDs mentioned in the query (name or alias word-boundary match)
        entity_ids_in_query = set()
        if self.entity_match_weight > 0 and self.graph_db and query_tokens:
            try:
                all_entities = self.graph_db.get_entity_stats(min_mentions=0)
                for ent in all_entities:
                    name_words = set(ent["name"].replace("_", " ").lower().split()) - _STOPWORDS
                    if name_words and name_words <= query_tokens:
                        entity_ids_in_query.add(ent["id"])
                        continue
                    aliases = json.loads(ent.get("aliases") or "[]")
                    for alias in aliases:
                        if len(alias) < 3:
                            continue
                        alias_words = set(alias.lower().split()) - _STOPWORDS
                        if alias_words and alias_words <= query_tokens:
                            entity_ids_in_query.add(ent["id"])
                            break
            except Exception as e:
                print(f"  Warning: entity query scan failed: {e}")

        # Build time filter
        cutoff_date = None
        if months_back:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=months_back * 30)).isoformat() + "Z"

        # Get all messages with embeddings
        if tier:
            messages = self.db.get_messages_with_embeddings(tier=tier, after=cutoff_date)
        else:
            messages = self.db.get_messages_with_embeddings(after=cutoff_date)

        if not messages:
            print("  No messages with embeddings found")
            return []

        # Note: Comparing against database messages (pre-filter count)
        # Only the final filtered count is shown to user

        # Phase 1: Score candidates (similarity + effective importance)
        candidates = []
        for msg in messages:
            # Get message embedding
            try:
                from .embeddings import embedding_from_json
                msg_embedding = embedding_from_json(msg["embedding_vector"])
            except Exception as e:
                print(f"  Warning: Skipping message {msg['id']} - bad embedding: {e}")
                continue

            # Calculate semantic similarity
            similarity = self.embedder.cosine_similarity(query_embedding, msg_embedding)

            # Debug output
            if verbose:
                print(f"  Message {msg['id']}: similarity={similarity:.3f} (threshold={self.similarity_threshold})")
                print(f"    Content: {msg['content'][:60]}...")

            # Skip if below threshold
            if similarity < self.similarity_threshold:
                continue

            # Get metadata
            metadata = json.loads(msg["metadata"]) if msg["metadata"] else {}
            is_initial_context = metadata.get("is_initial_context", False)

            # Calculate effective importance with decay
            effective_importance = self.calculate_effective_importance(
                msg["importance_score"],
                msg["timestamp"],
                is_initial_context
            )

            # Get recency multiplier
            recency_multiplier = self.calculate_time_decay_multiplier(
                msg["timestamp"],
                is_initial_context
            )

            candidates.append({
                "id": msg["id"],
                "content": msg["content"],
                "sender": msg["sender"],
                "timestamp": msg["timestamp"],
                "importance": msg["importance_score"],
                "effective_importance": effective_importance,
                "tier": msg["tier"],
                "semantic_similarity": similarity,
                "recency_multiplier": recency_multiplier,
                "metadata": metadata,
            })

        # Phase 2: Compute candidate-relative importance range
        if candidates:
            eff_scores = [c["effective_importance"] for c in candidates]
            importance_range = (min(eff_scores), max(eff_scores))
        else:
            importance_range = None

        # Phase 2.5: Batch-fetch entity links for match scoring
        # msg_id -> highest confidence among entities that match the query
        msg_entity_scores = {}
        if self.entity_match_weight > 0 and entity_ids_in_query and candidates:
            try:
                candidate_ids = [c["id"] for c in candidates]
                placeholders = ",".join("?" * len(candidate_ids))
                rows = self.db.execute_query(
                    f"SELECT message_id, entity_id, confidence FROM message_entities "
                    f"WHERE message_id IN ({placeholders})",
                    candidate_ids
                )
                for row in rows:
                    if row["entity_id"] in entity_ids_in_query:
                        msg_id = row["message_id"]
                        conf = float(row["confidence"])
                        if conf > msg_entity_scores.get(msg_id, 0.0):
                            msg_entity_scores[msg_id] = conf
            except Exception as e:
                print(f"  Warning: entity match lookup failed: {e}")

        # Phase 3: Calculate final scores with relative normalization + match score
        results = []
        for c in candidates:
            # Keyword score: fraction of query tokens found verbatim in message content
            if query_tokens:
                content_words = set(re.findall(r'\b[a-z]{3,}\b', c["content"].lower()))
                keyword_score = len(query_tokens & content_words) / len(query_tokens)
            else:
                keyword_score = 0.0

            # Entity score: confidence of entity link when that entity is named in query
            entity_score = msg_entity_scores.get(c["id"], 0.0)

            # Combined: stronger signal wins; small bonus when both fire
            match_score = min(1.0, max(keyword_score, entity_score) + 0.15 * min(keyword_score, entity_score))

            final_score = self.calculate_retrieval_score(
                c["semantic_similarity"],
                c["effective_importance"],
                c["recency_multiplier"],
                importance_range=importance_range,
                entity_match_score=match_score,
            )
            c["final_score"] = final_score
            results.append(c)

        # Sort by final score (highest first)
        results.sort(key=lambda x: x["final_score"], reverse=True)

        # Limit results
        results = results[:limit]

        # Note: Notification moved to context.py after duplicate filtering
        # to show actual final count visible to Claude

        return results

    def get_high_importance(
        self,
        min_importance: float = 7.0,
        limit: int = 50
    ) -> List[Dict]:
        """
        Retrieve high-importance memories (active tier content).

        Args:
            min_importance (float): Minimum importance threshold
            limit (int): Maximum results

        Returns:
            List[Dict]: High-importance memories

        USE CASE:
        Loading "active" context - always-relevant memories
        """
        messages = self.db.get_high_importance_messages(min_importance, limit)

        results = []
        for msg in messages:
            metadata = json.loads(msg["metadata"]) if msg["metadata"] else {}
            is_initial_context = metadata.get("is_initial_context", False)

            effective_importance = self.calculate_effective_importance(
                msg["importance_score"],
                msg["timestamp"],
                is_initial_context
            )

            results.append({
                "id": msg["id"],
                "content": msg["content"],
                "sender": msg["sender"],
                "timestamp": msg["timestamp"],
                "importance": msg["importance_score"],
                "effective_importance": effective_importance,
                "tier": msg["tier"]
            })

        # Sort by effective importance
        results.sort(key=lambda x: x["effective_importance"], reverse=True)

        return results


if __name__ == "__main__":
    """
    Test the retrieval module.
    """
    print("Retrieval module loaded successfully!")
    print("\nRetrieval formula:")
    print("  Final_Score = (semantic × 0.4) + (importance × 0.4) + (recency × 0.2)")
    print("\nTime decay multipliers:")
    print("  0-30 days:    ×1.5 (recency bonus)")
    print("  31-90 days:   ×1.2")
    print("  91-180 days:  ×1.0 (baseline)")
    print("  181-365 days: ×0.95")
    print("  After 1 year: ×0.9")
    print("\nTo use this module:")
    print("  from retrieval import MemoryRetriever")
    print("  retriever = MemoryRetriever(db, embedder)")
    print("  results = retriever.semantic_search('your query')")
