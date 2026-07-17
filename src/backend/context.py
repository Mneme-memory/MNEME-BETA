"""
Context Assembly Module for Mneme Memory System

Assembles conversation context staying within token budget:
- Recent conversation history (70k tokens)
- Retrieved memories (15k tokens)
- System prompt (3k tokens)
- Buffer for AI response (10k tokens)

WHY TOKEN-BASED CONTEXT?
Maintains conversational continuity - AI remembers recent discussion naturally.
Memories supplement rather than replace natural context flow.

SPEC ALIGNMENT:
- Line 29: "Rolling window: 50-100k tokens active"
- Line 32: "Memory lifecycle: load → use → unload when topic shifts"
- Line 33: "Duplicate detection: don't re-retrieve same memory"

USAGE:
    assembler = ContextAssembler(db, embedder, config)
    context = assembler.assemble_context(recent_messages, user_query)
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta, timezone
import json
import re


try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    print("Warning: tiktoken not installed. Using rough token estimation.")

# Phase 4 Performance: Import numpy at module level (not in loops)
try:
    from numpy import dot
    from numpy.linalg import norm
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("Warning: numpy not installed. Cosine similarity will not be available.")


class ContextError(Exception):
    """Custom exception for context assembly errors."""
    pass


@dataclass(frozen=True)
class DynamicContextBudget:
    """Per-turn budget for uncached, elastic context blocks."""
    total_tokens: Optional[int] = None


class ContextAssembler:
    """
    Handles intelligent context assembly with token budget management.

    This class:
    - Counts tokens accurately
    - Assembles recent conversation + retrieved memories
    - Stays within token budget (75k default)
    - Detects duplicate memories
    - Unloads memories when topic shifts
    """

    def __init__(self, database, embedder, config, graph_db=None, provenance=None):
        """
        Initialize context assembler.

        Args:
            database: Database instance
            embedder: EmbeddingGenerator instance
            config: Configuration dictionary
            graph_db: GraphDatabase instance (optional, for Phase 5)
            provenance: ProvenanceLogger instance (optional, for Phase 12)

        Config keys used:
            context.recent_messages_tokens: Budget for recent messages (default 50000)
            context.duplicate_window_minutes: Time window for duplicate detection (default 30)
            retrieval.max_results: Max memories to retrieve (default 10)
        """
        self.db = database
        self.embedder = embedder
        self.graph_db = graph_db
        self.config = config
        self.provenance = provenance

        # Token budgets from config
        context_config = config.get("context", {})
        self.recent_budget = context_config.get("recent_messages_tokens", 50000)
        self.memory_limit = config.get("retrieval", {}).get("max_results", 10)

        # Retrieval parameters from config
        retrieval_config = config.get("retrieval", {})
        self.similarity_threshold = retrieval_config.get("similarity_threshold", 0.25)
        self.semantic_weight = retrieval_config.get("semantic_weight", 0.4)
        self.importance_weight = retrieval_config.get("importance_weight", 0.4)
        self.recency_weight = retrieval_config.get("recency_weight", 0.2)
        self.entity_match_weight = retrieval_config.get("entity_match_weight", 0.15)

        # Duplicate detection
        self.duplicate_window = context_config.get("duplicate_window_minutes", 30)
        self.loaded_memories = {}  # {message_id: timestamp_loaded}

        # Concept context configuration
        concept_config = config.get("features", {}).get("concepts", {})
        self.concepts_enabled = concept_config.get("enabled", False)
        self.concepts_message_window = concept_config.get("message_window", 5)
        self.concepts_max_retrieved = concept_config.get("max_concepts_retrieved", 2)

        # File attachments context configuration
        files_config = config.get("features", {}).get("attachments", {})
        self.files_enabled = files_config.get("enabled", False)
        self.files_max_displayed = files_config.get("max_files_displayed", 5)
        self.files_similarity_threshold = files_config.get("auto_retrieve_threshold", 0.35)

        # Entity summaries context configuration
        summaries_config = config.get("features", {}).get("entity_summaries", {})
        self.summaries_enabled = summaries_config.get("enabled", False)
        self.summaries_max_entities = summaries_config.get("max_entities_per_retrieval", 3)
        self.summaries_max_tokens = summaries_config.get("max_tokens", 5000)
        self.entity_summary_manager = None  # Lazy-initialized when needed
        self.forced_entity_ids: list = []  # Entity IDs to force-include next retrieval (@entity command)

        # Timeline (daily summaries) context configuration
        timeline_config = config.get("features", {}).get("timeline", {})
        self.timeline_enabled = timeline_config.get("enabled", False)
        self.daily_summary_manager = None  # Lazy-initialized when needed

        # AI Notes configuration
        notes_config = config.get("features", {}).get("notes", {})
        self.notes_enabled = notes_config.get("enabled", True)
        self.notes_max_tokens = notes_config.get("max_tokens", 5000)
        self.notes_cleanup_threshold = notes_config.get("cleanup_threshold_pct", 80) / 100.0

        # Token encoding
        if TIKTOKEN_AVAILABLE:
            try:
                # cl100k_base is used by Claude and GPT-4
                self.encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                print(f"Warning: tiktoken encoding failed ({e}), using fallback token counting")
                self.encoding = None
        else:
            self.encoding = None

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text accurately.

        Args:
            text (str): Text to count tokens for

        Returns:
            int: Token count

        NOTE: Uses tiktoken for accuracy. Falls back to rough estimate
        (1 token ≈ 4 characters) if tiktoken not available.
        """
        if not text:
            return 0

        if self.encoding:
            return len(self.encoding.encode(text))
        else:
            # Rough estimate: 1 token ≈ 4 characters
            return len(text) // 4

    def assemble_context(
        self,
        recent_messages: List[Dict],
        current_query: Optional[str] = None,
        force_retrieve: bool = False,
        dynamic_budget: Optional[DynamicContextBudget] = None
    ) -> Dict:
        """
        Assemble complete context for AI.

        Args:
            recent_messages: Recent conversation messages
            current_query: Current user message (for semantic search)
            force_retrieve: Force memory retrieval even if no query

        Returns:
            dict: {
                "recent_context": List[Dict],  # Recent messages included
                "retrieved_memories": List[Dict],  # Relevant memories
                "notes_context": str,  # AI notes (Phase 11)
                "entity_summaries_context": str,  # Entity summaries (Phase 8)
                "token_counts": {
                    "recent": int,
                    "memories": int,
                    "notes": int,
                    "entity_summaries": int,
                    "total": int
                },
                "metadata": {
                    "recent_messages_included": int,
                    "memories_included": int,
                    "notes_tokens": int,
                    "summaries_enabled": bool,
                    "memories_skipped_duplicate": int
                }
            }

        PROCESS:
        1. Allocate recent messages (70k token budget)
        2. Retrieve relevant memories (10k token budget)
        3. Get entity summaries for retrieved memories (Phase 8, ~5k tokens)
        4. Get concept context (Phase 6, ~500 tokens)
        5. Remove duplicates, clean up old loaded memories
        6. Return assembled context
        """
        # Phase 12: Start provenance turn
        turn_id = None
        if self.provenance:
            try:
                turn_id = self.provenance.start_turn()
            except Exception as e:
                print(f"Warning: Provenance start_turn failed: {e}")

        # Clean up old duplicate tracking
        self._cleanup_loaded_memories()
        dynamic_budget = dynamic_budget or DynamicContextBudget()
        self._last_memory_token_budget_skipped = 0
        self._last_entity_summary_token_budget_skipped = 0
        self._last_concept_token_budget_skipped = 0
        self._last_file_token_budget_skipped = 0
        self._last_forced_entity_omitted = []
        self._last_forced_entity_shortened = []

        # Step 1: Get recent messages within budget
        recent_context, recent_tokens = self._get_recent_messages(
            recent_messages,
            self.recent_budget
        )

        # Step 2: Retrieve relevant memories (if query provided or forced)
        retrieved_memories = []
        memory_tokens = 0
        duplicates_skipped = 0

        if current_query or force_retrieve:
            retrieved_memories, memory_tokens, duplicates_skipped = self._retrieve_memories(
                current_query or "",
                recent_messages,  # Pass recent context
                turn_id=turn_id,  # Phase 12: provenance
                dynamic_budget=dynamic_budget
            )
            # Notify user of actual final count (after duplicate filtering)
            if retrieved_memories:
                print(f"  ✓ Found {len(retrieved_memories)} relevant memories")

        # Step 2.5: Get entity summaries for retrieved memories (Phase 8)
        entity_summaries_context = ""
        entity_summaries_tokens = 0
        entities_bootstrapped = []
        entity_names_loaded = []
        entity_detail_list = []
        if self.summaries_enabled and (retrieved_memories or self.forced_entity_ids):
            entity_summaries_context, entity_summaries_tokens, entities_bootstrapped, entity_names_loaded, entity_detail_list = self._get_entity_summaries_context(
                retrieved_memories,
                turn_id=turn_id,  # Phase 12: provenance
                current_query=current_query,
                dynamic_budget=dynamic_budget
            )
            if entity_summaries_context:
                print(f"  ✓ Generated entity summaries ({entity_summaries_tokens} tokens)")

        # Step 3: Get concept context (Phase 6)
        concept_context = ""
        concept_tokens = 0
        concept_matches = []
        if self.concepts_enabled:
            concept_budget = self._dynamic_budget_remaining(
                dynamic_budget,
                memory_tokens,
                entity_summaries_tokens
            )
            concept_context, concept_tokens, concept_matches = self._get_concept_context(
                recent_messages,
                token_budget=concept_budget
            )
            if concept_context:
                print(f"  ✓ Generated concept context ({concept_tokens} tokens)")

            # Phase 12: Log concept triggers
            if self.provenance and turn_id and concept_matches:
                try:
                    self.provenance.log_concepts(turn_id, concept_matches)
                except Exception as e:
                    print(f"Warning: Provenance log_concepts failed: {e}")

        # Step 3.5: Get files context (Phase 7)
        files_context = ""
        files_tokens = 0
        if self.files_enabled:
            files_budget = self._dynamic_budget_remaining(
                dynamic_budget,
                memory_tokens,
                entity_summaries_tokens,
                concept_tokens
            )
            files_context, files_tokens = self._get_files_context(
                recent_messages,
                token_budget=files_budget
            )
            if files_context:
                print(f"  ✓ Generated files context ({files_tokens} tokens)")

        # Step 4: Load AI notes (Phase 11)
        notes_context = ""
        notes_tokens = 0
        notes_cleanup_needed = False
        if self.notes_enabled:
            notes_context, notes_tokens, notes_cleanup_needed = self._get_notes_context()
            if notes_context:
                print(f"  ✓ Loaded AI notes ({notes_tokens} tokens)")

        # Step 6: Calculate totals
        # Note: graph_tokens removed in Phase 8 cleanup (graph context injection was removed)
        total_tokens = (recent_tokens + memory_tokens + notes_tokens +
                       concept_tokens + files_tokens + entity_summaries_tokens)

        # Phase 12: Finalize provenance turn
        if self.provenance and turn_id:
            try:
                self.provenance.finalize_turn(
                    turn_id=turn_id,
                    query_text=(current_query or "")[:500],  # Truncate for storage
                    tier_filter="standard",
                    memories_considered=duplicates_skipped + len(retrieved_memories),
                    memories_included=len(retrieved_memories),
                    total_tokens_used=total_tokens
                )
            except Exception as e:
                print(f"Warning: Provenance finalize_turn failed: {e}")

        return {
            "recent_context": recent_context,
            "retrieved_memories": retrieved_memories,
            "notes_context": notes_context,  # Phase 11: AI notes
            "notes_cleanup_needed": notes_cleanup_needed,  # Phase 11: Cleanup warning flag
            "concept_context": concept_context,  # Phase 6: Narrative concept context
            "files_context": files_context,  # Phase 7: File attachments context
            "entity_summaries_context": entity_summaries_context,  # Phase 8: Entity summaries
            "provenance_turn_id": turn_id,  # Phase 12: Provenance tracking
            "token_counts": {
                "recent": recent_tokens,
                "memories": memory_tokens,
                "notes": notes_tokens,
                "concepts": concept_tokens,
                "files": files_tokens,
                "entity_summaries": entity_summaries_tokens,
                "total": total_tokens,
                "budget": self.recent_budget,
                "remaining": self.recent_budget - total_tokens
            },
            "metadata": {
                "recent_messages_included": len(recent_context),
                "memories_included": len(retrieved_memories),
                "notes_tokens": notes_tokens,
                "concepts_enabled": self.concepts_enabled,
                "concept_tokens": concept_tokens,
                "concept_names": [m["name"] for m in concept_matches] if concept_matches else [],
                "concept_matches": concept_matches,
                "concepts_skipped_token_budget": self._last_concept_token_budget_skipped,
                "files_enabled": self.files_enabled,
                "files_tokens": files_tokens,
                "files_skipped_token_budget": self._last_file_token_budget_skipped,
                "summaries_enabled": self.summaries_enabled,
                "entity_summaries_tokens": entity_summaries_tokens,
                "entities_bootstrapped": entities_bootstrapped,
                "entity_names_loaded": entity_names_loaded,
                "entity_summaries_detail": entity_detail_list,
                "memories_skipped_duplicate": duplicates_skipped,
                "memories_skipped_token_budget": self._last_memory_token_budget_skipped,
                "entity_summaries_skipped_token_budget": self._last_entity_summary_token_budget_skipped,
                "forced_entities_omitted": self._last_forced_entity_omitted,
                "forced_entities_shortened": self._last_forced_entity_shortened,
                "duplicate_window_minutes": self.duplicate_window
            }
        }

    def _split_dynamic_budget(self, dynamic_budget: DynamicContextBudget) -> tuple:
        """Reserve the first slice of elastic context for entity summaries."""
        if dynamic_budget.total_tokens is None:
            return None, None
        total = max(0, int(dynamic_budget.total_tokens))
        if not self.summaries_enabled:
            return total, 0
        entity_tokens = min(self.summaries_max_tokens, max(0, total // 4))
        memory_tokens = max(0, total - entity_tokens)
        return memory_tokens, entity_tokens

    def _dynamic_budget_remaining(self, dynamic_budget: DynamicContextBudget, *used_tokens: int) -> Optional[int]:
        """Return remaining elastic context budget, or None when unbounded."""
        if dynamic_budget.total_tokens is None:
            return None
        used = sum(max(0, int(tokens or 0)) for tokens in used_tokens)
        return max(0, int(dynamic_budget.total_tokens) - used)

    def _get_recent_messages(
        self,
        messages: List[Dict],
        token_budget: int
    ) -> tuple:
        """
        Get recent messages within token budget.

        Args:
            messages: List of recent messages
            token_budget: Maximum tokens to use

        Returns:
            tuple: (included_messages, total_tokens)

        STRATEGY:
        - Take most recent messages first (reversed order)
        - Keep adding until budget exceeded
        - Return in chronological order

        NOTE: Token budget is the ONLY limit. No artificial message count limit!
        """
        included = []
        total_tokens = 0

        # Process ALL messages in reverse (most recent first)
        # Token budget naturally limits what fits
        for msg in reversed(messages):
            # Build message text
            msg_text = f"{msg['sender']}: {msg['content']}"
            msg_tokens = self.count_tokens(msg_text)

            # Check if adding this message exceeds budget
            if total_tokens + msg_tokens > token_budget:
                break

            included.insert(0, msg)  # Insert at beginning to maintain order
            total_tokens += msg_tokens

        return included, total_tokens

    def _retrieve_memories(
        self,
        query: str,
        recent_messages: List[Dict] = None,
        turn_id: str = None,
        dynamic_budget: Optional[DynamicContextBudget] = None
    ) -> tuple:
        """
        Retrieve relevant memories up to max_results count.

        Args:
            query: Search query for semantic search
            recent_messages: Recent messages (for dedup against active window)
            turn_id: Provenance turn ID (Phase 12)

        Returns:
            tuple: (memories, total_tokens, duplicates_skipped)

        FEATURES:
        - Semantic search for relevance
        - Duplicate detection (don't load same memory twice in session)
        - Count-limited (retrieval.max_results)
        - Mark memories as "referenced" (+2 importance per spec)
        - Provenance logging (Phase 12)
        """
        # Handle optional recent_messages parameter
        if recent_messages is None:
            recent_messages = []
        dynamic_budget = dynamic_budget or DynamicContextBudget()
        memory_token_budget, _entity_token_budget = self._split_dynamic_budget(dynamic_budget)

        from .retrieval import MemoryRetriever

        # Get retriever with config values
        retriever = MemoryRetriever(
            self.db,
            self.embedder,
            similarity_threshold=self.similarity_threshold,
            semantic_weight=self.semantic_weight,
            importance_weight=self.importance_weight,
            recency_weight=self.recency_weight,
            entity_match_weight=self.entity_match_weight,
            graph_db=self.graph_db,
        )

        # Semantic search - deliberately standard-only (unlike @recall in commands.py,
        # which searches both active + standard). Active-tier messages largely overlap
        # the prompt's recent-message window (recent_messages_tokens, default 50k), so
        # auto-retrieval duplicating them here would waste tokens on every turn for no
        # benefit. @recall is explicit and one-off, so it's worth the extra tier.
        # Skip if query is too large (>15K chars to avoid hitting 8192 token limit)
        if query and len(query) > 15000:
            print(f"⚠️ Skipping semantic search: Query too large ({len(query)} chars)")
            results = []
        elif query:
            results = retriever.semantic_search(
                query,
                limit=self.memory_limit * 2,  # Get extras in case of duplicates
                tier="standard"  # Don't retrieve messages already in active window
            )
        else:
            # No query - get recent high-importance memories
            results = []

        # Filter duplicates and enforce count limit
        # Track exclusion reasons for provenance
        included = []
        total_tokens = 0
        duplicates_skipped = 0
        token_budget_skipped = 0
        excluded_reasons = {}  # Phase 12: msg_id -> reason

        for idx, memory in enumerate(results):
            msg_id = memory["id"]

            # Check if already loaded recently
            if msg_id in self.loaded_memories:
                duplicates_skipped += 1
                excluded_reasons[msg_id] = "duplicate"
                continue

            # Check if already in recent context
            if recent_messages and any(msg.get("id") == msg_id for msg in recent_messages):
                duplicates_skipped += 1
                excluded_reasons[msg_id] = "recent_context"
                continue

            # Build memory text
            memory_text = f"[Memory from {memory['timestamp']}]\n{memory['sender']}: {memory['content']}"
            if memory.get("tags"):
                memory_text += f"\n[Tags: {', '.join(memory['tags'])}]"

            mem_tokens = self.count_tokens(memory_text)

            if memory_token_budget is not None and total_tokens + mem_tokens > memory_token_budget:
                token_budget_skipped += 1
                excluded_reasons[msg_id] = "token_budget"
                continue

            # Add to included list with formatted content
            memory_copy = memory.copy()
            memory_copy["formatted_content"] = memory_text
            included.append(memory_copy)
            total_tokens += mem_tokens

            # Mark as loaded (for duplicate detection)
            self.loaded_memories[msg_id] = datetime.now(timezone.utc)

            # Mark original as referenced in database (+2 importance per spec line 62)
            self._mark_as_referenced(msg_id)

            # Stop if we have enough
            if len(included) >= self.memory_limit:
                # Mark any remaining as budget-excluded
                for remaining in results[idx + 1:]:
                    if remaining["id"] not in excluded_reasons:
                        excluded_reasons[remaining["id"]] = "budget"
                break

        self._last_memory_token_budget_skipped = token_budget_skipped

        # Phase 12: Log retrieval provenance
        if self.provenance and turn_id and results:
            try:
                included_ids = {m["id"] for m in included}
                self.provenance.log_retrievals(
                    turn_id=turn_id,
                    all_results=results,
                    included_ids=included_ids,
                    excluded_reasons=excluded_reasons
                )
            except Exception as e:
                print(f"Warning: Provenance log_retrievals failed: {e}")

        return included, total_tokens, duplicates_skipped

    def _mark_as_referenced(self, message_id: int):
        """
        Mark memory as referenced with diminishing returns boost.

        Args:
            message_id: ID of referenced message

        PHASE 4.5: DIMINISHING RETURNS FORMULA (Updated for importance inflation fix)
        Instead of flat +2 each time (which causes inflation in small databases),
        we use logarithmic diminishing returns:

        boost = 1.5 / (1 + log10(reference_count))

        PROGRESSION:
        - 1st reference: +1.50
        - 2nd reference: +1.16
        - 3rd reference: +1.01
        - 5th reference: +0.88
        - 10th reference: +0.75
        """
        try:
            import math

            # Get current message
            msg = self.db.get_message(message_id)
            if not msg:
                return

            # Parse metadata
            metadata = json.loads(msg["metadata"]) if msg["metadata"] else {}

            # Get and increment reference count
            reference_count = metadata.get("reference_count", 0) + 1

            # Calculate diminishing boost
            boost = 1.5 / (1 + math.log10(max(reference_count, 1)))

            # Apply boost to importance
            current_importance = msg["importance_score"]
            new_importance = min(current_importance + boost, 10.0)  # Cap at 10

            # Update metadata with new reference count
            metadata["reference_count"] = reference_count
            self.db.update_message_metadata(message_id, metadata)

            # Update importance score
            self.db.update_message_importance(
                message_id,
                new_importance,
                reason="referenced_in_conversation",
                details={
                    "previous_score": current_importance,
                    "boost": boost,
                    "reference_count": reference_count
                }
            )
        except Exception as e:
            # Don't fail context assembly if this fails
            print(f"Warning: Could not mark message {message_id} as referenced: {e}")

    def _cleanup_loaded_memories(self):
        """
        Remove old entries from loaded memories tracking.

        Removes entries older than duplicate_window_minutes.
        This allows memories to be retrieved again after enough time.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.duplicate_window)

        # Remove old entries
        to_remove = [
            msg_id for msg_id, timestamp in self.loaded_memories.items()
            if timestamp < cutoff
        ]

        for msg_id in to_remove:
            del self.loaded_memories[msg_id]

    def _get_concept_context(
        self,
        recent_messages: List[Dict],
        token_budget: Optional[int] = None
    ) -> tuple:
        """
        Generate concept-based context insights.

        Args:
            recent_messages: Recent conversation messages

        Returns:
            tuple: (concept_context_text, token_count, concept_matches)
                   concept_matches is a list of dicts with keys:
                   id, name, matched_keywords, match_count
                   (Phase 12: structured data for provenance logging)

        ALGORITHM (Phase 6):
        1. Analyze last N messages (configurable, default 5) for keyword mentions
        2. Use local string matching (NO AI calls, $0 cost)
        3. For each concept, count keyword matches
        4. Return top N concepts sorted by match count
        5. Format as readable context (500-1000 tokens)
        6. Place in UNCACHED section (between memories and graph)

        CACHE-SAFE:
        - Concept context is in uncached section
        - Does NOT break adaptive caching (preserves 50-70% savings)
        - Changes every turn (based on recent messages)
        """
        if not self.concepts_enabled:
            return "", 0, []
        if token_budget is not None and token_budget <= 0:
            self._last_concept_token_budget_skipped = self.concepts_max_retrieved
            return "", 0, []

        try:
            # Step 1: Get last N messages (user + assistant)
            window_messages = recent_messages[-self.concepts_message_window:] if len(recent_messages) > self.concepts_message_window else recent_messages

            if not window_messages:
                return "", 0, []

            # Step 2: Extract text from messages for keyword matching
            combined_text = " ".join([
                msg.get("content", "") for msg in window_messages
            ])

            if not combined_text.strip():
                return "", 0, []

            # Step 3: Search for concepts with keyword matches
            matched_concepts = self.db.search_concepts_by_keywords(
                combined_text,
                limit=self.concepts_max_retrieved
            )

            if not matched_concepts:
                return "", 0, []

            # Step 4: Format concept insights within the remaining dynamic budget
            concept_insights = []
            concept_matches = []
            skipped_token_budget = 0

            for concept in matched_concepts:
                # Build insight text for this concept
                insight_lines = [f"\n**{concept['name'].upper()}**"]
                insight_lines.append(f"Definition: {concept['definition']}")

                # Show which keywords matched
                if concept.get("matched_keywords"):
                    keywords_str = ", ".join(concept["matched_keywords"][:5])
                    if len(concept["matched_keywords"]) > 5:
                        keywords_str += f" (+{len(concept['matched_keywords']) - 5} more)"
                    insight_lines.append(f"Triggered by: {keywords_str}")

                insight = "\n".join(insight_lines)
                candidate_insights = concept_insights + [insight]
                candidate_context = "\n--- NARRATIVE CONCEPTS ---\n"
                candidate_context += "Recent conversation relates to these concepts:\n"
                candidate_context += "\n".join(candidate_insights)
                candidate_context += "\n--- END CONCEPTS ---\n"
                candidate_tokens = self.count_tokens(candidate_context)

                if token_budget is not None and candidate_tokens > token_budget:
                    skipped_token_budget += 1
                    continue

                concept_insights.append(insight)
                concept_matches.append({
                    "id": concept.get("id"),
                    "name": concept.get("name", ""),
                    "definition": concept.get("definition", ""),
                    "matched_keywords": concept.get("matched_keywords", []),
                    "match_count": concept.get("match_count", 0)
                })

            self._last_concept_token_budget_skipped = skipped_token_budget

            if not concept_insights:
                return "", 0, concept_matches

            # Step 5: Format final context
            concept_context = "\n--- NARRATIVE CONCEPTS ---\n"
            concept_context += "Recent conversation relates to these concepts:\n"
            concept_context += "\n".join(concept_insights)
            concept_context += "\n--- END CONCEPTS ---\n"

            concept_tokens = self.count_tokens(concept_context)

            return concept_context, concept_tokens, concept_matches

        except Exception as e:
            # Don't fail context assembly if concept context fails
            print(f"⚠️  Concept context generation failed: {e}")
            return "", 0, []

    def _get_files_context(
        self,
        recent_messages: List[Dict],
        token_budget: Optional[int] = None
    ) -> tuple:
        """
        Generate files context block showing available attachments.

        Args:
            recent_messages: Recent conversation messages

        Returns:
            tuple: (files_context_text, token_count)

        ALGORITHM (Phase 7):
        1. Get recent attachments that have AI descriptions
        2. Format each as: [uuid] filename: short_description
        3. Stay within token budget (~50 tokens per file)
        4. Place in UNCACHED section (like concepts, graph)

        CACHE-SAFE:
        - Files context is in uncached section
        - Does NOT break adaptive caching
        - Changes when files are added/described

        FORMAT:
        --- FILES AVAILABLE ---
        Use @file view [uuid] to view any file in detail.

        [abc123] photo.jpg: Black crow on wooden fence, morning light
        [def456] notes.txt: Meeting notes about project timeline
        [ghi789] data.json: User analytics data, 1500 records
        --- END FILES ---
        """
        if not self.files_enabled:
            return "", 0
        if token_budget is not None and token_budget <= 0:
            self._last_file_token_budget_skipped = self.files_max_displayed
            return "", 0

        try:
            # Get recent attachments with descriptions
            attachments = self.db.get_recent_attachments(
                limit=self.files_max_displayed,
                with_description=True
            )

            if not attachments:
                return "", 0

            # Build files context
            file_lines = []
            skipped_token_budget = 0

            for attachment in attachments:
                uuid_short = attachment["uuid"][:8]  # First 8 chars for brevity
                filename = attachment["filename"]
                description = attachment.get("ai_description", "")

                # Truncate description to ~80 chars for brevity
                if len(description) > 80:
                    description = description[:77] + "..."

                line = f"[{uuid_short}] {filename}: {description}"
                candidate_lines = file_lines + [line]
                candidate_context = "\n--- RECENT FILES ---\n"
                candidate_context += "Use @file view [uuid] or @run to query the attachments table for older files.\n\n"
                candidate_context += "\n".join(candidate_lines)
                candidate_context += "\n--- END FILES ---\n"
                candidate_tokens = self.count_tokens(candidate_context)

                if token_budget is not None and candidate_tokens > token_budget:
                    skipped_token_budget += 1
                    continue

                file_lines.append(line)

            self._last_file_token_budget_skipped = skipped_token_budget

            if not file_lines:
                return "", 0

            # Format final context
            files_context = "\n--- RECENT FILES ---\n"
            files_context += "Use @file view [uuid] or @run to query the attachments table for older files.\n\n"
            files_context += "\n".join(file_lines)
            files_context += "\n--- END FILES ---\n"

            files_tokens = self.count_tokens(files_context)

            return files_context, files_tokens

        except Exception as e:
            # Don't fail context assembly if files context fails
            print(f"⚠️  Files context generation failed: {e}")
            return "", 0

    def _get_entity_summaries_context(
        self,
        retrieved_memories: List[Dict],
        turn_id: str = None,
        current_query: str = None,
        dynamic_budget: Optional[DynamicContextBudget] = None
    ) -> tuple:
        """
        Generate entity summaries context for retrieved memories (Phase 8).

        Args:
            retrieved_memories: Memories that were retrieved this turn
            turn_id: Provenance turn ID (Phase 12)
            current_query: Current user message for direct string matching

        Returns:
            tuple: (entity_summaries_context_text, token_count, bootstrapped_names, entity_names)

        ALGORITHM:
        1. String-match entities against user's message (catches proper nouns)
        2. Get entities from all retrieved memories
        3. Score entities by: confidence × log(link_count + 1) × recency_factor
        4. Select top N unique entities (configured, default 3)
        5. Get or create summaries for each (lazy generation)
        6. Format summaries for context injection

        CACHE-SAFE:
        - Entity summaries are in uncached section
        - Changes based on which memories are retrieved
        """
        if not self.summaries_enabled or (not retrieved_memories and not self.forced_entity_ids):
            return "", 0, [], [], []
        dynamic_budget = dynamic_budget or DynamicContextBudget()
        _memory_token_budget, entity_token_budget = self._split_dynamic_budget(dynamic_budget)

        try:
            import math

            # Lazy-initialize the entity summary manager
            if self.entity_summary_manager is None:
                from src.backend.entity_summaries import EntitySummaryManager
                self.entity_summary_manager = EntitySummaryManager(
                    self.config, self.db, self.graph_db
                )

            # Step 0: Direct string match — catch entity names in user's message
            # Semantic search misses short proper nouns that don't embed well
            entity_scores = {}  # entity_id -> {entity_data, total_score, count}

            now = datetime.now(timezone.utc)

            # Step 0a: Force-include entities requested via @entity command
            forced_ids = self.forced_entity_ids[:]
            self.forced_entity_ids = []  # Consume immediately — one-shot per turn
            for entity_id in forced_ids:
                ent = self.graph_db.get_entity_by_id(entity_id) if self.graph_db else None
                if ent:
                    link_count = self._get_entity_link_count(entity_id)
                    entity_scores[entity_id] = {
                        "entity": {
                            "id": entity_id,
                            "name": ent["name"],
                            "aliases": ent.get("aliases"),
                            "mention_count": ent.get("mention_count", 0)
                        },
                        "link_count": link_count,
                        "total_confidence": 2.0,  # Above string-match (1.5) and memory-sourced
                        "memory_count": 1,
                        "most_recent": now.isoformat(),
                        "forced": True
                    }
            if forced_ids:
                names = [entity_scores[eid]["entity"]["name"] for eid in forced_ids if eid in entity_scores]
                if names:
                    print(f"  ✓ Force-included entities: {', '.join(names)}")

            if current_query and self.graph_db:
                query_lower = current_query.lower()
                all_entities = self.graph_db.get_entity_stats(min_mentions=0)

                for ent in all_entities:
                    name = ent.get("name", "")
                    normalized = name.replace("_", " ").lower()
                    if len(normalized) < 3:
                        continue

                    matched = normalized in query_lower
                    if not matched and ent.get("aliases"):
                        for alias in ent["aliases"].split(","):
                            alias_norm = alias.strip().replace("_", " ").lower()
                            if len(alias_norm) >= 3 and alias_norm in query_lower:
                                matched = True
                                break

                    if matched:
                        entity_id = ent["id"]
                        link_count = self._get_entity_link_count(entity_id)
                        entity_scores[entity_id] = {
                            "entity": {
                                "id": entity_id,
                                "name": name,
                                "aliases": ent.get("aliases"),
                                "mention_count": ent.get("mention_count", 0)
                            },
                            "link_count": link_count,
                            "total_confidence": 1.5,
                            "memory_count": 1,
                            "most_recent": now.isoformat(),
                            "string_matched": True
                        }

                if entity_scores:
                    names = [d["entity"]["name"] for d in entity_scores.values()]
                    print(f"  ✓ String-matched entities: {', '.join(names)}")

            # Step 1: Collect all entities from retrieved memories

            for memory in retrieved_memories:
                msg_id = memory.get("id")
                if not msg_id:
                    continue

                # Get entities for this message
                entities = self.db.get_entities_for_message(msg_id)

                for entity_link in entities:
                    entity_id = entity_link.get("id")  # Column is 'id' from entities table
                    confidence = entity_link.get("confidence", 0.8)

                    if not entity_id:
                        continue

                    if entity_id not in entity_scores:
                        # Use entity data from the join (already have name, etc.)
                        entity = {
                            "id": entity_id,
                            "name": entity_link.get("name"),
                            "aliases": entity_link.get("aliases"),
                            "mention_count": entity_link.get("mention_count", 0)
                        }

                        # Get link count for this entity
                        link_count = self._get_entity_link_count(entity_id)

                        entity_scores[entity_id] = {
                            "entity": entity,
                            "link_count": link_count,
                            "total_confidence": 0,
                            "memory_count": 0,
                            "most_recent": None
                        }

                    # Accumulate confidence
                    entity_scores[entity_id]["total_confidence"] += confidence
                    entity_scores[entity_id]["memory_count"] += 1

                    # Track most recent memory timestamp
                    mem_timestamp = memory.get("timestamp")
                    current_recent = entity_scores[entity_id]["most_recent"]
                    if mem_timestamp and (not current_recent or mem_timestamp > current_recent):
                        entity_scores[entity_id]["most_recent"] = mem_timestamp

            if not entity_scores:
                return "", 0, [], [], []

            # Step 2: Calculate relevance scores
            def calculate_relevance(entity_data):
                avg_confidence = entity_data["total_confidence"] / max(1, entity_data["memory_count"])
                link_factor = math.log(entity_data["link_count"] + 1)

                # Recency factor: boost entities from recent memories
                recency_factor = 1.0
                if entity_data["most_recent"]:
                    try:
                        mem_time = datetime.fromisoformat(entity_data["most_recent"].replace("Z", "+00:00"))
                        hours_ago = (now - mem_time).total_seconds() / 3600
                        # Decay over 30 days, minimum factor 0.3
                        recency_factor = max(0.3, 1.0 - (hours_ago / (30 * 24)) * 0.7)
                    except (ValueError, TypeError, KeyError):
                        pass

                # Type priority: concrete entities (people, projects, events) surface
                # above abstract themes. Convention: CapitalCase = concrete, lowercase = abstract.
                name = entity_data["entity"].get("name", "")
                type_priority = 2.0 if (name and name[0].isupper()) else 1.0

                return avg_confidence * link_factor * recency_factor * entity_data["memory_count"] * type_priority

            # Step 3: Select top N entities — guaranteed slots for string-matched/forced
            priority_entities = [
                e for e in entity_scores.values()
                if e.get("string_matched") or e.get("forced")
            ]
            other_entities = sorted(
                [e for e in entity_scores.values() if not e.get("string_matched") and not e.get("forced")],
                key=calculate_relevance,
                reverse=True
            )
            # Priority entities first, then fill remaining slots with top-scoring others
            remaining_slots = max(0, self.summaries_max_entities - len(priority_entities))
            top_entities = priority_entities + other_entities[:remaining_slots]

            if not top_entities:
                return "", 0, [], [], []

            all_scored = priority_entities + other_entities
            scored_for_log = [
                {
                    "entity_id": ed["entity"]["id"],
                    "entity_name": ed["entity"].get("name", ""),
                    "relevance_score": calculate_relevance(ed)
                }
                for ed in all_scored
            ]

            # Step 4: Get or create summaries for each
            summary_blocks = []
            total_tokens = 0
            bootstrapped_names = []
            entity_names = []
            entity_detail_list = []
            included_entity_ids = set()
            omitted_forced_entities = []
            shortened_forced_entities = []
            skipped_token_budget = 0

            for entity_data in top_entities:
                entity = entity_data["entity"]
                entity_name = entity.get("name", "Unknown")
                is_forced = entity_data.get("forced", False)

                # Get or create summary (lazy generation)
                result = self.entity_summary_manager.get_or_create_summary(
                    entity["id"],
                    show_progress=True  # Shows "Generating summaries for X..."
                )

                if result.get("bootstrapped"):
                    bootstrapped_names.append(entity_name)

                if result.get("all_time"):
                    summary_text = result["all_time"]

                    # Append current month if available — all-time only covers
                    # frozen past months, so without this the AI has stale info.
                    # Use condensed brief version to save context tokens;
                    # fall back to full current_month if brief isn't available yet.
                    current_brief = result.get("current_month_short") or result.get("current_month")
                    if current_brief:
                        summary_text += f"\n\nThis month:\n{current_brief}"

                    # Format block
                    block = f"[{entity_name}]\n{summary_text}"
                    block_tokens = self.count_tokens(block)

                    if entity_token_budget is not None and total_tokens + block_tokens > entity_token_budget:
                        remaining_budget = max(0, entity_token_budget - total_tokens)
                        if is_forced:
                            fitted_block = self._fit_forced_entity_block(block, remaining_budget)
                            if fitted_block:
                                shortened_forced_entities.append(entity_name)
                                block = fitted_block
                                block_tokens = self.count_tokens(block)
                            else:
                                omitted_forced_entities.append(entity_name)
                                skipped_token_budget += 1
                                print(f"⚠️ Entity summary for {entity_name} was too large for remaining context")
                                continue
                        else:
                            skipped_token_budget += 1
                            continue

                    summary_blocks.append(block)
                    total_tokens += block_tokens
                    entity_names.append(entity_name)
                    included_entity_ids.add(entity["id"])
                    entity_detail_list.append({"name": entity_name, "summary": summary_text})

            self._last_entity_summary_token_budget_skipped = skipped_token_budget
            self._last_forced_entity_omitted = omitted_forced_entities
            self._last_forced_entity_shortened = shortened_forced_entities

            if not summary_blocks:
                if self.provenance and turn_id and scored_for_log:
                    try:
                        self.provenance.log_entity_summaries(
                            turn_id=turn_id,
                            scored_entities=scored_for_log,
                            included_ids=set()
                        )
                    except Exception as e:
                        print(f"Warning: Provenance log_entity_summaries failed: {e}")
                return "", 0, bootstrapped_names, entity_names, entity_detail_list

            # Phase 12: Log entity summary selection after token-budget filtering.
            if self.provenance and turn_id:
                try:
                    self.provenance.log_entity_summaries(
                        turn_id=turn_id,
                        scored_entities=scored_for_log,
                        included_ids=included_entity_ids
                    )
                except Exception as e:
                    print(f"Warning: Provenance log_entity_summaries failed: {e}")

            # Step 5: Format final context
            summaries_context = "\n--- ENTITY CONTEXT ---\n"
            summaries_context += "Historical context for entities discussed in retrieved memories:\n\n"
            summaries_context += "\n\n".join(summary_blocks)
            summaries_context += "\n--- END ENTITY CONTEXT ---\n"

            final_tokens = self.count_tokens(summaries_context)

            return summaries_context, final_tokens, bootstrapped_names, entity_names, entity_detail_list

        except Exception as e:
            # Don't fail context assembly if entity summaries fail
            print(f"⚠️  Entity summaries context generation failed: {e}")
            import traceback
            traceback.print_exc()
            return "", 0, [], [], []

    def _fit_forced_entity_block(self, block: str, token_budget: int) -> Optional[str]:
        """Keep a visible excerpt for an explicit @entity request when possible."""
        if token_budget <= 200:
            return None

        marker = (
            "\n\n[Mneme shortened this entity summary because remaining context "
            "was limited.]\n\n"
        )
        max_chars = max(200, token_budget * 4)

        for _attempt in range(6):
            if self.count_tokens(block) <= token_budget:
                return block
            available = max(80, max_chars - len(marker))
            head_chars = max(40, int(available * 0.7))
            tail_chars = max(0, available - head_chars)
            block = block[:head_chars] + marker + (block[-tail_chars:] if tail_chars else "")
            max_chars = max(120, int(max_chars * 0.75))

        return block if self.count_tokens(block) <= token_budget else None

    def _get_entity_link_count(self, entity_id: int) -> int:
        """Get the number of message links for an entity."""
        try:
            result = self.db.execute_query(
                "SELECT COUNT(*) as count FROM message_entities WHERE entity_id = ?",
                (entity_id,)
            )
            return result[0]["count"] if result else 0
        except Exception:
            return 0

    def _get_timeline_context(self) -> tuple:
        """
        Generate timeline context from daily summaries (Phase 9).

        Returns:
            tuple: (timeline_context_text, token_count)

        ALGORITHM:
        1. Check if timeline feature is enabled
        2. Get 7-day summary block from DailySummaryManager
        3. Return formatted text for prompt injection

        CACHE-SAFE:
        - Timeline goes in system blocks with cache_control
        - Changes once per day (when new day starts)
        - Cache naturally rebuilds when timeline updates
        """
        if not self.timeline_enabled:
            return "", 0

        try:
            # Lazy-initialize the daily summary manager
            if self.daily_summary_manager is None:
                from .daily_summaries import DailySummaryManager
                self.daily_summary_manager = DailySummaryManager(
                    self.config, self.db
                )

            # Get formatted 7-day block
            timeline_text = self.daily_summary_manager.get_seven_day_block()

            if not timeline_text:
                return "", 0

            timeline_tokens = self.count_tokens(timeline_text)

            return timeline_text, timeline_tokens

        except Exception as e:
            # Don't fail context assembly if timeline fails
            print(f"Timeline context generation failed: {e}")
            return "", 0

    def get_timeline_context(self) -> tuple:
        """
        Public method to get timeline context.

        Returns:
            tuple: (timeline_context_text, token_count)
        """
        return self._get_timeline_context()

    def clear_loaded_memories(self):
        """
        Clear all loaded memories.

        Call this when:
        - Topic shifts significantly
        - User explicitly requests with @clear command
        - Starting new conversation session
        """
        self.loaded_memories.clear()

    def _get_notes_context(self) -> tuple:
        """
        Load AI notes from database and format for prompt injection (Phase 11).

        Returns:
            tuple: (notes_context_text, token_count, cleanup_needed)
        """
        try:
            notes = self.db.get_all_notes()
            if not notes:
                return "", 0, False

            # Format notes
            parts = []
            for note in notes:
                parts.append(f"## {note['section']}")
                parts.append(note['content'])
                parts.append("")  # Blank line between sections

            notes_text = "\n".join(parts).strip()
            notes_tokens = self.count_tokens(notes_text)

            # Check if cleanup is needed
            cleanup_needed = notes_tokens > (self.notes_max_tokens * self.notes_cleanup_threshold)

            # Build header with token usage
            header = f"📝 AI NOTES ({notes_tokens}/{self.notes_max_tokens} tokens)"
            if cleanup_needed:
                header += "\n⚠️ Notes approaching limit - please condense or remove outdated sections"

            notes_context = f"{header}\n\n{notes_text}"
            total_tokens = self.count_tokens(notes_context)

            # Truncate if over budget
            if total_tokens > self.notes_max_tokens:
                # Trim notes to fit (remove from end)
                while notes and total_tokens > self.notes_max_tokens:
                    notes.pop()
                    parts = []
                    for note in notes:
                        parts.append(f"## {note['section']}")
                        parts.append(note['content'])
                        parts.append("")
                    notes_text = "\n".join(parts).strip()
                    notes_context = f"{header}\n[Some sections truncated to fit budget]\n\n{notes_text}"
                    total_tokens = self.count_tokens(notes_context)

            return notes_context, total_tokens, cleanup_needed

        except Exception as e:
            print(f"⚠️ Notes context generation failed: {e}")
            return "", 0, False


if __name__ == "__main__":
    """
    Test the context assembler.
    """
    print("Context Assembly module loaded successfully!")
    print("\nFeatures:")
    print("  ✓ Token-based context assembly (70k recent + 15k memories)")
    print("  ✓ Duplicate detection (30-minute window)")
    print("  ✓ Budget management and adjustment")
    print("  ✓ Referenced memory importance boost (+2)")
    print("\nTo use:")
    print("  from context import ContextAssembler")
    print("  assembler = ContextAssembler(db, embedder, config)")
    print("  context = assembler.assemble_context(recent_messages, query)")
