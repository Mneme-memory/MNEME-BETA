"""
Flask Web Server for Mneme Memory System

Provides REST API for chat interface:
- POST /api/chat - Send message, get AI response
- GET /api/history - Get conversation history
- GET /api/stats - Get system statistics
- GET / - Serve frontend HTML

Usage:
    python src/backend/server.py
"""

import sys
import os
import json
import io
from contextlib import redirect_stdout

# Fix Windows cp1252 encoding issues with Unicode output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.backend.database import Database
from src.backend.config import load_config, save_config, save_profile_config, update_active_profile
from src.backend.embeddings import EmbeddingGenerator
from src.backend.conversation import ConversationManager

app = Flask(__name__, static_folder='../frontend')

# Allow large file uploads (Phase 7: 25MB for Anthropic API limit)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB

# Phase 4 Security: Restrict CORS to localhost only (prevents unauthorized access)
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "http://localhost:*",
            "http://127.0.0.1:*",
            "http://[::1]:*"  # IPv6 localhost
        ]
    }
})

# Global instances
db = None
manager = None
config = None
file_storage = None
file_processor = None
setup_mode = False  # True when config is missing/incomplete — serves setup UI only


def needs_setup():
    """
    Check if Mneme needs first-time setup.

    Returns True if config.json doesn't exist or has placeholder API keys.
    """
    config_path = Path(__file__).parent.parent.parent / "config.json"
    if not config_path.exists():
        return True
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        anthropic_key = cfg.get("api_keys", {}).get("anthropic", "")
        if not anthropic_key or anthropic_key == "YOUR_ANTHROPIC_API_KEY_HERE":
            return True
        return False
    except Exception:
        return True


def _build_system(cfg):
    """
    Build all system components from a config dict.

    Returns (db, manager, file_storage, file_processor) tuple.
    Raises on failure instead of sys.exit.
    """
    db_path = cfg["storage"]["database_path"]
    openai_key = cfg["api_keys"]["openai"]

    new_db = Database(db_path)
    message_count = new_db.get_message_count()

    embedder = EmbeddingGenerator(openai_key, model="text-embedding-3-small")

    # Initialize graph database (if entity summaries enabled)
    graph_db = None
    entity_config = cfg.get("features", {}).get("entity_summaries", {})
    if entity_config.get("enabled", False):
        from src.backend.graph_database import GraphDatabase
        graph_db = GraphDatabase(cfg)
        graph_db.initialize_schema()
        entity_count = len(graph_db.get_entity_stats(min_mentions=1))
        print(f"✓ Entity system enabled ({entity_count} entities)")

    # Check concept status
    concept_config = cfg.get("features", {}).get("concepts", {})
    if concept_config.get("enabled", False):
        concept_count = len(new_db.get_all_concepts())
        print(f"✓ Narrative concepts enabled ({concept_count} concepts)")

    # Initialize file attachment system (if enabled)
    new_file_storage = None
    new_file_processor = None
    files_config = cfg.get("features", {}).get("attachments", {})
    if files_config.get("enabled", False):
        from src.backend.file_storage import FileStorage
        from src.backend.file_processor import FileProcessor

        db_dir = Path(db_path).parent
        attachments_dir = db_dir / "attachments"

        new_file_storage = FileStorage(str(attachments_dir))
        new_file_processor = FileProcessor(str(attachments_dir))

        attachment_count = new_db.get_attachment_count()
        print(f"✓ File attachments enabled ({attachment_count} files)")

    # Artifacts: always available, lazy directory creation
    from src.backend.artifact_storage import ArtifactStorage
    db_dir = Path(db_path).parent
    artifact_storage = ArtifactStorage(str(db_dir / "artifacts"))
    print(f"✓ Artifact storage ready ({db_dir / 'artifacts'})")

    new_manager = ConversationManager(
        new_db, embedder, cfg, graph_db=graph_db,
        file_processor=new_file_processor, artifact_storage=artifact_storage
    )

    print(f"✓ Database connected ({message_count} messages stored)")
    print(f"✓ ConversationManager initialized")

    return new_db, new_manager, new_file_storage, new_file_processor


def init_system():
    """Initialize Mneme system components on startup."""
    global db, manager, config, file_storage, file_processor

    print("Initializing Mneme Memory System...")

    try:
        config = load_config()
        active_profile = config["storage"].get("active_profile", "")

        print(f"✓ Configuration loaded")
        if active_profile:
            print(f"✓ Active profile: '{active_profile}'")
        print(f"✓ Database path: {config['storage']['database_path']}")

    except Exception as e:
        print(f"✗ Configuration error: {e}")
        sys.exit(1)

    try:
        db, manager, file_storage, file_processor = _build_system(config)
        print()
    except Exception as e:
        print(f"✗ Initialization error: {e}")
        sys.exit(1)


def reinit_system(profile_name):
    """
    Switch to a different profile by tearing down and rebuilding all components.

    Args:
        profile_name: Profile folder name to switch to

    Returns:
        dict with 'success' key, or 'error' on failure
    """
    global db, manager, config, file_storage, file_processor

    print(f"\nSwitching to profile '{profile_name}'...")

    # Close existing graph DB connection if present
    if manager and hasattr(manager, 'background_queue') and manager.background_queue.graph_db:
        try:
            manager.background_queue.graph_db.conn.close()
        except Exception:
            pass

    try:
        # Update config with new profile and re-resolve paths
        config = update_active_profile(config, profile_name)

        # Save the profile switch to root config.json
        save_config(config)

        # Rebuild all components
        db, manager, file_storage, file_processor = _build_system(config)

        print(f"✓ Switched to profile '{profile_name}'\n")
        return {"success": True}

    except Exception as e:
        print(f"✗ Profile switch failed: {e}")
        return {"error": str(e)}


def filter_output(captured_output: str) -> list:
    """
    Filter captured output to remove clutter.

    SIMPLE RULE (Phase 4):
    - ANY line starting with emoji → SHOW IT (user-facing notification)
    - Exception: 🔧 DEBUG → always hidden (development only)
    - Everything else → hidden (technical verbose output)

    This makes the system future-proof: add new emoji notifications
    without updating the filter!

    Examples that pass:
    - 🤖 Instance used @recall
    - ↳ Found 3 memories
    - 💭 Intermediate response
    - 💾 Cache: Enabled
    - ⚠ Warning message
    - 🔄 Running rebalance
    - ✓ Success

    Examples that are filtered:
    - Searching for...
    - Comparing against 1234 messages...
    - → Batch tagging...
    - 🔧 DEBUG: token count = 1234
    """
    lines = captured_output.split('\n')
    filtered = []
    in_intermediate = False

    for line in lines:
        line_stripped = line.strip()

        # Preserve blank lines in intermediate responses
        if not line_stripped:
            if in_intermediate:
                filtered.append('')  # Keep blank line for formatting
            continue

        # SIMPLE EMOJI FILTER:
        # If line starts with emoji (non-ASCII character), it's a notification
        first_char = line_stripped[0] if line_stripped else ''
        starts_with_emoji = ord(first_char) > 127 if first_char else False

        if starts_with_emoji:
            # Exception: Debug emoji is always hidden
            if line_stripped.startswith('🔧 DEBUG:'):
                continue  # Skip debug output

            # All other emojis → show!
            # Check if it's an intermediate response marker
            if line_stripped.startswith('💭'):
                in_intermediate = True
            else:
                in_intermediate = False

            filtered.append(line_stripped)
            continue

        # If we're in an intermediate block, capture the content
        if in_intermediate:
            # Keep capturing until we hit a line that starts with emoji or looks technical
            if not any(x in line_stripped for x in ['Searching', 'Comparing', '→ Batch', 'tokens']):
                filtered.append(line_stripped)
            else:
                in_intermediate = False
            continue

        # Keep errors and warnings even without emoji
        if 'error' in line_stripped.lower() or 'failed' in line_stripped.lower():
            filtered.append(line_stripped)
            continue

    return filtered


@app.before_request
def check_setup_mode():
    """Block API requests when in setup mode (except setup endpoints and static files)."""
    if not setup_mode:
        return None
    # Allow setup endpoints
    if request.path in ('/api/setup', '/api/setup/status'):
        return None
    # Allow static file serving (setup page needs CSS, fonts, assets)
    if request.path.startswith('/assets/') or request.path in (
        '/', '/setup.css', '/favicon.svg', '/style.css'
    ):
        return None
    # Block all other API calls
    if request.path.startswith('/api/'):
        return jsonify({"error": "Mneme is not configured yet. Please complete setup."}), 503
    return None


@app.route('/')
def serve_frontend():
    """Serve the main HTML page, or setup page if not configured."""
    if setup_mode:
        return send_from_directory(app.static_folder, 'setup.html')
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/style.css')
def serve_css():
    """Serve the CSS file."""
    return send_from_directory(app.static_folder, 'style.css')


@app.route('/app.js')
def serve_js():
    """Serve the JavaScript file."""
    return send_from_directory(app.static_folder, 'app.js')


@app.route('/setup.css')
def serve_setup_css():
    """Serve setup page CSS."""
    return send_from_directory(app.static_folder, 'setup.css')


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    """Serve icon and image assets."""
    return send_from_directory(os.path.join(app.static_folder, 'assets'), filename)


@app.route('/favicon.svg')
def serve_favicon():
    """Serve the favicon."""
    return send_from_directory(app.static_folder, 'favicon.svg')


@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Handle chat message.

    Request body:
    {
        "message": "User's message text",
        "attachment_uuids": ["uuid1", "uuid2"]  // Optional: files to include
    }

    Response:
    {
        "response": "AI response text",
        "commands_used": [...],
        "context_info": {...},
        "notifications": ["🤖 Instance used @recall", "↳ Found 3 memories"]
    }
    """
    try:
        data = request.json

        if data is None:
            return jsonify({"error": "Invalid JSON in request body"}), 400

        message = data.get('message', '').strip()
        attachment_uuids = data.get('attachment_uuids', [])

        if not message and not attachment_uuids:
            return jsonify({"error": "Message or attachments required"}), 400

        # Phase 4 Security: Input validation
        if len(message) > 500000:  # 500K character limit (allows large JSON pastes)
            return jsonify({"error": "Message too long (max 500,000 characters)"}), 400

        # Capture stdout to filter verbose output
        output_buffer = io.StringIO()

        with redirect_stdout(output_buffer):
            result = manager.process_message(message, attachment_uuids=attachment_uuids)

        # Filter captured output
        captured = output_buffer.getvalue()
        notifications = filter_output(captured)

        # Build response
        response = {
            "response": result["response"],
            "is_command": result.get("is_command", False),
            "context_info": result.get("context_info", {}),
            "processing_info": result.get("processing_info", {}),
            "notifications": notifications
        }

        # Include thinking text if present (Phase 10)
        if result.get("thinking"):
            response["thinking"] = result["thinking"]

        return jsonify(response)

    except Exception as e:
        # Log full error to stderr (not captured by redirect_stdout)
        import sys
        import traceback
        print(f"\n{'='*70}", file=sys.stderr)
        print(f"ERROR IN /api/chat:", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print(f"{'='*70}\n", file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """
    Handle chat message with streaming response (Phase 4.3).

    Request body:
    {
        "message": "User's message text",
        "attachment_uuids": ["uuid1", "uuid2"]  // Optional: files to include
    }

    Response: Server-Sent Events (SSE) stream
    - data: {"type": "notification", "data": "🔄 Processing..."}
    - data: {"type": "chunk", "data": "partial text"}
    - data: {"type": "done", "data": {...metadata...}}

    STREAMING BENEFITS:
    - Real-time response appears as AI generates it
    - Progressive notifications during processing
    - Better mobile UX (no blank screen during long responses)
    - Lower perceived latency
    """
    try:
        data = request.json

        if data is None:
            return jsonify({"error": "Invalid JSON in request body"}), 400

        message = data.get('message', '').strip()
        attachment_uuids = data.get('attachment_uuids', [])

        if not message and not attachment_uuids:
            return jsonify({"error": "Message or attachments required"}), 400

        # Phase 4 Security: Input validation
        if len(message) > 500000:  # 500K character limit (allows large JSON pastes)
            return jsonify({"error": "Message too long (max 500,000 characters)"}), 400

        def generate():
            """Generator for SSE stream."""
            try:
                # Stream events from ConversationManager
                for event in manager.process_message_stream(message, attachment_uuids=attachment_uuids):
                    # Format as SSE (Server-Sent Events)
                    yield f"data: {json.dumps(event)}\n\n"

            except Exception as e:
                # Send error event
                error_event = {"type": "error", "data": str(e)}
                yield f"data: {json.dumps(error_event)}\n\n"

        # Return SSE response
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'  # Disable nginx buffering
            }
        )

    except Exception as e:
        import sys
        import traceback
        print(f"\n{'='*70}", file=sys.stderr)
        print(f"ERROR IN /api/chat/stream:", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print(f"{'='*70}\n", file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/history', methods=['GET'])
def get_history():
    """
    Get conversation history.

    Query params:
    - limit: Number of messages to return (default 50)

    Response:
    {
        "messages": [
            {
                "id": 123,
                "sender": "user" | "assistant" | "system",
                "content": "message text",
                "timestamp": "2025-11-03T12:34:56Z",
                "importance_score": 7.5
            },
            ...
        ]
    }
    """
    try:
        limit = request.args.get('limit', 50, type=int)
        messages = db.get_recent_messages(limit=limit)

        return jsonify({"messages": messages})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/messages/cleanup-orphans', methods=['POST'])
def cleanup_orphan_messages():
    """
    Clean up orphaned user messages that have no AI response.

    Called by frontend on:
    - Live interruption (catch block in sendMessage)
    - Page startup (before rendering history)

    Response: {"deleted": N, "restored_text": "..." | null}
    """
    try:
        result = db.cleanup_orphan_messages()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/messages/save-partial', methods=['POST'])
def save_partial_response():
    """
    Save a partial (interrupted) AI response to the database.

    Called by frontend when the user aborts an in-progress stream.
    On first interruption: creates a new assistant message with [message interrupted] suffix.
    On re-interruption (continue was itself aborted): updates the existing partial message.

    Request body:
    {
        "partial_content": "text streamed so far",
        "original_message_id": 123  // optional — present if re-interrupting a continuation
    }

    Response: {"message_id": <int>}
    """
    try:
        data = request.json
        if data is None:
            return jsonify({"error": "Invalid JSON"}), 400

        partial = data.get('partial_content', '').strip()
        original_id = data.get('original_message_id')
        thinking_text = data.get('thinking_text', '').strip()

        if not partial and not thinking_text:
            return jsonify({"error": "No content to save"}), 400

        if original_id:
            # Re-interruption: update existing partial message
            existing = db.get_message(int(original_id))
            if existing:
                clean = existing['content']
                if clean.endswith('\n\n[message interrupted]'):
                    clean = clean[:-len('\n\n[message interrupted]')].rstrip()
                merged = clean + '\n\n' + partial + '\n\n[message interrupted]'
                db.update_message_content(int(original_id), merged)
                return jsonify({"message_id": int(original_id)})

        # First interruption: create new assistant message
        msg_id = db.add_message(
            sender="assistant",
            content=partial + '\n\n[message interrupted]',
            importance_score=3.0
        )
        # Preserve thinking so the block re-appears on history reload
        if thinking_text:
            db.update_message_metadata(int(msg_id), {"thinking": thinking_text}, merge=True)
        return jsonify({"message_id": msg_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/chat/continue', methods=['POST'])
def chat_continue():
    """
    Continue a previously interrupted AI response (streaming).

    The AI is given the partial text already written and asked to continue
    seamlessly. The continuation is merged into the original DB message.

    Request body:
    {
        "interrupted_message_id": 123
    }

    Response: Server-Sent Events stream (same format as /api/chat/stream)
    - data: {"type": "notification", "data": "..."}
    - data: {"type": "chunk", "data": "partial text"}
    - data: {"type": "done", "data": {"merged_message_id": 123}}
    """
    try:
        data = request.json
        if data is None:
            return jsonify({"error": "Invalid JSON"}), 400

        interrupted_message_id = data.get('interrupted_message_id')
        if not interrupted_message_id:
            return jsonify({"error": "interrupted_message_id required"}), 400

        def generate():
            try:
                for event in manager.continue_message_stream(int(interrupted_message_id)):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as e:
                error_event = {"type": "error", "data": str(e)}
                yield f"data: {json.dumps(error_event)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    """
    Get client-facing configuration settings.

    Returns settings that affect frontend behavior (e.g., streaming mode, TTS).
    """
    try:
        # Get model config
        model_config = config.get('model', {})

        # Get TTS config
        tts_config = config.get('features', {}).get('tts', {})
        tts_enabled = tts_config.get('enabled', False)

        # Check if TTS is actually usable (has API key)
        if tts_enabled:
            elevenlabs_key = config.get('api_keys', {}).get('elevenlabs', '')
            if not elevenlabs_key or elevenlabs_key == 'YOUR_ELEVENLABS_API_KEY_HERE':
                tts_enabled = False

        # Get thinking config
        thinking_config = config.get('thinking', {})

        return jsonify({
            'streaming_enabled': model_config.get('streaming', False),
            'tts_enabled': tts_enabled,
            'thinking_enabled': thinking_config.get('enabled', False),
            'show_thinking': thinking_config.get('show_in_ui', True)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """
    Get system statistics and configuration.

    Response includes model config, context budgets, and tier counts.
    """
    try:
        # Get configuration
        config = manager.config

        # Get tier counts from database
        tier_counts = manager.db.execute_query("""
            SELECT tier, COUNT(*) as count
            FROM messages
            WHERE (metadata IS NULL OR json_extract(metadata, '$.retrieved') IS NULL)
            AND (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
            GROUP BY tier
        """)

        # Build tier count dict
        tiers = {'active': 0, 'standard': 0, 'deep_archive': 0}
        for row in tier_counts:
            tiers[row['tier']] = row['count']

        # Get active model — use live manager.model (may have been updated via set-model)
        model_id = manager.model
        model_cfg = config.get('model', {})

        # Get profile name and instance display name from config
        profile = config.get('storage', {}).get('active_profile', 'main')
        instance_name = config.get('identity', {}).get('instance_name', '') or profile

        # Get feature info
        entity_config = config.get('features', {}).get('entity_summaries', {})
        concept_config = config.get('features', {}).get('concepts', {})

        # Build response
        stats = {
            'profile': profile,
            'instance_name': instance_name,
            'model': model_id,
            'temperature': model_cfg.get('temperature', 1.0),
            'recent_budget': config.get('context', {}).get('recent_messages_tokens', 50000),
            'memory_limit': config.get('retrieval', {}).get('max_results', 10),
            'entity_enabled': entity_config.get('enabled', False),
            'entity_limit': entity_config.get('max_entities_per_retrieval', 3),
            'concept_enabled': concept_config.get('enabled', False),
            'concept_limit': concept_config.get('max_concepts_retrieved', 2),
            'active_tier': tiers['active'],
            'standard_tier': tiers['standard'],
            'deep_tier': tiers['deep_archive']
        }

        return jsonify(stats)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/set-model', methods=['POST'])
def set_model():
    """
    Switch the active AI model at runtime and persist to profile config.

    Body: {"model_id": "claude-sonnet-4-6"}
    """
    try:
        data = request.get_json()
        model_id = data.get('model_id', '').strip()

        if not model_id:
            return jsonify({"error": "model_id is required"}), 400

        # Basic validation — only allow claude- model IDs
        if not model_id.startswith('claude-'):
            return jsonify({"error": "Invalid model ID"}), 400

        manager.model = model_id
        manager.ai_client.update_model(model_id)

        # Persist to config so settings page stays in sync
        config.setdefault('model', {})['default'] = model_id
        from src.backend.config import PROFILE_SCOPED_KEYS
        profile_scoped = {k: config[k] for k in PROFILE_SCOPED_KEYS if k in config}
        if profile_scoped:
            save_profile_config(config, profile_scoped)
        save_config(config)

        # Force cache cold start — new model has no cache, and the
        # tier rebalance + history reload cascade needs to fire.
        manager.cache_manager.last_message_time = None
        manager.cache_manager.current_session_cached = False

        return jsonify({"model": model_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# PROFILE MANAGEMENT
# =============================================================================

@app.route('/api/profiles', methods=['GET'])
def list_profiles():
    """
    List all available profiles.

    Scans data/ for subdirectories containing memory.db.
    Returns profile metadata (name, display name, model, message count).
    """
    try:
        import sqlite3 as _sqlite3
        project_root = Path(__file__).parent.parent.parent

        # Read base model from root config.json (not overlaid in-memory config)
        base_model_id = ""
        root_config_path = project_root / "config.json"
        if root_config_path.exists():
            try:
                with open(root_config_path, 'r', encoding='utf-8') as f:
                    root_cfg = json.load(f)
                base_model_id = root_cfg.get("model", {}).get("default", "")
            except Exception:
                pass

        # Determine data directory from config template or resolved path
        storage = config.get("storage", {})
        db_template = storage.get("database_path_template", storage.get("database_path", ""))

        # Extract the data root (everything before {profile} or the profile folder)
        if "{profile}" in db_template:
            # Template like ./data/{profile}/memory.db → data dir is ./data/
            data_dir = project_root / db_template.split("{profile}")[0]
        else:
            # Resolved path — go up two levels from the DB file
            data_dir = Path(storage.get("database_path", "")).parent.parent

        if not data_dir.exists():
            return jsonify({"profiles": [], "active": "", "user_name": ""})

        profiles = []
        for entry in sorted(data_dir.iterdir()):
            if not entry.is_dir():
                continue
            db_file = entry / "memory.db"
            if not db_file.exists():
                continue

            profile_name = entry.name
            message_count = 0
            model_id = ""
            display_name = profile_name

            # Read message count from DB
            try:
                conn = _sqlite3.connect(str(db_file), timeout=5)
                conn.row_factory = _sqlite3.Row
                cursor = conn.execute("SELECT COUNT(*) as n FROM messages")
                message_count = cursor.fetchone()[0]
                conn.close()
            except Exception:
                pass

            # Read per-profile config if it exists, fall back to global
            profile_config_path = entry / "config.json"
            if profile_config_path.exists():
                try:
                    with open(profile_config_path, 'r', encoding='utf-8') as f:
                        pc = json.load(f)
                    display_name = pc.get("identity", {}).get("instance_name", profile_name) or profile_name
                    model_id = pc.get("model", {}).get("default", "")
                except Exception:
                    pass

            # Fall back to root config model if profile doesn't specify one
            if not model_id:
                model_id = base_model_id

            profiles.append({
                "name": profile_name,
                "display_name": display_name,
                "model": model_id,
                "message_count": message_count
            })

        active = storage.get("active_profile", "")
        user_name = config.get("identity", {}).get("user_name", "")

        return jsonify({
            "profiles": profiles,
            "active": active,
            "user_name": user_name
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/profiles/create', methods=['POST'])
def create_profile():
    """
    Create a new profile.

    Body: {"name": "Casual-Claude", "model": "claude-sonnet-4-6"}

    Creates the profile directory, writes per-profile config,
    copies system_instructions.example.txt, and switches to it.
    """
    try:
        data = request.get_json()
        display_name = (data.get('name') or '').strip()
        model_id = (data.get('model') or '').strip()

        if not display_name:
            return jsonify({"error": "name is required"}), 400

        # Sanitize to folder slug: lowercase, replace spaces/special chars with hyphens
        import re
        slug = re.sub(r'[^a-z0-9]+', '-', display_name.lower()).strip('-')
        if not slug or slug in ('.', '..') or '/' in slug or '\\' in slug:
            return jsonify({"error": "Invalid profile name"}), 400

        # Determine data directory
        project_root = Path(__file__).parent.parent.parent
        storage = config.get("storage", {})
        db_template = storage.get("database_path_template", storage.get("database_path", ""))
        if "{profile}" in db_template:
            data_dir = project_root / db_template.split("{profile}")[0]
        else:
            data_dir = Path(storage.get("database_path", "")).parent.parent

        profile_dir = data_dir / slug
        if profile_dir.exists() and (profile_dir / "memory.db").exists():
            return jsonify({"error": f"Profile '{slug}' already exists"}), 409

        # Create directory
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Write per-profile config
        profile_config = {
            "identity": {"instance_name": display_name}
        }
        if model_id:
            profile_config["model"] = {"default": model_id}

        with open(profile_dir / "config.json", 'w', encoding='utf-8') as f:
            json.dump(profile_config, f, indent=2, ensure_ascii=False)

        # Copy system_instructions.example.txt if it exists
        example_instructions = project_root / "system_instructions.example.txt"
        if example_instructions.exists():
            import shutil
            shutil.copy2(str(example_instructions), str(profile_dir / "system_instructions.txt"))

        # Switch to the new profile
        result = reinit_system(slug)
        if "error" in result:
            return jsonify(result), 500

        return jsonify({
            "success": True,
            "profile": slug,
            "display_name": display_name
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/profiles/switch', methods=['POST'])
def switch_profile():
    """
    Switch to an existing profile.

    Body: {"profile": "code-planner"}
    """
    try:
        data = request.get_json()
        profile_name = (data.get('profile') or '').strip()

        if not profile_name:
            return jsonify({"error": "profile is required"}), 400

        # Validate profile exists
        project_root = Path(__file__).parent.parent.parent
        storage = config.get("storage", {})
        db_template = storage.get("database_path_template", storage.get("database_path", ""))
        if "{profile}" in db_template:
            data_dir = project_root / db_template.split("{profile}")[0]
        else:
            data_dir = Path(storage.get("database_path", "")).parent.parent

        profile_dir = data_dir / profile_name
        if not profile_dir.exists() or not (profile_dir / "memory.db").exists():
            return jsonify({"error": f"Profile '{profile_name}' not found"}), 404

        # Switch
        result = reinit_system(profile_name)
        if "error" in result:
            return jsonify(result), 500

        return jsonify({"success": True, "profile": profile_name})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# FIRST-TIME SETUP
# =============================================================================

@app.route('/api/setup/status', methods=['GET'])
def setup_status():
    """Check whether first-time setup is needed."""
    return jsonify({"needs_setup": setup_mode})


@app.route('/api/setup', methods=['POST'])
def complete_setup():
    """
    Complete first-time setup.

    Receives questionnaire data, writes config.json, copies system instructions,
    initializes the database, and transitions to normal mode.
    """
    global setup_mode

    if not setup_mode:
        return jsonify({"error": "Setup already completed"}), 400

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Validate required fields
        user_name = (data.get('user_name') or '').strip()
        anthropic_key = (data.get('anthropic_key') or '').strip()
        openai_key = (data.get('openai_key') or '').strip()
        elevenlabs_key = (data.get('elevenlabs_key') or '').strip()
        instance_name = (data.get('instance_name') or '').strip()
        model_id = (data.get('model') or 'claude-sonnet-4-6').strip()

        if not anthropic_key:
            return jsonify({"error": "Anthropic API key is required"}), 400
        if not openai_key:
            return jsonify({"error": "OpenAI API key is required"}), 400

        # Build config from example template
        project_root = Path(__file__).parent.parent.parent
        example_path = project_root / "config.example.json"
        config_path = project_root / "config.json"

        if example_path.exists():
            with open(example_path, 'r', encoding='utf-8') as f:
                new_config = json.load(f)
        else:
            # Minimal fallback if example doesn't exist
            new_config = {
                "api_keys": {}, "storage": {
                    "active_profile": "main",
                    "database_path": "./data/{profile}/memory.db",
                    "backup_path": "./data/{profile}/backups/"
                }
            }

        # Fill in user values
        new_config["api_keys"]["anthropic"] = anthropic_key
        new_config["api_keys"]["openai"] = openai_key
        new_config["api_keys"]["elevenlabs"] = elevenlabs_key
        new_config["identity"]["user_name"] = user_name
        new_config["identity"]["instance_name"] = instance_name
        new_config["model"]["default"] = model_id

        # Write config.json
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        print(f"✓ Configuration written to {config_path}")

        # Copy system_instructions.example.txt to root (for legacy/fallback)
        import shutil
        example_instructions = project_root / "system_instructions.example.txt"
        root_instructions = project_root / "system_instructions.txt"
        if example_instructions.exists() and not root_instructions.exists():
            shutil.copy2(str(example_instructions), str(root_instructions))
            print(f"✓ System instructions created")

        # Create per-profile config and instructions for the default "main" profile
        # Without this, profile listing shows the folder slug "main" instead of the instance name
        active_profile = new_config.get("storage", {}).get("active_profile", "main")
        db_template = new_config.get("storage", {}).get("database_path", "./data/{profile}/memory.db")
        profile_dir = project_root / db_template.replace("{profile}", active_profile).replace("/memory.db", "")
        profile_dir.mkdir(parents=True, exist_ok=True)

        profile_config = {"identity": {"instance_name": instance_name}}
        if model_id:
            profile_config["model"] = {"default": model_id}
        with open(profile_dir / "config.json", 'w', encoding='utf-8') as f:
            json.dump(profile_config, f, indent=2, ensure_ascii=False)

        # Copy system instructions to profile directory
        if example_instructions.exists():
            shutil.copy2(str(example_instructions), str(profile_dir / "system_instructions.txt"))

        print(f"✓ Profile '{active_profile}' initialized with instance name '{instance_name}'")

        # Initialize the full system
        setup_mode = False
        init_system()

        # Start entity backfill in background
        import threading
        threading.Thread(target=_run_startup_entity_backfill, daemon=True).start()

        print("✓ Setup complete — Mneme is ready!")
        return jsonify({"success": True})

    except Exception as e:
        print(f"✗ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =============================================================================
# SETTINGS
# =============================================================================

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all tunable runtime settings for the Settings page."""
    try:
        model_cfg = config.get('model', {})
        thinking_cfg = config.get('thinking', {})
        context_cfg = config.get('context', {})
        retrieval_cfg = config.get('retrieval', {})
        features = config.get('features', {})
        identity_cfg = config.get('identity', {})

        # Mask API keys — show last 4 chars only
        api_keys = config.get('api_keys', {})
        def mask_key(key):
            if not key:
                return ''
            return '••••••••' + key[-4:] if len(key) > 4 else '••••'

        return jsonify({
            # Identity
            'user_name': identity_cfg.get('user_name', ''),
            'instance_name': identity_cfg.get('instance_name', ''),
            # API keys (masked)
            'anthropic_key_masked': mask_key(api_keys.get('anthropic', '')),
            'openai_key_masked': mask_key(api_keys.get('openai', '')),
            'elevenlabs_key_masked': mask_key(api_keys.get('elevenlabs', '')),
            # Model — use runtime model (manager) if available, fallback to config
            'model_default': (manager.model if manager else None) or model_cfg.get('default', 'claude-sonnet-4-6'),
            'use_testing_model': model_cfg.get('use_testing', False),
            'temperature': model_cfg.get('temperature', 1.0),
            # Thinking
            'thinking_enabled': thinking_cfg.get('enabled', True),
            'thinking_budget': thinking_cfg.get('budget_tokens', 10000),
            # Context
            'recent_messages_tokens': context_cfg.get('recent_messages_tokens', 50000),
            # Retrieval
            'retrieval_threshold': retrieval_cfg.get('similarity_threshold', 0.25),
            'max_retrieval_results': retrieval_cfg.get('max_results', 10),
            'semantic_weight': retrieval_cfg.get('semantic_weight', 0.4),
            'importance_weight': retrieval_cfg.get('importance_weight', 0.4),
            'recency_weight': retrieval_cfg.get('recency_weight', 0.2),
            'entity_match_weight': retrieval_cfg.get('entity_match_weight', 0.15),
            'deep_archive_age_days': retrieval_cfg.get('deep_archive_age_days', 180),
            # Count limits
            'max_entities_per_retrieval': features.get('entity_summaries', {}).get('max_entities_per_retrieval', 3),
            'max_concepts_retrieved': features.get('concepts', {}).get('max_concepts_retrieved', 2),
            'max_files_displayed': features.get('attachments', {}).get('max_files_displayed', 5),
            # Features
            'concepts_enabled': features.get('concepts', {}).get('enabled', True),
            'entity_summaries_enabled': features.get('entity_summaries', {}).get('enabled', True),
            'attachments_enabled': features.get('attachments', {}).get('enabled', True),
            'tts_enabled': features.get('tts', {}).get('enabled', True),
            'timeline_enabled': features.get('timeline', {}).get('enabled', True),
            'notes_enabled': features.get('notes', {}).get('enabled', True),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Apply and persist tunable runtime settings."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        updated = {}

        # --- API Keys ---
        # Only update if the user provides a new key (not the masked placeholder)
        api_key_fields = {
            'anthropic_key': 'anthropic',
            'openai_key': 'openai',
            'elevenlabs_key': 'elevenlabs',
        }
        for data_key, config_key in api_key_fields.items():
            if data_key in data:
                val = str(data[data_key]).strip()
                # Skip if it's the masked value (starts with dots) or empty
                if val and not val.startswith('••'):
                    config.setdefault('api_keys', {})[config_key] = val
                    updated[data_key] = True

        # --- Identity ---
        if 'user_name' in data:
            val = str(data['user_name']).strip()
            config.setdefault('identity', {})['user_name'] = val
            updated['user_name'] = val

        if 'instance_name' in data:
            val = str(data['instance_name']).strip()
            config.setdefault('identity', {})['instance_name'] = val
            updated['instance_name'] = val

        # --- Model ---
        if 'model_default' in data:
            val = str(data['model_default']).strip()
            if not val.startswith('claude-'):
                return jsonify({"error": "Invalid model ID"}), 400
            config.setdefault('model', {})['default'] = val
            updated['model_default'] = val

        if 'use_testing_model' in data:
            val = bool(data['use_testing_model'])
            config.setdefault('model', {})['use_testing'] = val
            updated['use_testing_model'] = val

        if 'temperature' in data:
            val = float(data['temperature'])
            if not 0.0 <= val <= 1.0:
                return jsonify({"error": "temperature must be between 0 and 1"}), 400
            config.setdefault('model', {})['temperature'] = val
            updated['temperature'] = val

        # --- Thinking ---
        if 'thinking_enabled' in data:
            val = bool(data['thinking_enabled'])
            config.setdefault('thinking', {})['enabled'] = val
            updated['thinking_enabled'] = val

        if 'thinking_budget' in data:
            val = int(data['thinking_budget'])
            if not 5000 <= val <= 50000:
                return jsonify({"error": "thinking_budget must be between 5000 and 50000"}), 400
            config.setdefault('thinking', {})['budget_tokens'] = val
            updated['thinking_budget'] = val

        # --- Context ---
        if 'recent_messages_tokens' in data:
            val = int(data['recent_messages_tokens'])
            if not 5000 <= val <= 200000:
                return jsonify({"error": "recent_messages_tokens must be between 5000 and 200000"}), 400
            config.setdefault('context', {})['recent_messages_tokens'] = val
            updated['recent_messages_tokens'] = val

        # --- Retrieval ---
        if 'retrieval_threshold' in data:
            val = float(data['retrieval_threshold'])
            if not 0.1 <= val <= 0.6:
                return jsonify({"error": "retrieval_threshold must be between 0.1 and 0.6"}), 400
            config.setdefault('retrieval', {})['similarity_threshold'] = val
            updated['retrieval_threshold'] = val

        if 'max_retrieval_results' in data:
            val = int(data['max_retrieval_results'])
            if not 3 <= val <= 30:
                return jsonify({"error": "max_retrieval_results must be between 3 and 30"}), 400
            config.setdefault('retrieval', {})['max_results'] = val
            updated['max_retrieval_results'] = val

        if 'semantic_weight' in data and 'importance_weight' in data and 'recency_weight' in data:
            sw = round(float(data['semantic_weight']), 2)
            iw = round(float(data['importance_weight']), 2)
            rw = round(float(data['recency_weight']), 2)
            mw = round(float(data.get('entity_match_weight', 0.0)), 2)
            total = round(sw + iw + rw + mw, 2)
            if total != 1.0:
                return jsonify({"error": f"Retrieval weights must sum to 1.0 (got {total})"}), 400
            retrieval = config.setdefault('retrieval', {})
            retrieval['semantic_weight'] = sw
            retrieval['importance_weight'] = iw
            retrieval['recency_weight'] = rw
            retrieval['entity_match_weight'] = mw
            updated['semantic_weight'] = sw
            updated['importance_weight'] = iw
            updated['recency_weight'] = rw
            updated['entity_match_weight'] = mw

        if 'deep_archive_age_days' in data:
            val = int(data['deep_archive_age_days'])
            if not 30 <= val <= 365:
                return jsonify({"error": "deep_archive_age_days must be between 30 and 365"}), 400
            config.setdefault('retrieval', {})['deep_archive_age_days'] = val
            updated['deep_archive_age_days'] = val

        # --- Count limits ---
        if 'max_entities_per_retrieval' in data:
            val = int(data['max_entities_per_retrieval'])
            if not 1 <= val <= 8:
                return jsonify({"error": "max_entities_per_retrieval must be between 1 and 8"}), 400
            config.setdefault('features', {}).setdefault('entity_summaries', {})['max_entities_per_retrieval'] = val
            updated['max_entities_per_retrieval'] = val

        if 'max_concepts_retrieved' in data:
            val = int(data['max_concepts_retrieved'])
            if not 1 <= val <= 5:
                return jsonify({"error": "max_concepts_retrieved must be between 1 and 5"}), 400
            config.setdefault('features', {}).setdefault('concepts', {})['max_concepts_retrieved'] = val
            updated['max_concepts_retrieved'] = val

        if 'max_files_displayed' in data:
            val = int(data['max_files_displayed'])
            if not 1 <= val <= 15:
                return jsonify({"error": "max_files_displayed must be between 1 and 15"}), 400
            config.setdefault('features', {}).setdefault('attachments', {})['max_files_displayed'] = val
            updated['max_files_displayed'] = val

        # --- Features ---
        feature_toggles = {
            'concepts_enabled': ('concepts', 'enabled'),
            'entity_summaries_enabled': ('entity_summaries', 'enabled'),
            'attachments_enabled': ('attachments', 'enabled'),
            'tts_enabled': ('tts', 'enabled'),
            'timeline_enabled': ('timeline', 'enabled'),
            'notes_enabled': ('notes', 'enabled'),
        }
        for key, (feature, field) in feature_toggles.items():
            if key in data:
                val = bool(data[key])
                config.setdefault('features', {}).setdefault(feature, {})[field] = val
                updated[key] = val

        # Split saves: profile-scoped keys → profile config, rest → root config
        from src.backend.config import PROFILE_SCOPED_KEYS
        profile_scoped = {k: config[k] for k in PROFILE_SCOPED_KEYS if k in config}
        if profile_scoped:
            save_profile_config(config, profile_scoped)
        save_config(config)

        # Propagate changes to live manager and sub-components
        if manager:
            model_config = config.get("model", {})
            manager.use_testing_model = model_config.get("use_testing", True)
            if manager.use_testing_model:
                manager.model = model_config.get("testing", "claude-haiku-4-5")
            else:
                manager.model = model_config.get("default", "claude-sonnet-4-6")
            manager.temperature = model_config.get("temperature", 1.0)
            manager.max_tokens = model_config.get("max_tokens", 4096)

            # Sync AI client
            manager.ai_client.model = manager.model
            manager.ai_client.temperature = manager.temperature
            manager.ai_client.max_tokens = manager.max_tokens

            # Sync thinking config
            thinking_config = config.get("thinking", {})
            manager.thinking_enabled = thinking_config.get("enabled", False)
            manager.thinking_budget = thinking_config.get("budget_tokens", 10000)

            # Sync context assembler budgets
            ctx_cfg = config.get("context", {})
            ret_cfg = config.get("retrieval", {})
            ca = manager.context_assembler
            ca.recent_budget = ctx_cfg.get("recent_messages_tokens", 50000)
            ca.similarity_threshold = ret_cfg.get("similarity_threshold", 0.25)
            ca.memory_limit = ret_cfg.get("max_results", 10)
            ca.semantic_weight = ret_cfg.get("semantic_weight", 0.4)
            ca.importance_weight = ret_cfg.get("importance_weight", 0.4)
            ca.recency_weight = ret_cfg.get("recency_weight", 0.2)
            ca.entity_match_weight = ret_cfg.get("entity_match_weight", 0.15)
            # Count limits
            features_cfg = config.get("features", {})
            ca.summaries_max_entities = features_cfg.get("entity_summaries", {}).get("max_entities_per_retrieval", 3)
            ca.concepts_max_retrieved = features_cfg.get("concepts", {}).get("max_concepts_retrieved", 2)
            ca.files_max_displayed = features_cfg.get("attachments", {}).get("max_files_displayed", 5)

        # If API keys changed, reinitialize clients
        if manager and any(k in updated for k in ('anthropic_key', 'openai_key')):
            api_keys = config.get('api_keys', {})
            if 'anthropic_key' in updated:
                import anthropic
                manager.ai_client.client = anthropic.Anthropic(api_key=api_keys['anthropic'])

        # Force cache cold start on next message so the tier rebalance +
        # history reload cascade fires with the new settings.
        if manager:
            manager.cache_manager.last_message_time = None
            manager.cache_manager.current_session_cached = False

        return jsonify({"success": True, "updated": updated})

    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid value: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug/context', methods=['GET'])
def debug_context():
    """
    Debug endpoint to see what context blocks would be injected.
    Only available when debug_endpoints is enabled in config.

    Query params:
    - query: Optional test query for memory retrieval (default: empty)

    Response shows all context blocks that would be sent to the AI.
    """
    if not config.get("system", {}).get("debug_endpoints", False):
        return jsonify({"error": "Debug endpoints disabled. Set system.debug_endpoints: true in config.json to enable."}), 403
    try:
        test_query = request.args.get('query', '')

        # Get recent messages for context
        recent_messages = manager.conversation_history[-20:] if manager.conversation_history else []

        # Assemble context
        context = manager.context_assembler.assemble_context(
            recent_messages=recent_messages,
            current_query=test_query
        )

        # Add timeline context if enabled
        timeline_context = ""
        timeline_tokens = 0
        if manager.timeline_enabled:
            timeline_context, timeline_tokens = manager.context_assembler.get_timeline_context()

        # Build sections to see formatted output
        sections = manager.prompt_builder.build_sections(
            {**context, "timeline_context": timeline_context},
            test_query or "(no query)"
        )

        # Format response
        debug_info = {
            "query_used": test_query or "(empty)",
            "blocks": {
                "timeline": {
                    "enabled": manager.timeline_enabled,
                    "chars": len(timeline_context),
                    "tokens": timeline_tokens,
                    "content": timeline_context[:2000] + "..." if len(timeline_context) > 2000 else timeline_context
                },
                "retrieved_memories": {
                    "count": context["metadata"]["memories_included"],
                    "chars": len(sections.get("retrieved", "")),
                    "content": sections.get("retrieved", "")[:3000] + "..." if len(sections.get("retrieved", "")) > 3000 else sections.get("retrieved", "")
                },
                "entity_summaries": {
                    "chars": len(sections.get("entity_summaries", "")),
                    "content": sections.get("entity_summaries", "")[:2000] + "..." if len(sections.get("entity_summaries", "")) > 2000 else sections.get("entity_summaries", "")
                },
                "concepts": {
                    "chars": len(sections.get("concept", "")),
                    "content": sections.get("concept", "")
                },
                "notes": {
                    "chars": len(sections.get("notes", "")),
                    "content": sections.get("notes", "")[:1000] + "..." if len(sections.get("notes", "")) > 1000 else sections.get("notes", "")
                },
                "recent_conversation": {
                    "message_count": len(recent_messages),
                    "chars": len(sections.get("recent", "")),
                }
            },
            "token_counts": context.get("token_counts", {})
        }

        return jsonify(debug_info)

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# =============================================================================
# PHASE 7: File Attachment Endpoints
# =============================================================================

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """
    Upload a file attachment (Phase 7).

    Request: multipart/form-data with 'file' field

    Response:
    {
        "success": true,
        "uuid": "abc12345-...",
        "filename": "photo.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": 1048576,
        "thumbnail_url": "/api/attachment/abc12345/thumbnail"
    }
    """
    try:
        # Check if file attachments are enabled
        files_config = config.get("features", {}).get("attachments", {})
        if not files_config.get("enabled", False):
            return jsonify({"error": "File attachments not enabled"}), 400

        # Check if file is in request
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        # Read file content
        file_content = file.read()
        filename = file.filename

        # Validate file (raises FileValidationError on failure)
        from src.backend.file_storage import FileValidationError
        try:
            mime_type, category = file_storage.validate_file(file_content, filename)
        except FileValidationError as e:
            return jsonify({"error": str(e)}), 400

        # Store file
        stored_file = file_storage.store_file(
            file_content,
            filename,
            mime_type
        )

        # Add to database
        attachment_id = db.add_attachment(
            uuid=stored_file["uuid"],
            filename=stored_file["filename"],
            mime_type=stored_file["mime_type"],
            size_bytes=stored_file["size_bytes"],
            storage_path=stored_file["uuid"],
            file_hash=stored_file.get("hash"),
            content_preview=file_processor.generate_preview(
                stored_file["uuid"],
                stored_file["mime_type"]
            ) if file_processor else None,
            processing_status="ready",
            metadata=stored_file.get("metadata")
        )

        return jsonify({
            "success": True,
            "uuid": stored_file["uuid"],
            "filename": stored_file["filename"],
            "mime_type": stored_file["mime_type"],
            "size_bytes": stored_file["size_bytes"],
            "thumbnail_url": f"/api/attachment/{stored_file['uuid']}/thumbnail"
        })

    except Exception as e:
        import sys
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/attachment/<uuid>', methods=['GET'])
def get_attachment_info(uuid):
    """
    Get attachment metadata.

    Response:
    {
        "uuid": "abc12345-...",
        "filename": "photo.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": 1048576,
        "ai_description": "A black crow perched on a fence...",
        "created_at": "2025-12-14T10:00:00Z"
    }
    """
    try:
        attachment = db.get_attachment_by_uuid(uuid)
        if not attachment:
            return jsonify({"error": "Attachment not found"}), 404

        return jsonify({
            "uuid": attachment["uuid"],
            "filename": attachment["filename"],
            "mime_type": attachment["mime_type"],
            "size_bytes": attachment["size_bytes"],
            "ai_description": attachment.get("ai_description"),
            "content_preview": attachment.get("content_preview"),
            "created_at": attachment["created_at"],
            "metadata": attachment.get("metadata", {})
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/attachment/<uuid>/thumbnail', methods=['GET'])
def get_attachment_thumbnail(uuid):
    """
    Get attachment thumbnail image.

    Returns the thumbnail version for images, or 404 for non-images.
    """
    try:
        attachment = db.get_attachment_by_uuid(uuid)
        if not attachment:
            return jsonify({"error": "Attachment not found"}), 404

        # Check if it's an image
        if not attachment["mime_type"].startswith("image/"):
            return jsonify({"error": "Attachment is not an image"}), 400

        # Get thumbnail path
        db_dir = Path(config["storage"]["database_path"]).parent
        attachments_dir = db_dir / "attachments"
        file_dir = attachments_dir / attachment["uuid"]

        # Find thumbnail
        for ext in [".jpg", ".jpeg", ".png", ".webp"]:
            thumbnail_path = file_dir / f"thumbnail{ext}"
            if thumbnail_path.exists():
                return send_from_directory(
                    str(file_dir),
                    f"thumbnail{ext}",
                    mimetype=attachment["mime_type"]
                )

        # Fall back to optimized
        for ext in [".jpg", ".jpeg", ".png", ".webp"]:
            optimized_path = file_dir / f"optimized{ext}"
            if optimized_path.exists():
                return send_from_directory(
                    str(file_dir),
                    f"optimized{ext}",
                    mimetype=attachment["mime_type"]
                )

        return jsonify({"error": "Thumbnail not found"}), 404

    except Exception as e:
        import sys
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/attachment/<uuid>/image', methods=['GET'])
def get_attachment_image(uuid):
    """
    Get full attachment image (optimized version).

    Returns the optimized version for images.
    """
    try:
        attachment = db.get_attachment_by_uuid(uuid)
        if not attachment:
            return jsonify({"error": "Attachment not found"}), 404

        # Check if it's an image
        if not attachment["mime_type"].startswith("image/"):
            return jsonify({"error": "Attachment is not an image"}), 400

        # Get image path
        db_dir = Path(config["storage"]["database_path"]).parent
        attachments_dir = db_dir / "attachments"
        file_dir = attachments_dir / attachment["uuid"]

        # Find optimized or original
        for version in ["optimized", "original"]:
            for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
                image_path = file_dir / f"{version}{ext}"
                if image_path.exists():
                    return send_from_directory(
                        str(file_dir),
                        f"{version}{ext}",
                        mimetype=attachment["mime_type"]
                    )

        return jsonify({"error": "Image not found"}), 404

    except Exception as e:
        import sys
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/attachments', methods=['GET'])
def list_attachments():
    """
    List recent attachments.

    Query params:
    - limit: Number of attachments to return (default 20)
    - with_description: Only return attachments with descriptions (default false)

    Response:
    {
        "attachments": [
            {
                "uuid": "abc12345-...",
                "filename": "photo.jpg",
                "mime_type": "image/jpeg",
                "ai_description": "...",
                "thumbnail_url": "/api/attachment/abc12345/thumbnail"
            },
            ...
        ]
    }
    """
    try:
        limit = request.args.get('limit', 20, type=int)
        with_description = request.args.get('with_description', 'false').lower() == 'true'

        attachments = db.get_recent_attachments(
            limit=limit,
            with_description=with_description
        )

        result = []
        for att in attachments:
            item = {
                "uuid": att["uuid"],
                "filename": att["filename"],
                "mime_type": att["mime_type"],
                "ai_description": att.get("ai_description"),
                "created_at": att["created_at"]
            }
            if att["mime_type"].startswith("image/"):
                item["thumbnail_url"] = f"/api/attachment/{att['uuid']}/thumbnail"
            result.append(item)

        return jsonify({"attachments": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# PHASE 9: Text-to-Speech Endpoint
# =============================================================================

def get_tts_cache_path(text: str, voice_id: str, model_id: str) -> Path:
    """
    Get the cache file path for a TTS request.

    Uses a hash of text + voice + model to create unique cache keys.
    This means the same text with different voices gets different cache files.
    """
    import hashlib

    # Create hash from text + settings
    cache_key = f"{text}|{voice_id}|{model_id}"
    text_hash = hashlib.sha256(cache_key.encode('utf-8')).hexdigest()[:16]

    # Get cache directory
    db_path = Path(config["storage"]["database_path"])
    cache_dir = db_path.parent / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir / f"{text_hash}.mp3"


@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    """
    Convert text to speech using ElevenLabs (Phase 9).

    Request body:
    {
        "text": "Text to convert to speech"
    }

    Response: Audio file (mp3)

    Caching: Audio is cached on disk by text hash. Replaying the same
    message serves from cache (no API cost).
    """
    try:
        # Check if TTS is enabled
        tts_config = config.get("features", {}).get("tts", {})
        if not tts_config.get("enabled", False):
            return jsonify({"error": "TTS not enabled"}), 400

        # Get API key
        elevenlabs_key = config.get("api_keys", {}).get("elevenlabs")
        if not elevenlabs_key or elevenlabs_key == "YOUR_ELEVENLABS_API_KEY_HERE":
            return jsonify({"error": "ElevenLabs API key not configured"}), 400

        # Get request data
        data = request.json
        if not data or not data.get('text'):
            return jsonify({"error": "Text required"}), 400

        text = data['text'].strip()
        if len(text) > 40000:
            return jsonify({"error": "Text too long (max 40000 characters)"}), 400

        # Get TTS settings
        model_id = tts_config.get("model_id", "eleven_flash_v2_5")
        voice_id = tts_config.get("voice_id", "86DSREGT0ynChViVr49a")
        output_format = tts_config.get("output_format", "mp3_44100_128")

        # Check cache first
        cache_enabled = tts_config.get("cache_enabled", True)
        cache_path = get_tts_cache_path(text, voice_id, model_id)

        if cache_enabled and cache_path.exists():
            # Serve from cache
            print(f"🔊 TTS cache hit: {cache_path.name}")
            audio_bytes = cache_path.read_bytes()
            return Response(
                audio_bytes,
                mimetype='audio/mpeg',
                headers={
                    'Content-Type': 'audio/mpeg',
                    'Content-Disposition': 'inline; filename="speech.mp3"',
                    'X-TTS-Cache': 'hit'
                }
            )

        # Import ElevenLabs
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError:
            return jsonify({"error": "ElevenLabs package not installed. Run: pip install elevenlabs"}), 500

        # Create client and generate audio
        print(f"🔊 TTS generating: {len(text)} chars...")
        client = ElevenLabs(api_key=elevenlabs_key)

        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
        )

        # Collect audio chunks into bytes
        audio_bytes = b''.join(chunk for chunk in audio_generator)

        # Save to cache
        if cache_enabled:
            try:
                cache_path.write_bytes(audio_bytes)
                print(f"🔊 TTS cached: {cache_path.name} ({len(audio_bytes)} bytes)")
            except Exception as cache_error:
                print(f"⚠️  TTS cache write failed: {cache_error}")

        # Return audio file
        return Response(
            audio_bytes,
            mimetype='audio/mpeg',
            headers={
                'Content-Type': 'audio/mpeg',
                'Content-Disposition': 'inline; filename="speech.mp3"',
                'X-TTS-Cache': 'miss'
            }
        )

    except Exception as e:
        import sys
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/tts/cache/stats', methods=['GET'])
def tts_cache_stats():
    """Get TTS cache statistics."""
    try:
        db_path = Path(config["storage"]["database_path"])
        cache_dir = db_path.parent / "tts_cache"

        if not cache_dir.exists():
            return jsonify({
                "files": 0,
                "total_bytes": 0,
                "total_mb": 0
            })

        files = list(cache_dir.glob("*.mp3"))
        total_bytes = sum(f.stat().st_size for f in files)

        return jsonify({
            "files": len(files),
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tts/cache/clear', methods=['POST'])
def tts_cache_clear():
    """Clear TTS cache."""
    try:
        db_path = Path(config["storage"]["database_path"])
        cache_dir = db_path.parent / "tts_cache"

        if not cache_dir.exists():
            return jsonify({"cleared": 0, "bytes_freed": 0})

        files = list(cache_dir.glob("*.mp3"))
        total_bytes = sum(f.stat().st_size for f in files)

        for f in files:
            f.unlink()

        return jsonify({
            "cleared": len(files),
            "bytes_freed": total_bytes,
            "mb_freed": round(total_bytes / (1024 * 1024), 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# DEBUG ENDPOINTS
# =============================================================================

@app.route('/api/debug/messages', methods=['GET'])
def debug_messages():
    """
    DEBUG: Show all messages with metadata for troubleshooting.
    Only available when debug_endpoints is enabled in config.
    """
    if not config.get("system", {}).get("debug_endpoints", False):
        return jsonify({"error": "Debug endpoints disabled. Set system.debug_endpoints: true in config.json to enable."}), 403
    try:
        # Get all messages
        all_messages = db.execute_query("""
            SELECT id, sender, timestamp, tier,
                   substr(content, 1, 100) as content_preview,
                   metadata
            FROM messages
            ORDER BY timestamp DESC
            LIMIT 100
        """)

        messages_list = []
        for msg in all_messages:
            msg_dict = dict(msg)
            # Parse metadata if present
            if msg_dict.get('metadata'):
                try:
                    msg_dict['metadata_parsed'] = json.loads(msg_dict['metadata'])
                except:
                    msg_dict['metadata_parsed'] = None
            messages_list.append(msg_dict)

        return jsonify({
            "total": len(messages_list),
            "messages": messages_list
        })

    except Exception as e:
        import sys
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug/cleanup', methods=['POST'])
def debug_cleanup():
    """
    DEBUG: Clean up retrieved memories and temporary messages.
    Only available when debug_endpoints is enabled in config.
    """
    if not config.get("system", {}).get("debug_endpoints", False):
        return jsonify({"error": "Debug endpoints disabled. Set system.debug_endpoints: true in config.json to enable."}), 403
    try:
        # Delete retrieved memories
        deleted_retrieved = db.execute_write("""
            DELETE FROM messages
            WHERE json_extract(metadata, '$.retrieved') = 1
        """)

        # Delete temporary messages
        deleted_temp = db.execute_write("""
            DELETE FROM messages
            WHERE json_extract(metadata, '$.temporary') = 1
        """)

        return jsonify({
            "success": True,
            "deleted_retrieved": deleted_retrieved,
            "deleted_temporary": deleted_temp,
            "message": f"Cleaned up {deleted_retrieved} retrieved memories and {deleted_temp} temporary messages"
        })

    except Exception as e:
        import sys
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug/delete/<int:message_id>', methods=['DELETE'])
def debug_delete_message(message_id):
    """
    DEBUG: Delete a specific message by ID.
    Only available when debug_endpoints is enabled in config.
    """
    if not config.get("system", {}).get("debug_endpoints", False):
        return jsonify({"error": "Debug endpoints disabled. Set system.debug_endpoints: true in config.json to enable."}), 403
    try:
        # Delete the message
        deleted = db.execute_write("""
            DELETE FROM messages
            WHERE id = ?
        """, (message_id,))

        if deleted > 0:
            return jsonify({
                "success": True,
                "message": f"Deleted message {message_id}"
            })
        else:
            return jsonify({
                "success": False,
                "message": f"Message {message_id} not found"
            }), 404

    except Exception as e:
        import sys
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


def _run_startup_entity_backfill():
    """Background thread: process messages that missed entity assignment last session."""
    try:
        processed = manager.background_queue.run_startup_backfill()
        if processed:
            print(f"✓ Startup backfill complete ({processed} messages assigned)")
    except Exception as e:
        count = db.get_unchecked_message_count()
        print(f"⚠ Startup entity backfill failed ({count} messages still pending): {e}")
        print(f"  When credits are available, run: python scripts/backfill_message_entities.py")


def main():
    """Start the Flask server."""
    global setup_mode

    if needs_setup():
        # Boot in setup mode — serve setup UI only
        setup_mode = True
        print("=" * 70)
        print("  MNEME — FIRST-TIME SETUP")
        print("=" * 70)
        print()
        print("  No configuration found. Starting setup wizard...")
        print()
        port = 8080
    else:
        # Normal boot
        init_system()

        # Backfill any messages that missed entity assignment last session (in background)
        import threading
        threading.Thread(target=_run_startup_entity_backfill, daemon=True).start()

        # Get port from config
        port = config.get("system", {}).get("server_port", 8080)

    print("=" * 70)
    print(f"  MNEME WEB SERVER")
    print("=" * 70)
    print()
    print(f"  Local:     http://localhost:{port}")
    print(f"  Tailscale: http://[tailscale-ip]:{port}")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 70)
    print()

    # Start server
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == "__main__":
    main()
