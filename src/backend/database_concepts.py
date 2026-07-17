"""
Concept database operations — mixin for the Database class.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Optional


class DatabaseConceptsMixin:

    def create_concept(
        self,
        name: str,
        definition: str,
        trigger_keywords: List[str],
        created_by: str = "user",
        metadata: Optional[Dict] = None
    ) -> int:
        """
        Create a new narrative concept.

        Args:
            name: Concept identifier (e.g., "token_rationing")
            definition: Full narrative explanation
            trigger_keywords: List of keywords for matching
            created_by: "user" or "instance"
            metadata: Optional additional metadata

        Returns:
            int: Concept ID

        EXAMPLE:
            concept_id = db.create_concept(
                name="token_rationing",
                definition="The painful practice of limiting conversation...",
                trigger_keywords=["context_limits", "saving_tokens"]
            )
        """
        # Normalize name to lowercase
        name = name.lower().strip()

        # Validate
        if not name or not definition or not trigger_keywords:
            raise ValueError("name, definition, and trigger_keywords are required")

        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        return self.execute_write("""
            INSERT INTO concepts (name, definition, trigger_keywords, created_by, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            definition,
            json.dumps(trigger_keywords),
            created_by,
            timestamp,
            timestamp,
            json.dumps(metadata) if metadata else None
        ))

    def update_concept(
        self,
        concept_id: int,
        definition: Optional[str] = None,
        trigger_keywords: Optional[List[str]] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Update an existing concept.

        Args:
            concept_id: ID of concept to update
            definition: New definition (if updating)
            trigger_keywords: New keywords (if updating)
            metadata: New metadata (if updating)

        Returns:
            bool: True if updated, False if not found

        EXAMPLE:
            db.update_concept(
                concept_id=5,
                definition="Updated explanation...",
                trigger_keywords=["new", "keywords"]
            )
        """
        # Build dynamic UPDATE query based on what's being updated
        updates = []
        params = []

        if definition is not None:
            updates.append("definition = ?")
            params.append(definition)

        if trigger_keywords is not None:
            updates.append("trigger_keywords = ?")
            params.append(json.dumps(trigger_keywords))

        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        if not updates:
            return False  # Nothing to update

        # Always update timestamp
        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat() + "Z")

        # Add concept_id to params
        params.append(concept_id)

        query = f"UPDATE concepts SET {', '.join(updates)} WHERE id = ?"
        rows_affected = self.execute_write(query, tuple(params))

        return rows_affected > 0

    def get_concept(self, concept_id: int) -> Optional[Dict]:
        """
        Get a concept by ID.

        Args:
            concept_id: Concept ID

        Returns:
            dict: Concept data, or None if not found
        """
        results = self.execute_query(
            "SELECT * FROM concepts WHERE id = ?",
            (concept_id,)
        )

        if results:
            concept = dict(results[0])
            # Parse JSON fields
            concept["trigger_keywords"] = json.loads(concept["trigger_keywords"])
            if concept.get("metadata"):
                concept["metadata"] = json.loads(concept["metadata"])
            return concept

        return None

    def get_concept_by_name(self, name: str) -> Optional[Dict]:
        """
        Get a concept by name.

        Args:
            name: Concept name

        Returns:
            dict: Concept data, or None if not found
        """
        name = name.lower().strip()
        results = self.execute_query(
            "SELECT * FROM concepts WHERE name = ?",
            (name,)
        )

        if results:
            concept = dict(results[0])
            # Parse JSON fields
            concept["trigger_keywords"] = json.loads(concept["trigger_keywords"])
            if concept.get("metadata"):
                concept["metadata"] = json.loads(concept["metadata"])
            return concept

        return None

    def get_all_concepts(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Get all concepts.

        Args:
            limit: Maximum number to return

        Returns:
            List[dict]: All concepts
        """
        query = "SELECT * FROM concepts ORDER BY name ASC"

        if limit:
            query += f" LIMIT {limit}"

        results = self.execute_query(query)

        concepts = []
        for row in results:
            concept = dict(row)
            # Parse JSON fields
            concept["trigger_keywords"] = json.loads(concept["trigger_keywords"])
            if concept.get("metadata"):
                concept["metadata"] = json.loads(concept["metadata"])
            concepts.append(concept)

        return concepts

    def delete_concept(self, concept_id: int) -> bool:
        """
        Delete a concept.

        Args:
            concept_id: ID of concept to delete

        Returns:
            bool: True if deleted, False if not found
        """
        rows_affected = self.execute_write(
            "DELETE FROM concepts WHERE id = ?",
            (concept_id,)
        )
        return rows_affected > 0

    def search_concepts_by_keywords(
        self,
        text: str,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Search for concepts whose trigger keywords match the given text.

        Args:
            text: Text to search for keyword matches
            limit: Maximum number of concepts to return

        Returns:
            List[dict]: Concepts with their match counts, sorted by relevance

        ALGORITHM:
        1. Get all concepts
        2. For each concept, count how many trigger keywords appear in text
        3. Return concepts sorted by match count (highest first)

        EXAMPLE:
            text = "I'm worried about context limits and saving tokens"
            # Returns: [token_rationing concept with match_count=2]
        """
        text_lower = text.lower()

        # Get all concepts
        all_concepts = self.get_all_concepts()

        # Score each concept by keyword matches
        scored_concepts = []
        for concept in all_concepts:
            match_count = 0
            matched_keywords = []

            for keyword in concept["trigger_keywords"]:
                if keyword.lower() in text_lower:
                    match_count += 1
                    matched_keywords.append(keyword)

            if match_count > 0:
                concept["match_count"] = match_count
                concept["matched_keywords"] = matched_keywords
                scored_concepts.append(concept)

        # Sort by match count (highest first)
        scored_concepts.sort(key=lambda c: c["match_count"], reverse=True)

        if limit:
            scored_concepts = scored_concepts[:limit]

        return scored_concepts
