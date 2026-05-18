"""
Attachment database operations — mixin for the Database class.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Optional


class DatabaseAttachmentsMixin:

    def add_attachment(
        self,
        uuid: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_path: str,
        file_hash: Optional[str] = None,
        ai_description: Optional[str] = None,
        ai_summary: Optional[str] = None,
        content_preview: Optional[str] = None,
        embedding_id: Optional[int] = None,
        message_id: Optional[int] = None,
        processing_status: str = "pending",
        metadata: Optional[Dict] = None
    ) -> int:
        """
        Add a new file attachment to the database.

        Args:
            uuid: Unique identifier for external reference
            filename: Original filename (for display)
            mime_type: MIME type (e.g., "image/jpeg")
            size_bytes: File size in bytes
            storage_path: Path to file directory (relative to attachments dir)
            file_hash: SHA-256 hash for deduplication
            ai_description: AI-generated description
            ai_summary: AI-generated summary (for large files)
            content_preview: First ~2000 chars (for text/JSON)
            embedding_id: ID of embedding vector (for semantic search)
            message_id: Associated message ID (NULL if not yet sent)
            processing_status: "pending", "ready", or "failed"
            metadata: Additional metadata (width, height, page_count, etc.)

        Returns:
            int: Attachment ID

        EXAMPLE:
            attachment_id = db.add_attachment(
                uuid="a1b2c3d4-5678-90ab",
                filename="photo.jpg",
                mime_type="image/jpeg",
                size_bytes=1048576,
                storage_path="a1b2c3d4-5678-90ab",
                metadata={"width": 1920, "height": 1080}
            )
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        metadata_json = json.dumps(metadata) if metadata else None

        return self.execute_write("""
            INSERT INTO attachments
            (uuid, filename, mime_type, size_bytes, storage_path, file_hash,
             ai_description, ai_summary, content_preview, embedding_id, message_id,
             processing_status, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uuid, filename, mime_type, size_bytes, storage_path, file_hash,
            ai_description, ai_summary, content_preview, embedding_id, message_id,
            processing_status, timestamp, metadata_json
        ))

    def get_attachment(self, attachment_id: int) -> Optional[Dict]:
        """
        Get an attachment by ID.

        Args:
            attachment_id: Attachment ID

        Returns:
            dict: Attachment data, or None if not found
        """
        results = self.execute_query(
            "SELECT * FROM attachments WHERE id = ?",
            (attachment_id,)
        )

        if results:
            attachment = dict(results[0])
            # Parse JSON fields
            if attachment.get("metadata"):
                attachment["metadata"] = json.loads(attachment["metadata"])
            return attachment

        return None

    def get_attachment_by_uuid(self, uuid: str) -> Optional[Dict]:
        """
        Get an attachment by UUID.

        Args:
            uuid: Attachment UUID

        Returns:
            dict: Attachment data, or None if not found
        """
        results = self.execute_query(
            "SELECT * FROM attachments WHERE uuid = ?",
            (uuid,)
        )

        if results:
            attachment = dict(results[0])
            # Parse JSON fields
            if attachment.get("metadata"):
                attachment["metadata"] = json.loads(attachment["metadata"])
            return attachment

        return None

    def get_attachments_for_message(self, message_id: int) -> List[Dict]:
        """
        Get all attachments associated with a message.

        Args:
            message_id: Message ID

        Returns:
            List[dict]: Attachments for this message
        """
        results = self.execute_query(
            "SELECT * FROM attachments WHERE message_id = ? ORDER BY created_at ASC",
            (message_id,)
        )

        attachments = []
        for row in results:
            attachment = dict(row)
            if attachment.get("metadata"):
                attachment["metadata"] = json.loads(attachment["metadata"])
            attachments.append(attachment)

        return attachments

    def get_recent_attachments(
        self,
        limit: int = 20,
        with_description: bool = True,
        message_ids: Optional[List[int]] = None
    ) -> List[Dict]:
        """
        Get recent attachments for FILES block context.

        Args:
            limit: Maximum number of attachments to return
            with_description: Only return attachments with AI descriptions
            message_ids: Optional filter by message IDs (for active tier)

        Returns:
            List[dict]: Recent attachments with descriptions

        USE CASE:
        Building FILES block for auto-retrieval awareness.
        """
        conditions = ["processing_status = 'ready'"]
        params = []

        if with_description:
            conditions.append("ai_description IS NOT NULL")

        if message_ids:
            placeholders = ",".join("?" * len(message_ids))
            conditions.append(f"message_id IN ({placeholders})")
            params.extend(message_ids)

        query = f"""
            SELECT * FROM attachments
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)

        results = self.execute_query(query, tuple(params))

        attachments = []
        for row in results:
            attachment = dict(row)
            if attachment.get("metadata"):
                attachment["metadata"] = json.loads(attachment["metadata"])
            attachments.append(attachment)

        return attachments

    def get_attachments_without_descriptions(self, limit: int = 10) -> List[Dict]:
        """
        Get attachments that don't have AI descriptions yet.

        Args:
            limit: Maximum number to return

        Returns:
            List[dict]: Attachments needing descriptions

        USE CASE:
        For @describe reminder - find files needing AI descriptions.
        """
        results = self.execute_query("""
            SELECT * FROM attachments
            WHERE ai_description IS NULL
              AND processing_status = 'ready'
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))

        attachments = []
        for row in results:
            attachment = dict(row)
            if attachment.get("metadata"):
                attachment["metadata"] = json.loads(attachment["metadata"])
            attachments.append(attachment)

        return attachments

    def update_attachment(
        self,
        attachment_id: int,
        ai_description: Optional[str] = None,
        ai_summary: Optional[str] = None,
        content_preview: Optional[str] = None,
        embedding_id: Optional[int] = None,
        message_id: Optional[int] = None,
        processing_status: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Update an attachment's fields.

        Args:
            attachment_id: ID of attachment to update
            ai_description: New AI description (if updating)
            ai_summary: New AI summary (if updating)
            content_preview: New content preview (if updating)
            embedding_id: New embedding ID (if updating)
            message_id: New message ID (if updating)
            processing_status: New status (if updating)
            metadata: New metadata (if updating)

        Returns:
            bool: True if updated, False if not found
        """
        updates = []
        params = []

        if ai_description is not None:
            updates.append("ai_description = ?")
            params.append(ai_description)

        if ai_summary is not None:
            updates.append("ai_summary = ?")
            params.append(ai_summary)

        if content_preview is not None:
            updates.append("content_preview = ?")
            params.append(content_preview)

        if embedding_id is not None:
            updates.append("embedding_id = ?")
            params.append(embedding_id)

        if message_id is not None:
            updates.append("message_id = ?")
            params.append(message_id)

        if processing_status is not None:
            updates.append("processing_status = ?")
            params.append(processing_status)
            if processing_status == "ready":
                updates.append("processed_at = ?")
                params.append(datetime.now(timezone.utc).isoformat() + "Z")

        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        if not updates:
            return False

        params.append(attachment_id)
        query = f"UPDATE attachments SET {', '.join(updates)} WHERE id = ?"
        rows_affected = self.execute_write(query, tuple(params))

        return rows_affected > 0

    def link_attachment_to_message(self, uuid: str, message_id: int) -> bool:
        """
        Link an attachment to a message by UUID.

        Args:
            uuid: Attachment UUID
            message_id: Message ID to link to

        Returns:
            bool: True if linked, False if attachment not found
        """
        attachment = self.get_attachment_by_uuid(uuid)
        if not attachment:
            return False

        return self.update_attachment(attachment["id"], message_id=message_id)

    def delete_attachment(self, attachment_id: int) -> bool:
        """
        Delete an attachment from the database.

        Args:
            attachment_id: ID of attachment to delete

        Returns:
            bool: True if deleted, False if not found

        NOTE: This only deletes the database record.
        Call FileStorage.delete_attachment() to remove the actual files.
        """
        rows_affected = self.execute_write(
            "DELETE FROM attachments WHERE id = ?",
            (attachment_id,)
        )
        return rows_affected > 0

    def search_attachments_by_description(
        self,
        query: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search attachments by keyword in AI description.

        Args:
            query: Search keyword(s) — multiple words are ANDed (each must match
                   somewhere in the description or filename, in any order)
            limit: Maximum results

        Returns:
            List[dict]: Matching attachments

        USE CASE:
        Keyword search for @file search command.
        For semantic search, use embeddings instead.
        """
        words = query.split()
        if not words:
            return []

        # Build per-word conditions
        conditions = []
        params = []
        for word in words:
            conditions.append("(ai_description LIKE ? OR filename LIKE ?)")
            params.extend([f"%{word}%", f"%{word}%"])

        # Try AND first (all words must match) for precision
        and_params = params + [limit]
        results = self.execute_query(f"""
            SELECT * FROM attachments
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT ?
        """, tuple(and_params))

        # Fall back to OR (any word matches) if AND finds nothing
        if not results and len(words) > 1:
            or_params = params + [limit]
            results = self.execute_query(f"""
                SELECT * FROM attachments
                WHERE {' OR '.join(conditions)}
                ORDER BY created_at DESC
                LIMIT ?
            """, tuple(or_params))

        attachments = []
        for row in results:
            attachment = dict(row)
            if attachment.get("metadata"):
                attachment["metadata"] = json.loads(attachment["metadata"])
            attachments.append(attachment)

        return attachments

    def get_attachment_count(self) -> int:
        """
        Get total number of attachments in database.

        Returns:
            int: Total attachment count
        """
        result = self.execute_query("SELECT COUNT(*) as count FROM attachments")
        return result[0]["count"] if result else 0

    def get_attachment_stats(self) -> Dict:
        """
        Get attachment statistics.

        Returns:
            dict: Statistics breakdown
        """
        # Count by MIME type category
        mime_query = """
            SELECT
                CASE
                    WHEN mime_type LIKE 'image/%' THEN 'images'
                    WHEN mime_type = 'application/pdf' THEN 'pdfs'
                    WHEN mime_type = 'application/json' THEN 'json'
                    ELSE 'text'
                END as category,
                COUNT(*) as count,
                SUM(size_bytes) as total_size
            FROM attachments
            GROUP BY category
        """
        mime_results = self.execute_query(mime_query)

        # Count by processing status
        status_query = """
            SELECT processing_status, COUNT(*) as count
            FROM attachments
            GROUP BY processing_status
        """
        status_results = self.execute_query(status_query)

        # Count with/without descriptions
        desc_query = """
            SELECT
                CASE WHEN ai_description IS NOT NULL THEN 'with_description' ELSE 'without_description' END as has_desc,
                COUNT(*) as count
            FROM attachments
            GROUP BY has_desc
        """
        desc_results = self.execute_query(desc_query)

        return {
            "by_category": {row["category"]: {"count": row["count"], "size_bytes": row["total_size"]} for row in mime_results},
            "by_status": {row["processing_status"]: row["count"] for row in status_results},
            "descriptions": {row["has_desc"]: row["count"] for row in desc_results},
            "total": self.get_attachment_count()
        }
