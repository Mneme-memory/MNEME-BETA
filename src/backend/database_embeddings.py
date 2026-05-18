"""
Embedding database operations — mixin for the Database class.
"""

from datetime import datetime, timezone
from typing import List, Dict, Optional


class DatabaseEmbeddingsMixin:

    def add_embedding(
        self,
        vector: List[float],
        model: str,
        cost: float = 0.0
    ) -> int:
        """
        Add an embedding vector to the database.

        Args:
            vector (List[float]): Embedding vector (typically 1024 dimensions)
            model (str): Model used (e.g., "voyage-3")
            cost (float): Cost to generate this embedding

        Returns:
            int: ID of the newly created embedding

        USAGE:
            embedding_id = db.add_embedding(vector, "voyage-3", 0.000012)
            db.update_message_embedding(message_id, embedding_id)
        """
        from .embeddings import embedding_to_json
        vector_json = embedding_to_json(vector)
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        query = """
            INSERT INTO embeddings (vector, model, created_at, cost)
            VALUES (?, ?, ?, ?)
        """
        params = (vector_json, model, timestamp, cost)

        return self.execute_write(query, params)

    def update_message_embedding(self, message_id: int, embedding_id: int) -> bool:
        """
        Link an embedding to a message.

        Args:
            message_id (int): The message ID
            embedding_id (int): The embedding ID

        Returns:
            bool: True if successful
        """
        query = "UPDATE messages SET embedding_id = ? WHERE id = ?"
        self.execute_write(query, (embedding_id, message_id))
        return True

    def get_messages_with_embeddings(
        self,
        tier: Optional[str] = None,
        after: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Get all messages that have embeddings.

        Args:
            tier (str, optional): Filter by tier
            after (str, optional): Only messages after this timestamp
            limit (int, optional): Maximum number of results

        Returns:
            List[dict]: Messages with their embeddings

        RETURN FORMAT:
            Each dict includes:
            - All message fields (id, content, timestamp, etc.)
            - embedding_vector (JSON string)
            - embedding_model
        """
        conditions = ["embedding_id IS NOT NULL"]
        params = []

        if tier:
            conditions.append("tier = ?")
            params.append(tier)

        if after:
            conditions.append("timestamp >= ?")
            params.append(after)

        query = f"""
            SELECT m.*, e.vector as embedding_vector, e.model as embedding_model
            FROM messages m
            INNER JOIN embeddings e ON m.embedding_id = e.id
            WHERE {' AND '.join(conditions)}
            ORDER BY m.timestamp DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        results = self.execute_query(query, tuple(params))
        return [dict(row) for row in results]

    def get_messages_without_embeddings(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Get messages that haven't been embedded yet.

        Args:
            limit (int, optional): Maximum number to return

        Returns:
            List[dict]: Messages without embeddings

        USE CASE:
        When running Phase 2 embedding on existing messages.
        """
        query = """
            SELECT *
            FROM messages
            WHERE embedding_id IS NULL
            ORDER BY timestamp ASC
        """

        if limit:
            query += f" LIMIT {limit}"

        results = self.execute_query(query)
        return [dict(row) for row in results]
