"""
Background Processing Module for Mneme Memory System

Handles automatic embedding generation and entity assignment:
- Embeddings: Immediate (cheap ~$0.000001/msg, needed for search)
- Entity assignment: Links messages to entities via Haiku (Phase 8)

SPEC ALIGNMENT:
- Line 71: "Embeddings generated in background (batched)"

USAGE:
    queue = BackgroundQueue(db, embedder, config, graph_db)
    queue.add_message(message_id)  # Auto-processes when batch full
    queue.force_process()  # Immediate processing for @remember
"""

from typing import List, Dict, Optional
from datetime import datetime, timezone
import json


class BackgroundError(Exception):
    """Custom exception for background processing errors."""
    pass


class BackgroundQueue:
    """
    Manages automatic embedding generation and entity assignment.

    This class:
    - Generates embeddings immediately for each message
    - Queues messages for entity assignment (Phase 8)
    - Uses Haiku for entity assignment (not string matching)
    - Allows forced processing for @remember command
    """

    def __init__(self, database, embedder, config, graph_db=None):
        """
        Initialize background processing queue.

        Args:
            database: Database instance
            embedder: EmbeddingGenerator instance
            config: Configuration dictionary
            graph_db: GraphDatabase instance (optional, for Phase 5/8)

        Config keys used:
            retrieval.embedding_immediate: Generate embeddings immediately (default True)
            features.entity_summaries.enabled: Enable entity processing (default False)
            features.entity_summaries.auto_extract_entities: Enable automatic extraction (default True)
            features.entity_summaries.assignment_batch_size: Batch size for entity assignment (default 30)
        """
        self.db = database
        self.embedder = embedder
        self.graph_db = graph_db
        self.config = config

        # Background settings from config
        self.embedding_immediate = config.get("retrieval", {}).get("embedding_immediate", True)

        # Entity processing settings (graph + summaries unified)
        entity_config = config.get("features", {}).get("entity_summaries", {})
        self.graph_enabled = entity_config.get("enabled", False) and graph_db is not None
        self.graph_auto_extract = entity_config.get("auto_extract_entities", True)

        self.entity_assignment_enabled = entity_config.get("enabled", False) and graph_db is not None
        self.entity_batch_size = entity_config.get("assignment_batch_size", 2)

        # Entity assignment queue (Phase 8)
        self.entity_queue = []

        # Initialize Anthropic client for Haiku calls (entity assignment)
        self._entity_assigner = None
        if self.entity_assignment_enabled:
            self._init_entity_assigner()

        # Statistics
        self.stats = {
            "embeddings_generated": 0,
            "embedding_cost": 0.0,
            "graph_batches_processed": 0,
            "graph_relationships_extracted": 0,
            "graph_new_entities_found": 0,
            "entity_assignment_batches": 0,
            "entity_links_created": 0,
            "entity_assignment_cost": 0.0
        }

    def _init_entity_assigner(self):
        """Initialize the EntityAssigner with Anthropic client."""
        try:
            import anthropic
            from .entity_assignment import EntityAssigner

            api_key = self.config.get("api_keys", {}).get("anthropic")
            if api_key:
                client = anthropic.Anthropic(api_key=api_key)
                self._entity_assigner = EntityAssigner(client)
            else:
                print("  Warning: No Anthropic API key for entity assignment")
        except ImportError:
            print("  Warning: anthropic package not installed, entity assignment disabled")

    def add_message(self, message_id: int, content: str, sender: str) -> Dict:
        """
        Add message for background processing.

        Args:
            message_id: Database ID of message
            content: Message content
            sender: Message sender ("user" or "assistant")

        Returns:
            dict: Processing status {
                "embedding_generated": bool,
                "queued_for_entity_assignment": bool,
                "entity_batch_processed": bool
            }

        PROCESS:
        1. Generate embedding immediately
        2. Add to entity assignment queue (if Phase 8 enabled)
        3. If queue full, process batch
        4. Return status
        """
        result = {
            "embedding_generated": False,
            "queued_for_entity_assignment": False,
            "entity_batch_processed": False,
            "entity_batch_details": None
        }

        # Step 1: Generate embedding immediately
        if self.embedding_immediate:
            embedding_generated = self._generate_embedding(message_id, content)
            result["embedding_generated"] = embedding_generated

        # Step 2: Add to entity assignment queue (Phase 8)
        if self.entity_assignment_enabled:
            self.entity_queue.append({
                "id": message_id,
                "content": content,
                "sender": sender,
                "added_at": datetime.now(timezone.utc).isoformat()
            })
            result["queued_for_entity_assignment"] = True

            # Process entity batch if queue full
            if len(self.entity_queue) >= self.entity_batch_size:
                entity_result = self._process_entity_assignment_batch()
                result["entity_batch_processed"] = entity_result.get("success", False)
                result["entity_batch_details"] = entity_result

        return result

    def _generate_embedding(self, message_id: int, content: str) -> bool:
        """
        Generate embedding for message and store in database.

        Args:
            message_id: Database ID
            content: Message content

        Returns:
            bool: True if successful, False otherwise

        COST: ~$0.000001 per message (very cheap with OpenAI)
        TIME: ~0.3-0.5 seconds

        SIZE LIMIT:
        - text-embedding-3-small has 8192 token limit
        - Skip embedding for messages > 15,000 chars
        - JSON/structured data tokenizes densely (~2-3 chars/token)
        - 15K chars = ~5-7.5K tokens (safe margin below 8192)
        - Large messages (e.g., JSON pastes) don't need semantic search anyway
        """
        # Check message size before attempting embedding
        if len(content) > 15000:
            print(f"  Skipping embedding for large message ({len(content)} chars, msg_id={message_id})")
            return False

        try:
            # Generate embedding
            embedding = self.embedder.generate_embedding(content)

            # Get cost
            stats = self.embedder.get_usage_stats()
            cost = stats["total_cost"] - self.stats["embedding_cost"]
            self.stats["embedding_cost"] = stats["total_cost"]

            # Store in database
            embedding_id = self.db.add_embedding(
                vector=embedding,
                model=getattr(self.embedder, "model", "text-embedding-3-small"),
                cost=cost
            )

            # Link to message
            self.db.update_message_embedding(message_id, embedding_id)

            # Update stats
            self.stats["embeddings_generated"] += 1

            return True

        except Exception as e:
            print(f"Warning: Failed to generate embedding for message {message_id}: {e}")
            return False


    def _process_entity_assignment_batch(self) -> dict:
        """
        Process batch of messages for entity assignment using Haiku (Phase 8).

        Returns:
            dict: {success, new_entity_names, links_created, messages_processed}

        PROCESS:
        1. Get canonical entities from graph database
        2. Call Haiku API with batch + full entity list
        3. Parse entity assignments
        4. Store links in message_entities table
        5. Update stats and cost

        COST: ~$0.005-0.01 per batch (30 messages)
        TIME: ~2-3 seconds
        """
        _empty = {"success": False, "new_entity_names": [], "links_created": 0, "messages_processed": 0}
        if not self.entity_queue or not self.graph_db:
            return _empty

        if not self._entity_assigner:
            # Lazy init in case it wasn't ready at startup
            self._init_entity_assigner()
            if not self._entity_assigner:
                print("  Entity assignment skipped: no Haiku client available")
                self.entity_queue = self.entity_queue[self.entity_batch_size:]
                return _empty

        try:
            # Get batch
            batch = self.entity_queue[:self.entity_batch_size]

            print(f"  -> Entity assignment for {len(batch)} messages (Haiku)...")

            # Get canonical entities (full list, no cap)
            entity_stats = self.graph_db.get_entity_stats(min_mentions=0)
            canonical_entities = [e["name"] for e in entity_stats]
            entity_data = [
                {
                    "name": e["name"],
                    "aliases": json.loads(e["aliases"]) if e.get("aliases") else []
                }
                for e in entity_stats
            ]

            if not canonical_entities:
                print(f"  No canonical entities yet — discovery mode (new entities will be created)")

            # Safety valve: only filters if entity count would overflow Haiku's context window.
            # At current alias density (~33 chars/entity) this triggers around 13,500 entities —
            # roughly 3+ years of heavy use. Normal operation always sends the full list.
            if len(canonical_entities) > 12_000:
                canonical_entities, entity_data = self._trim_entities_for_context(batch, canonical_entities, entity_data)

            # Fetch preceding messages as context for correction detection
            first_batch_id = batch[0]["id"]
            context_messages = []
            prev_msgs = self.db.get_messages_before(first_batch_id, limit=2)
            for m in prev_msgs:
                context_messages.append({
                    "id": m["id"],
                    "content": m["content"],
                    "sender": m["sender"]
                })

            # Call Haiku for entity assignment + discovery + importance scoring (single call)
            assignments, new_entities, importance_scores, alias_updates, descriptions, corrected_ids = self._entity_assigner.assign_and_discover_batch(
                batch, canonical_entities, entity_data=entity_data,
                context_messages=context_messages if context_messages else None
            )

            # Create any newly discovered entities
            new_entity_ids = {}  # name -> entity_id
            for new_ent in new_entities:
                entity_name = new_ent["name"]
                aliases = new_ent.get("aliases") or None
                try:
                    existing = self.graph_db.get_entity_by_name(entity_name)
                    if not existing:
                        entity_id = self.graph_db.add_entity(entity_name, aliases=aliases)
                        self.stats["graph_new_entities_found"] += 1
                        alias_str = f" (aliases: {', '.join(aliases)})" if aliases else ""
                        print(f"  New entity auto-created: {entity_name}{alias_str}")
                        new_entity_ids[entity_name] = entity_id
                    else:
                        new_entity_ids[entity_name] = existing["id"]
                except Exception as e:
                    print(f"  Error creating entity '{entity_name}': {e}")

            # Apply alias updates for existing entities
            import json as _json
            for update in alias_updates:
                entity_name = update["entity"]
                new_aliases = update["add_aliases"]
                try:
                    existing = self.graph_db.get_entity_by_name(entity_name)
                    if existing:
                        current = _json.loads(existing["aliases"]) if existing.get("aliases") else []
                        current_lower = {a.lower() for a in current}
                        to_add = [a for a in new_aliases if a.lower() not in current_lower]
                        if to_add:
                            merged = current + to_add
                            self.graph_db.update_entity(existing["id"], aliases=merged)
                            print(f"  Alias update: {entity_name} += {to_add}")
                except Exception as e:
                    print(f"  Error updating aliases for '{entity_name}': {e}")

            # Store message descriptions in metadata
            if descriptions:
                for msg in batch:
                    msg_id = msg["id"]
                    desc = descriptions.get(msg_id)
                    if desc:
                        try:
                            self.db.update_message_metadata(msg_id, {"description": desc})
                        except Exception as e:
                            print(f"  Warning: failed to store description for msg {msg_id}: {e}")

            # Store links for existing entity assignments
            links_created = 0
            for msg in batch:
                msg_id = str(msg["id"])
                entities = assignments.get(msg_id, [])

                for entity_info in entities:
                    entity_name = entity_info["entity"]
                    confidence = entity_info["confidence"]

                    entity = self.graph_db.get_entity_by_name(entity_name)
                    if entity:
                        try:
                            result = self.db.add_message_entity(
                                message_id=msg["id"],
                                entity_id=entity["id"],
                                confidence=confidence,
                                source="haiku"
                            )
                            if result:
                                links_created += 1
                        except Exception:
                            continue

            # Store links for new entity assignments (from discovery output)
            for new_ent in new_entities:
                entity_name = new_ent["name"]
                entity_id = new_entity_ids.get(entity_name)
                if not entity_id:
                    continue
                for assignment in new_ent.get("assignments", []):
                    try:
                        result = self.db.add_message_entity(
                            message_id=int(assignment["message_id"]),
                            entity_id=entity_id,
                            confidence=assignment["confidence"],
                            source="haiku"
                        )
                        if result:
                            links_created += 1
                    except Exception:
                        continue

            # Apply importance scores (skip messages manually marked via @remember)
            scores_applied = 0
            for msg in batch:
                msg_id = str(msg["id"])
                score = importance_scores.get(msg_id)
                if score is None:
                    continue
                try:
                    full_msg = self.db.get_message(msg["id"])
                    if full_msg:
                        meta = json.loads(full_msg.get("metadata") or "{}")
                        if meta.get("marked_by"):
                            continue  # @remember score is authoritative — don't overwrite
                    self.db.update_message_importance(
                        msg["id"],
                        float(score),
                        reason="haiku_scored"
                    )
                    scores_applied += 1
                except Exception as e:
                    print(f"  Warning: Failed to apply importance score for msg {msg['id']}: {e}")

            # Apply correction downscore to flagged context messages
            corrections_applied = 0
            for corrected_id in corrected_ids:
                try:
                    msg_id = int(corrected_id)
                    self.db.update_message_importance(msg_id, 1.0, reason="corrected_factual_error")
                    corrections_applied += 1
                    print(f"  ⚠️  Downscored msg {msg_id} (factual correction detected)")
                except Exception as e:
                    print(f"  Warning: Failed to downscore corrected msg {corrected_id}: {e}")

            # Update stats
            self.stats["entity_assignment_batches"] += 1
            self.stats["entity_links_created"] += links_created
            self.stats["entity_assignment_cost"] = self._entity_assigner.get_cost()

            # Mark as checked and clear from queue
            self.db.mark_messages_entity_checked([msg["id"] for msg in batch])
            self.entity_queue = self.entity_queue[self.entity_batch_size:]

            created_names = [e["name"] for e in new_entities if e["name"] in new_entity_ids]
            created_details = [{"name": e["name"], "aliases": e.get("aliases") or []} for e in new_entities if e["name"] in new_entity_ids]
            print(f"  Entity assignment complete ({links_created} links, {scores_applied} scored, {len(created_names)} new entities, cost: ${self._entity_assigner.get_batch_cost():.4f}/batch)")

            return {
                "success": True,
                "new_entity_names": created_names,
                "new_entity_details": created_details,
                "links_created": links_created,
                "messages_processed": len(batch)
            }

        except Exception as e:
            print(f"  Entity assignment failed: {e}")
            # Don't re-queue — skip the batch. A future backfill can catch missed messages.
            self.entity_queue = self.entity_queue[self.entity_batch_size:]
            return {"success": False, "new_entity_names": [], "new_entity_details": [], "links_created": 0, "messages_processed": 0}

    def _trim_entities_for_context(
        self,
        batch: List[Dict],
        canonical_entities: List[str],
        entity_data: List[Dict],
        top_n: int = 500
    ):
        """
        Trim the entity list when it would overflow Haiku's context window.

        EDGE CASE ONLY — only called when entity count exceeds 12,000.
        Normal operation sends the full list.

        Strategy: top 500 by mention count (entity_data is pre-sorted DESC)
        plus any entity whose name or alias appears verbatim in this batch.
        """
        batch_text = " ".join(msg["content"].lower() for msg in batch)

        matched = set()
        for e in entity_data:
            name = e["name"]
            if name.lower().replace("_", " ") in batch_text or name.lower() in batch_text:
                matched.add(name)
                continue
            for alias in e.get("aliases", []):
                if alias.lower() in batch_text:
                    matched.add(name)
                    break

        top_names = set(canonical_entities[:top_n])
        keep = top_names | matched

        filtered_data = [e for e in entity_data if e["name"] in keep]
        filtered_names = [e["name"] for e in filtered_data]
        print(f"  WARNING: entity list too large ({len(canonical_entities):,}), trimmed to {len(filtered_names):,} ({len(matched)} batch matches + {len(top_names)} top-mention)")
        return filtered_names, filtered_data

    def force_process(self) -> Dict:
        """
        Force immediate processing of entity assignment queue.

        Returns:
            dict: Processing result {
                "entity_messages_processed": int,
                "success": bool
            }

        WHEN TO USE:
        - User types @remember (mark as high-importance)
        - Before @recall command (accurate importance for retrieval)
        - End of conversation session
        """
        result = {
            "entity_messages_processed": 0,
            "success": True
        }

        # Process entity assignment queue (Phase 8)
        if self.entity_queue and self.entity_assignment_enabled:
            entity_messages = len(self.entity_queue)
            entity_result = self._process_entity_assignment_batch()
            entity_success = entity_result.get("success", False)
            result["entity_messages_processed"] = entity_messages if entity_success else 0
            result["success"] = entity_success

        return result

    def run_startup_backfill(self) -> int:
        """
        Process any messages that missed entity assignment (e.g. due to API failure).

        Called once at server startup. Loads unchecked messages from DB into the
        entity queue and processes all of them in batches.

        Returns:
            int: Number of messages processed (0 if nothing to do or assignment disabled)

        Raises:
            Exception: propagates API/network errors so the caller can warn the user
        """
        if not self.entity_assignment_enabled or not self.graph_db:
            return 0

        unchecked = self.db.get_unchecked_messages()
        if not unchecked:
            return 0

        print(f"  Startup backfill: {len(unchecked)} messages pending entity assignment")
        self.entity_queue = unchecked + self.entity_queue  # prepend so they go first

        processed = 0
        while self.entity_queue:
            before = len(self.entity_queue)
            batch_result = self._process_entity_assignment_batch()
            after = len(self.entity_queue)
            if batch_result.get("success"):
                processed += before - after
            else:
                # API failure — stop and let caller report
                raise RuntimeError("Entity assignment API call failed during startup backfill")

        return processed

    def get_queue_status(self) -> Dict:
        """
        Get current queue status.

        Returns:
            dict: Queue information

        USEFUL FOR:
        - Debugging
        - Showing user how many messages pending
        - Deciding when to force process
        """
        return {
            "entity_queue_size": len(self.entity_queue),
            "entity_batch_size": self.entity_batch_size,
            "entity_assignment_enabled": self.entity_assignment_enabled
        }

    def get_statistics(self) -> Dict:
        """
        Get processing statistics.

        Returns:
            dict: Statistics including counts and costs

        USEFUL FOR:
        - Cost tracking
        - Performance monitoring
        - User transparency
        """
        total_cost = (
            self.stats["embedding_cost"] +
            self.stats["entity_assignment_cost"]
        )
        return {
            "embeddings_generated": self.stats["embeddings_generated"],
            "embedding_cost": self.stats["embedding_cost"],
            "total_cost": total_cost,
            "avg_cost_per_message": (
                total_cost / max(1, self.stats["embeddings_generated"])
            ),
            # Phase 8: Entity assignment stats
            "entity_assignment_batches": self.stats["entity_assignment_batches"],
            "entity_links_created": self.stats["entity_links_created"],
            "entity_assignment_cost": self.stats["entity_assignment_cost"]
        }

    def clear_queue(self):
        """
        Clear entity assignment queue without processing.

        WARNING: Only use when:
        - Resetting test environment
        - Canceling batch processing
        - Handling error conditions
        """
        self.entity_queue.clear()


if __name__ == "__main__":
    """
    Test the background processing queue.
    """
    print("Background Processing module loaded successfully!")
    print("\nFeatures:")
    print("  - Immediate embedding generation (~$0.000001/msg)")
    print("  - Entity assignment via Haiku (Phase 8)")
    print("  - Auto-create entities from graph extraction")
    print("  - Force processing for @remember")
    print("  - Cost tracking and statistics")
    print("\nTo use:")
    print("  from background import BackgroundQueue")
    print("  queue = BackgroundQueue(db, embedder, config, graph_db)")
    print("  queue.add_message(message_id, content, sender)")
