"""
Entity Assignment Module for Mneme Memory System

Uses Anthropic tool use for guaranteed valid JSON output.
Haiku is forced to call a tool with a strict schema — the API constrains
output at the token level, eliminating JSON parse failures entirely.

Used by:
- Background pipeline (background.py) for live entity assignment + discovery
- Backfill scripts for batch processing
"""

from typing import Dict, List, Tuple

from .error_handling import retry_with_backoff


# ============================================================================
# Tool schemas — Anthropic API guarantees output matches these exactly
# ============================================================================

ASSIGNMENT_TOOL = {
    "name": "submit_entity_assignments",
    "description": "Submit entity assignments and importance scores for analyzed messages. Only include messages that have at least one entity assigned in 'assignments' — but score ALL messages in 'message_scores'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assignments": {
                "type": "object",
                "description": "Map of message_id (string) to list of entity assignments. Omit messages with 0 entities.",
                "additionalProperties": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entity": {"type": "string", "description": "Entity name from the canonical list"},
                            "confidence": {"type": "number", "description": "0.5 = tangential, 1.0 = definitely about this"}
                        },
                        "required": ["entity", "confidence"]
                    }
                }
            },
            "message_scores": {
                "type": "object",
                "description": "Importance score (1-9) for EVERY message in the batch, keyed by message_id string. Score ALL messages, even those with no entities.",
                "additionalProperties": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 9
                }
            }
        },
        "required": ["assignments", "message_scores"]
    }
}

COMBINED_TOOL = {
    "name": "submit_entity_assignments",
    "description": "Submit entity assignments, importance scores, and optionally propose new entities. Only include messages that have at least one entity in 'assignments' — but score ALL messages in 'message_scores'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assignments": {
                "type": "object",
                "description": "Map of message_id (string) to list of entity assignments. Omit messages with 0 entities.",
                "additionalProperties": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entity": {"type": "string", "description": "Entity name from the canonical list"},
                            "confidence": {"type": "number", "description": "0.5 = tangential, 1.0 = definitely about this"}
                        },
                        "required": ["entity", "confidence"]
                    }
                }
            },
            "message_scores": {
                "type": "object",
                "description": "Importance score (1-9) for EVERY message in the batch, keyed by message_id string. Score ALL messages, even those with no entities.",
                "additionalProperties": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 9
                }
            },
            "new_entities": {
                "type": "array",
                "description": "New entity proposals. Almost always empty. Maximum 5.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Self-explanatory entity name"},
                        "aliases": {
                            "type": "array",
                            "description": "Common shorthand names (e.g. 'Sanni' for 'Sanni_Friend', 'Mneme' for 'Mneme_project'). Usually 0-2 items.",
                            "items": {"type": "string"}
                        },
                        "assignments": {
                            "type": "array",
                            "description": "Which messages this new entity applies to",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "message_id": {"type": "string"},
                                    "confidence": {"type": "number"}
                                },
                                "required": ["message_id", "confidence"]
                            }
                        }
                    },
                    "required": ["name", "aliases", "assignments"]
                }
            },
            "alias_updates": {
                "type": "array",
                "description": "Add aliases to EXISTING entities when a message uses a shorthand not yet in the entity's aliases. Almost always empty.",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "Canonical entity name from the list"},
                        "add_aliases": {
                            "type": "array",
                            "description": "Shorthand names to add (e.g. ['Sanni'] for entity 'Sanni_Friend')",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["entity", "add_aliases"]
                }
            },
            "message_descriptions": {
                "type": "object",
                "description": "A 1-4 word topic description for EVERY message in the batch, keyed by message_id string. Describe the single core topic of the message. Examples: 'cooking with grandma', 'morning anxiety', 'Mneme architecture decision', 'casual greeting'. Must cover ALL message IDs.",
                "additionalProperties": {
                    "type": "string"
                }
            },
            "corrected_messages": {
                "type": "array",
                "description": "IDs (as strings) of messages (context or batch) that contain factual errors corrected by a later message. Flag the WRONG message, not the correction. Usually empty.",
                "items": {"type": "string"}
            }
        },
        "required": ["assignments", "message_scores", "new_entities", "alias_updates", "message_descriptions"]
    }
}


# ============================================================================
# Prompts — no OUTPUT FORMAT section needed, tool schema handles structure
# ============================================================================

ASSIGNMENT_PROMPT = """You are analyzing conversation messages to identify which entities are discussed and how important each message is.

**CANONICAL ENTITIES:**
{entity_list}

**MESSAGES TO ANALYZE:**
{messages}

**JOB 1 — ENTITY ASSIGNMENT:**
1. ONLY use entities from the canonical list — do NOT invent new ones
2. Be selective — only include entities that are substantively discussed, not just mentioned in passing
3. A message can have 0 entities (pleasantries, greetings, meta-conversation)
4. Most messages will have 0-3 entities
5. Focus on the core topic being discussed, not tangential mentions
Confidence: 1.0 = definitely about this entity, 0.5 = tangentially related

**WHAT COUNTS AS "SUBSTANTIVELY DISCUSSED":**
- The message is primarily about that entity/topic
- The entity is being explained, explored, or analyzed
- Questions are being asked specifically about the entity
- Decisions are being made regarding the entity

**WHAT DOES NOT COUNT:**
- Brief mentions in passing ("like consciousness or whatever")
- Examples used to explain something else
- References without discussion

**JOB 2 — IMPORTANCE SCORING:**
Score EVERY message 1-9 in message_scores. Include ALL message IDs, even those with no entities.
- 1-2: Greetings, small talk, simple acknowledgments ("ok", "thanks", "sure")
- 3-4: Casual conversation, routine questions, everyday topics — THIS IS THE DEFAULT
- 5-6: Substantive discussion, meaningful ideas being explored
- 7-8: Key insights, important decisions, significant personal moments
- 9: Major breakthroughs, profound realizations, critical turning points

CALIBRATION — this is critical. Err strongly toward lower scores:
- Expected distribution: ~20% score 1-2, ~45% score 3-4, ~20% score 5-6, ~12% score 7-8, ~3% score 9
- A message being long, thoughtful, or emotionally present does NOT make it 7+
- 7+ requires something genuinely rare: a decision that changes things, a realization that shifts perspective, a commitment or vulnerability that stands out across hundreds of conversations
- When in doubt between two adjacent scores, pick the lower one

**Respond ONLY with the tool call. No preamble or commentary.**"""


COMBINED_PROMPT = """You are analyzing conversation messages for a memory system. You have three jobs:

**JOB 1 — ENTITY ASSIGNMENT:** For each message, identify which entities from the canonical list are substantively discussed (not just mentioned in passing). Most messages have 0-3 entities.

**JOB 2 — IMPORTANCE SCORING:** Score EVERY message 1-9 in message_scores. Include ALL message IDs, even those with no entities.
- 1-2: Greetings, small talk, simple acknowledgments ("ok", "thanks", "sure")
- 3-4: Casual conversation, routine questions, everyday topics — THIS IS THE DEFAULT
- 5-6: Substantive discussion, meaningful ideas being explored
- 7-8: Key insights, important decisions, significant personal moments
- 9: Major breakthroughs, profound realizations, critical turning points

CALIBRATION — this is critical. Err strongly toward lower scores:
- Expected distribution: ~20% score 1-2, ~45% score 3-4, ~20% score 5-6, ~12% score 7-8, ~3% score 9
- A message being long, thoughtful, or emotionally present does NOT make it 7+
- 7+ requires something genuinely rare: a decision that changes things, a realization that shifts perspective, a commitment or vulnerability that stands out across hundreds of conversations
- When in doubt between two adjacent scores, pick the lower one

**JOB 3 — ENTITY DISCOVERY:** Check if ANY message discusses a topic NOT covered by the canonical list. Most batches need **0 new entities** — the list is comprehensive.

**CANONICAL ENTITIES:**
{entity_list}

{alias_context}{context_section}**MESSAGES TO ANALYZE:**
{messages}

**ASSIGNMENT RULES:**
- ONLY assign entities from the canonical list
- Be selective — substantive discussion only, not passing mentions
- A message can have 0 entities (pleasantries, greetings, meta-conversation)
- Confidence: 1.0 = definitely about this, 0.5 = tangentially related

**DISCOVERY RULES — when to propose a NEW entity:**
The bar is **deep engagement** — the conversation explores, analyzes, or emotionally engages with a topic not covered by any existing entity.

A new entity must be:
- **Deeply engaged with** — not just named or mentioned in passing
- **Broad enough** to accumulate meaningful history (not a single event or fleeting moment)
- **Specific enough** to be distinct from existing entities (not a synonym or subset)

A single song, show, character, or program CAN become an entity if deeply engaged with (analysis, emotional response, extended discussion) — not just "I listened to X" or "I watched Y".

**DO NOT propose:**
- Too vague/generic: "action", "good", "growth", "life", "happy", "nice"
- One-off events: "bus_ticket_purchase", "optician_appointment"
- Passing media mentions: a song → "songs"/"music", a game → "games", a show → "scifi"/the show's entity
- Too-specific moments: "dehydrated_soy_technique", "dryer_time_calculation"
- Technical implementation details: specific bugs, migration steps, config tweaks
- Routine logistics: grocery, laundry, packing, scheduling
- Redundant sub-topics: if existing entities cover it in combination, skip it
- Specific emotions as new entities: "felt_sad_today" → already "melancholy"/"mental_health"
- Specific people details: "Sanni's job" → already "Sanni_Friend"

**Naming rules for new entities:**
- People: Name_Context ("Dario_Anthropic", "Sanni_Friend")
- Projects: Actual names ("Mneme") not generic ("memory_project")
- Concepts: General form ("anxiety" not "anxious_about_interview"), underscores for multi-word

**CRITICAL — Names must be self-explanatory:**
Entity names will be read by future AI instances with NO access to the conversation that created them.
The name alone must make the topic clear. If it could be interpreted multiple ways, add a qualifying word.

BAD (ambiguous): "witness_dynamic", "substance_awareness", "pattern_recognition", "bridge_concept"
GOOD (clear): "witnessing_as_consciousness_practice", "psychoactive_substance_awareness", "cognitive_pattern_recognition", "conceptual_bridging_between_domains"

Test: "Would another AI reading ONLY this name understand what topic it covers?"
If not, make it more specific. Err on the side of longer-but-clear over short-but-cryptic.

**Before proposing, verify:**
1. Ask: "Would the conversations I'd tag with this new entity already fit under an existing entity?" If yes, use the existing one — even if its name isn't identical. The test is whether the TOPIC is already covered, not whether the NAME matches.
2. Deep engagement present — not just named or briefly referenced
3. Can't be covered by any combination of existing entities

**JOB 4 — ALIASES:**

For **new entities**: include common shorthand names in `aliases`. Examples:
- "Sanni_Friend" → aliases: ["Sanni"]
- "Mneme" → aliases: [] (name is already the shorthand)
- "cognitive_pattern_recognition" → aliases: [] (no natural shorthand)
- People always get their first name as an alias if the canonical name has a suffix

For **existing entities** (`alias_updates`): if a message uses a name or shorthand that clearly refers to an existing entity but isn't its canonical name AND isn't already an obvious alias, add it. Examples:
- Message says "Sanni" but entity is "Sanni_Friend" with no aliases → add alias
- Message says "my dog" but entity is "River_dog" → too generic, skip
- Only propose when confident the shorthand is unambiguous

**CONFLICT RULE — check the Known Aliases section above before proposing:**
Never add a name as an alias for Entity A if:
- It is already listed as an alias for a different Entity B, OR
- It is the first part of another entity's canonical name (e.g. "Eve" is the first part of "Eve_Ex" → "Eve" belongs to Eve_Ex, not anyone else)
When in doubt whether a name refers to entity A or entity B, skip the alias — do not guess.

**JOB 5 — MESSAGE DESCRIPTIONS:**
For EVERY message in the batch, write a 1-4 word description of the single core topic.
- Be specific and concrete: "cooking with grandma" not "food memory"
- Use natural language, not snake_case
- For greetings/chitchat: "casual greeting", "small talk"
- For AI assistant messages: describe what Claude is doing: "explaining memory system", "asking follow-up question"
- Include ALL message IDs in message_descriptions, even simple ones

**JOB 6 — CORRECTION DETECTION:**
If ANY message (context or batch) contains factual errors, hallucinated content, or wrong information that a later message in the batch explicitly corrects, add the INCORRECT message's ID to `corrected_messages`. This prevents wrong information from surfacing in future memory retrieval.
- Only flag clear factual corrections ("no, that's wrong", "actually it's X not Y", "that's not what happened")
- Do NOT flag opinion changes, preference updates, or evolving discussions
- Flag the message that CONTAINS THE ERROR, not the message that corrects it
- Usually empty — most batches contain no corrections

**Respond ONLY with the tool call. No preamble or commentary.**"""


# ============================================================================
# Formatting helpers
# ============================================================================

def format_messages_for_prompt(messages: List[Dict]) -> str:
    """Format a batch of messages for the entity assignment prompt. No truncation."""
    return "\n".join([
        f"[ID: {msg['id']}] {msg['sender']}: {msg['content']}"
        for msg in messages
    ])


def format_entity_list(canonical_entities: List[str]) -> str:
    """Format canonical entities for the prompt. Sends full list (no cap)."""
    return ", ".join(canonical_entities)


def format_alias_context(entity_data: List[Dict]) -> str:
    """Format a known-aliases section for the prompt.

    Shows existing aliases so Haiku knows which names are already claimed,
    preventing a person's first name (e.g. 'Eve' from 'Eve_Ex') from being
    added as an alias for a completely different entity.  Only entities that
    actually have aliases are included.  Aliases are capped at 5 per entity
    to keep token usage reasonable.
    """
    lines = []
    for e in entity_data:
        # Only proper nouns (people, projects) start with a capital letter.
        # Concept entities (anxiety, work_stress) can't be confused with first names,
        # so including their aliases would just add noise.
        if not e["name"][0].isupper():
            continue
        aliases = (e.get("aliases") or [])[:5]
        if aliases:
            lines.append(f"- {e['name']}: {', '.join(aliases)}")
    if not lines:
        return ""
    return (
        "**KNOWN ENTITY ALIASES (already assigned — do not add these as aliases for a different entity):**\n"
        + "\n".join(lines)
        + "\n\n"
    )


# ============================================================================
# Validation — applied to tool output (already valid JSON, just need to
# check entity names against canonical list)
# ============================================================================

def validate_assignments(
    data: Dict,
    canonical_entities: List[str]
) -> Dict[str, List[Dict]]:
    """Validate entity names in assignments against the canonical list."""
    canonical_lower = {e.lower(): e for e in canonical_entities}
    assignments_raw = data.get("assignments", {})

    validated = {}
    for msg_id, entities in assignments_raw.items():
        valid_entities = []
        if isinstance(entities, list):
            for item in entities:
                if isinstance(item, dict):
                    entity_name = item.get("entity", "")
                    confidence = item.get("confidence", 0.8)
                    if entity_name.lower() in canonical_lower:
                        valid_entities.append({
                            "entity": canonical_lower[entity_name.lower()],
                            "confidence": min(1.0, max(0.0, float(confidence)))
                        })
        if valid_entities:
            validated[str(msg_id)] = valid_entities

    return validated


def validate_importance_scores(
    data: Dict,
    batch_message_ids: List[int]
) -> Dict[str, int]:
    """Extract and validate importance scores from tool output.

    Returns dict mapping message_id string -> score int (1-9).
    Missing messages default to 3 (neutral baseline).
    """
    raw = data.get("message_scores", {})
    scores = {}
    for msg_id in batch_message_ids:
        key = str(msg_id)
        raw_score = raw.get(key)
        if isinstance(raw_score, (int, float)) and 1 <= raw_score <= 9:
            scores[key] = int(raw_score)
        else:
            scores[key] = 3  # Default to neutral if missing or invalid
    return scores


def validate_new_entities(
    data: Dict,
    canonical_entities: List[str],
    entity_data: List[Dict] = None
) -> Tuple[List[Dict], Dict[str, List[Dict]]]:
    """Extract and filter new entity proposals from tool output.

    Returns:
        (new_entities, redirected_assignments)
        - new_entities: genuinely new proposals to create
        - redirected_assignments: {msg_id_str: [{entity, confidence}]} for proposals
          whose name matched an existing alias — assignments are redirected to the
          owning entity rather than dropped (e.g. 'social_anxiety' → 'anxiety').

    entity_data (optional): used to detect alias-name collisions.
    """
    canonical_lower = {e.lower(): e for e in canonical_entities}

    # Build alias lookup: alias_lower (both spaced and underscored) → owning canonical name
    existing_aliases: Dict[str, str] = {}
    if entity_data:
        for e in entity_data:
            for alias in (e.get("aliases") or []):
                existing_aliases[alias.lower()] = e["name"]
                existing_aliases[alias.lower().replace(" ", "_")] = e["name"]

    new_entities_raw = data.get("new_entities", [])
    if not isinstance(new_entities_raw, list):
        return [], {}

    new_entities = []
    redirected: Dict[str, List[Dict]] = {}

    for e in new_entities_raw[:5]:
        if not isinstance(e, dict):
            continue
        name = e.get("name", "").strip()
        if not name or name.lower() in canonical_lower:
            continue

        # If the proposed name is already an alias, redirect assignments to the owner
        owner = (existing_aliases.get(name.lower())
                 or existing_aliases.get(name.lower().replace("_", " ")))
        if owner:
            print(f"  [entity guard] '{name}' is an alias of '{owner}' — redirecting assignments")
            for a in e.get("assignments", []):
                if isinstance(a, dict):
                    mid = str(a.get("message_id", ""))
                    conf = min(1.0, max(0.0, float(a.get("confidence", 0.8))))
                    if mid:
                        redirected.setdefault(mid, []).append({"entity": owner, "confidence": conf})
            continue

        aliases = [
            a.strip() for a in e.get("aliases", [])
            if isinstance(a, str) and a.strip() and a.strip().lower() != name.lower()
        ]

        assignments = []
        for a in e.get("assignments", []):
            if isinstance(a, dict):
                mid = str(a.get("message_id", ""))
                conf = min(1.0, max(0.0, float(a.get("confidence", 0.8))))
                if mid:
                    assignments.append({"message_id": mid, "confidence": conf})

        new_entities.append({"name": name, "aliases": aliases, "assignments": assignments})

    return new_entities, redirected


def validate_alias_updates(
    data: Dict,
    canonical_entities: List[str],
    entity_data: List[Dict] = None
) -> List[Dict]:
    """Extract alias update proposals for existing entities.

    entity_data (optional): list of {name, aliases} dicts used to detect
    conflicts — e.g. rejecting 'Eve' as alias for Sanni_Friend when 'Eve_Ex'
    already exists (either via its explicit aliases or its name prefix).
    """
    canonical_lower = {e.lower(): e for e in canonical_entities}

    # Build conflict map: alias_lower -> owning_canonical_name
    # Covers both explicit aliases and first-name prefixes of Name_Context entities
    conflict_map: Dict[str, str] = {}
    if entity_data:
        for e in entity_data:
            name = e["name"]
            # First-name prefix: 'Eve' from 'Eve_Ex', 'Sanni' from 'Sanni_Friend'
            if "_" in name:
                first = name.split("_")[0]
                conflict_map.setdefault(first.lower(), name)
            # Explicit aliases
            for alias in (e.get("aliases") or []):
                conflict_map.setdefault(alias.lower(), name)

    raw = data.get("alias_updates", [])

    if not isinstance(raw, list):
        return []

    updates = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entity_name = item.get("entity", "").strip()
        canonical = canonical_lower.get(entity_name.lower())
        if not canonical:
            continue
        aliases = []
        for a in item.get("add_aliases", []):
            if not isinstance(a, str):
                continue
            a = a.strip()
            if not a or a.lower() == entity_name.lower():
                continue
            # Reject if this alias already belongs to a different entity
            owner = conflict_map.get(a.lower())
            if owner and owner.lower() != canonical.lower():
                print(f"  [alias guard] Rejected '{a}' as alias for '{canonical}' — already claimed by '{owner}'")
                continue
            aliases.append(a)
        if aliases:
            updates.append({"entity": canonical, "add_aliases": aliases})

    return updates


def validate_descriptions(data: dict, batch_ids: list) -> dict:
    """Validate and extract message descriptions. Returns {msg_id_int: description_str}."""
    raw = data.get("message_descriptions", {})
    result = {}
    for msg in batch_ids:
        key = str(msg)
        desc = raw.get(key, "")
        if isinstance(desc, str) and desc.strip():
            result[msg] = desc.strip()[:80]  # Cap at 80 chars
    return result


# ============================================================================
# EntityAssigner — uses tool_choice for guaranteed valid output
# ============================================================================

class EntityAssigner:
    """
    Assigns entities to messages using Haiku with tool use.

    Tool use with tool_choice forces the API to return valid JSON matching
    the schema — no parsing failures possible.
    """

    # Haiku 4.5 pricing: $0.80/1M input, $4.00/1M output
    INPUT_COST_PER_MILLION = 0.80
    OUTPUT_COST_PER_MILLION = 4.00

    def __init__(self, anthropic_client, model: str = "claude-haiku-4-5"):
        self.client = anthropic_client
        self.model = model

        # Cost tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.batches_processed = 0

    @retry_with_backoff(max_retries=3, initial_delay=2.0)
    def assign_entities_batch(
        self,
        messages: List[Dict],
        canonical_entities: List[str]
    ) -> Tuple[Dict[str, List[Dict]], Dict[str, int]]:
        """
        Assign entities to a batch of messages (assignment only, no discovery).

        Returns:
            Tuple of (assignments, importance_scores)
            - assignments: {msg_id: [{entity, confidence}]}
            - importance_scores: {msg_id: score 1-9}
        """
        prompt = ASSIGNMENT_PROMPT.format(
            entity_list=format_entity_list(canonical_entities),
            messages=format_messages_for_prompt(messages)
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=64000,
            temperature=0.3,
            tools=[ASSIGNMENT_TOOL],
            tool_choice={"type": "tool", "name": "submit_entity_assignments"},
            messages=[{"role": "user", "content": prompt}],
            timeout=120.0
        )

        self._track_usage(response)
        data = self._extract_tool_input(response)
        batch_ids = [msg["id"] for msg in messages]
        return validate_assignments(data, canonical_entities), validate_importance_scores(data, batch_ids)

    @retry_with_backoff(max_retries=3, initial_delay=2.0)
    def assign_and_discover_batch(
        self,
        messages: List[Dict],
        canonical_entities: List[str],
        entity_data: List[Dict] = None,
        context_messages: List[Dict] = None
    ) -> Tuple[Dict[str, List[Dict]], List[Dict], Dict[str, int], List[Dict], Dict[int, str], List[str]]:
        """
        Assign entities, score importance, discover new entities, and describe messages in a single call.

        Args:
            messages: Batch of messages to analyze.
            canonical_entities: List of canonical entity names.
            entity_data: Optional list of {name, aliases} dicts.  When supplied,
                aliases are shown in the prompt (so Haiku knows 'Eve' belongs to
                'Eve_Ex' before it tries to alias it elsewhere) and the validator
                uses them to reject conflicting alias proposals.
            context_messages: Optional preceding messages for correction detection.
                These are read-only context — not scored or assigned.

        Returns:
            Tuple of (assignments, new_entities, importance_scores, alias_updates, descriptions, corrected_ids)
            - assignments: {msg_id: [{entity, confidence}]}
            - new_entities: [{name, assignments: [{message_id, confidence}]}]
            - importance_scores: {msg_id: score 1-9}
            - alias_updates: [{entity, add_aliases}]
            - descriptions: {msg_id_int: description_str}
            - corrected_ids: list of context message ID strings flagged as containing errors
        """
        alias_context = format_alias_context(entity_data) if entity_data else ""

        # Build context section for correction detection
        if context_messages:
            context_section = "**CONTEXT (preceding messages — do NOT score or assign, but flag in corrected_messages if they contain errors corrected by batch messages):**\n"
            context_section += format_messages_for_prompt(context_messages) + "\n\n"
        else:
            context_section = ""

        prompt = COMBINED_PROMPT.format(
            entity_list=format_entity_list(canonical_entities),
            alias_context=alias_context,
            context_section=context_section,
            messages=format_messages_for_prompt(messages)
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=64000,
            temperature=0.3,
            tools=[COMBINED_TOOL],
            tool_choice={"type": "tool", "name": "submit_entity_assignments"},
            messages=[{"role": "user", "content": prompt}],
            timeout=120.0
        )

        self._track_usage(response)
        data = self._extract_tool_input(response)
        batch_ids = [msg["id"] for msg in messages]

        assignments = validate_assignments(data, canonical_entities)
        new_entities, redirected = validate_new_entities(data, canonical_entities, entity_data)

        # Merge redirected assignments (alias-collision proposals) into main assignments
        for msg_id, entity_list in redirected.items():
            existing_names = {a["entity"] for a in assignments.get(msg_id, [])}
            for e in entity_list:
                if e["entity"] not in existing_names:
                    assignments.setdefault(msg_id, []).append(e)
                    existing_names.add(e["entity"])

        # Extract corrected message IDs (accept IDs from context or batch)
        valid_ids = {str(m["id"]) for m in (context_messages or [])} | {str(m["id"]) for m in messages}
        raw_corrected = data.get("corrected_messages", [])
        corrected_ids = [mid for mid in raw_corrected if isinstance(mid, str) and mid in valid_ids]

        return (
            assignments,
            new_entities,
            validate_importance_scores(data, batch_ids),
            validate_alias_updates(data, canonical_entities, entity_data),
            validate_descriptions(data, batch_ids),
            corrected_ids,
        )

    def _track_usage(self, response):
        """Track token usage and warn if output was truncated."""
        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens
        self.batches_processed += 1
        if response.stop_reason == "max_tokens":
            print(f"  WARNING: output truncated at {response.usage.output_tokens} tokens")

    @staticmethod
    def _extract_tool_input(response) -> dict:
        """Find the ToolUseBlock in the response and return its input dict.
        Haiku may emit a TextBlock before the tool call even with tool_choice forced."""
        for block in response.content:
            if block.type == "tool_use":
                return block.input
        raise ValueError(f"No tool_use block in response. Got: {[b.type for b in response.content]}")

    def get_cost(self) -> float:
        """Get estimated cost based on usage."""
        input_cost = (self.total_input_tokens / 1_000_000) * self.INPUT_COST_PER_MILLION
        output_cost = (self.total_output_tokens / 1_000_000) * self.OUTPUT_COST_PER_MILLION
        return input_cost + output_cost

    def get_batch_cost(self) -> float:
        """Get average cost per batch."""
        if self.batches_processed == 0:
            return 0.0
        return self.get_cost() / self.batches_processed
