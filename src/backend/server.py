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
import atexit
import threading
import time
import re
import tempfile
from datetime import datetime, timezone
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
from src.backend.config import (
    load_config, save_config, save_profile_config, update_active_profile, get_backup_path,
    get_mneme_home, get_default_home, get_project_root,
)
from src.backend.home_migration import describe_install, copy_install, find_candidate_installs, MigrationError
from src.backend.embeddings import create_embedding_generator
from src.backend.embedding_migration import (
    migration_manager,
    PROVIDER_SIMILARITY_THRESHOLD,
)
from src.backend.conversation import ConversationManager
from src.backend.prompt_builder import resolve_instructions_path
from src.backend.model_capabilities import get_model_capabilities, max_recent_window_for_model
from src.backend import power_management
from src.backend.stream_worker import GenerationRegistry, GenerationInProgress
from src.backend.network_access import TailscaleAccessGate

app = Flask(__name__, static_folder='../frontend')
access_gate = TailscaleAccessGate()

# Allow large file uploads (Phase 7: 25MB for Anthropic API limit)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB

# Browser-origin defense in depth; network authorization is enforced separately
# by ``restrict_network_access`` for every route.
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

# Durable stream reconnect (v1): tracks in-flight turns per profile so generation
# survives client disconnects and cleanup never deletes a still-generating turn.
generation_registry = GenerationRegistry()

# Home relocation (legacy app-folder installs -> %LOCALAPPDATA%/Mneme) progress.
# Updated by the background copy thread started from /api/relocate; read by
# /api/relocation/status. Never touched from more than one thread at a time
# because /api/relocate refuses to start a second copy while one is running.
_relocation_lock = threading.Lock()
_relocation_state = {
    "in_progress": False,
    "done": False,
    "error": None,
    "done_bytes": 0,
    "total_bytes": 0,
    "dst": "",
}


def _current_profile_name():
    """Active profile folder name (the unit the in-flight guard is keyed on)."""
    storage_cfg = config.get("storage", {}) if config else {}
    return storage_cfg.get("active_profile", "main") or "main"
startup_lock = threading.Lock()
STARTUP_STEPS = 7  # config, database, embeddings, entities, attachments, tiers, ready

startup_status = {
    "state": "starting",
    "phase": "Starting Mneme",
    "detail": "Preparing the local memory system...",
    "step": 0,
    "steps": STARTUP_STEPS,
    "started_at": time.time(),
    "ready_at": None,
    "error": None,
    "background_work": [],
}


def set_startup_status(state=None, phase=None, detail=None, error=None, background_work=None, step=None):
    """Update process-wide startup status for the loading page and tray."""
    with startup_lock:
        if state is not None:
            startup_status["state"] = state
            if state == "ready":
                startup_status["ready_at"] = time.time()
                startup_status["step"] = STARTUP_STEPS
        if phase is not None:
            startup_status["phase"] = phase
        if detail is not None:
            startup_status["detail"] = detail
        if error is not None:
            startup_status["error"] = str(error)
        if background_work is not None:
            startup_status["background_work"] = background_work
        if step is not None:
            startup_status["step"] = step


def get_startup_status():
    """Return a copy of startup status safe for JSON responses."""
    with startup_lock:
        status = dict(startup_status)
        status["background_work"] = list(startup_status.get("background_work", []))
        return status


def needs_setup():
    """
    Check if Mneme needs first-time setup.

    Returns True if config.json doesn't exist or has placeholder API keys.
    """
    config_path = get_mneme_home() / "config.json"
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
    set_startup_status(
        phase="Opening memory database",
        detail="Connecting to the active profile and checking stored messages...",
        step=2,
    )
    db_path = cfg["storage"]["database_path"]

    new_db = Database(db_path)
    message_count = new_db.get_message_count()

    set_startup_status(
        phase="Preparing embeddings",
        detail="Loading the local retrieval pipeline...",
        step=3,
    )
    embedder = create_embedding_generator(cfg)

    # Initialize graph/entity schema for all installs. Even with entity
    # summaries disabled, core tables reference entity tables via FKs.
    entity_config = cfg.get("features", {}).get("entity_summaries", {})
    from src.backend.graph_database import GraphDatabase
    graph_db = GraphDatabase(cfg)
    graph_db.initialize_schema()
    if entity_config.get("enabled", False):
        set_startup_status(
            phase="Loading entity memory",
            detail="Opening entity links and summary metadata...",
            step=4,
        )
        entity_count = len(graph_db.get_entity_stats(min_mentions=1))
        print(f"✓ Entity system enabled ({entity_count} entities)")
    else:
        print("✓ Entity schema ready")

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
        set_startup_status(
            phase="Preparing attachments",
            detail="Checking file storage for the active profile...",
            step=5,
        )
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

    set_startup_status(
        phase="Rebalancing memory tiers",
        detail="Making sure recent, searchable, and archived memories are in the right places...",
        step=6,
    )
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
    set_startup_status(
        state="starting",
        phase="Loading configuration",
        detail="Reading Mneme settings and active profile...",
        step=1,
        error=None,
    )

    try:
        config = load_config()
        active_profile = config["storage"].get("active_profile", "")

        print(f"✓ Configuration loaded")
        if active_profile:
            print(f"✓ Active profile: '{active_profile}'")
        print(f"✓ Database path: {config['storage']['database_path']}")

    except Exception as e:
        print(f"✗ Configuration error: {e}")
        set_startup_status(state="failed", phase="Configuration error", detail=str(e), error=e)
        raise

    try:
        db, manager, file_storage, file_processor = _build_system(config)
        set_startup_status(
            state="ready",
            phase="Mneme is ready",
            detail="The app is ready. Catch-up memory work may continue in the background.",
        )
        print()
    except Exception as e:
        print(f"✗ Initialization error: {e}")
        set_startup_status(state="failed", phase="Initialization error", detail=str(e), error=e)
        raise

    # Keep-awake is a server-lifetime/global setting (system.*, not per-profile).
    # Only engage it in the process that actually serves requests: app.run()
    # below runs with debug=False so Werkzeug's reloader never spawns a second
    # process, but guard anyway in case that ever changes — with the reloader
    # enabled, the parent watcher process doesn't set WERKZEUG_RUN_MAIN, only
    # the child that actually serves requests does.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        try:
            power_management.apply_setting(config.get("system", {}).get("keep_pc_awake", False))
        except Exception as e:
            print(f"[PowerManagement] Failed to apply keep_pc_awake setting: {e}")


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
def restrict_network_access():
    """Keep Mneme reachable only from this device and verified tailnet peers."""
    if not access_gate.allows(request.remote_addr):
        return jsonify({"error": "Mneme is only available locally or through Tailscale."}), 403


@app.before_request
def check_setup_mode():
    """Block API requests when in setup mode (except setup endpoints and static files)."""
    status = get_startup_status()

    if status["state"] == "starting":
        allowed_paths = {
            '/',
            '/startup.css',
            '/startup.js',
            '/favicon.svg',
            '/api/startup/status',
        }
        if request.path in allowed_paths or request.path.startswith('/assets/'):
            return None
        if request.path.startswith('/api/'):
            return jsonify(status), 503
        return None

    if status["state"] == "failed":
        allowed_paths = {
            '/',
            '/startup.css',
            '/startup.js',
            '/favicon.svg',
            '/api/startup/status',
        }
        if request.path in allowed_paths or request.path.startswith('/assets/'):
            return None
        if request.path.startswith('/api/'):
            return jsonify(status), 503
        return None

    if not setup_mode:
        return None
    # Allow setup endpoints
    if request.path in (
        '/api/setup', '/api/setup/status', '/api/startup/status',
        '/api/setup/detect-installs', '/api/setup/validate-source', '/api/setup/import',
    ):
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
    if get_startup_status()["state"] in ("starting", "failed"):
        return send_from_directory(app.static_folder, 'startup.html')
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


@app.route('/startup.css')
def serve_startup_css():
    """Serve startup loading page CSS."""
    return send_from_directory(app.static_folder, 'startup.css')


@app.route('/startup.js')
def serve_startup_js():
    """Serve startup loading page JavaScript."""
    return send_from_directory(app.static_folder, 'startup.js')


@app.route('/api/startup/status', methods=['GET'])
def startup_status_endpoint():
    """Report startup readiness for the loading page and tray launcher."""
    return jsonify(get_startup_status())


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


@app.route('/api/command', methods=['POST'])
def run_command():
    """
    Run a @command directly for the command console (drawer).

    Unlike typed commands going through the chat pipeline, this path stores
    NOTHING in conversation history — no temporary messages, no cache-pollution
    cleanup. Human queries to the memory system are meta-work, not conversation.

    Request body:  { "command": "@entity list" }
    Response:      the raw handler result:
                   { "success": bool, "command": str, "message": str, "data": {...} }
    """
    try:
        data = request.json
        if data is None:
            return jsonify({"error": "Invalid JSON in request body"}), 400

        command = (data.get('command') or '').strip()
        if not command.startswith('@'):
            return jsonify({"error": "Not a command (must start with @)"}), 400
        if len(command) > 100000:
            return jsonify({"error": "Command too long"}), 400

        # Suppress handler prints (same hygiene as /api/chat)
        output_buffer = io.StringIO()
        with redirect_stdout(output_buffer):
            result = manager.command_handler.handle_command(command, marked_by="user")

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
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

        # Durable stream reconnect (v1): run the turn in a background worker so a
        # client disconnect (mobile tab switch, screen lock, network blip) can no
        # longer kill generation. The worker persists the response regardless of
        # whether anyone is still listening; this endpoint only relays events.
        profile = _current_profile_name()
        try:
            worker = generation_registry.start(
                profile,
                manager.process_message_stream(message, attachment_uuids=attachment_uuids),
            )
        except GenerationInProgress:
            # No double-generation: a turn is already in flight for this profile.
            return jsonify({
                "error": "generation_in_progress",
                "message": "Mneme is still writing a response. Please wait for it to finish."
            }), 409

        def generate():
            """Relay buffered worker events to the SSE client."""
            for event in worker.events():
                yield f"data: {json.dumps(event)}\n\n"

        # Return SSE response. NOTE: stream_with_context is intentionally NOT used
        # here — the turn runs on the worker thread, not in this request context,
        # so the response generator must be free to stop (on disconnect) without
        # affecting generation.
        return Response(
            generate(),
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
    - before_id: If set, return the page of messages immediately older than
      this message id (keyset pagination for "load older messages" scrolling).
      Omit for the initial/most-recent page — behavior is unchanged from
      before pagination was added.

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
        ],
        "has_more": true
    }
    """
    try:
        limit = request.args.get('limit', 50, type=int)
        before_id = request.args.get('before_id', type=int)
        messages, has_more = db.get_message_page(limit=limit, before_id=before_id)

        return jsonify({"messages": messages, "has_more": has_more})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _format_transcript_timestamp(timestamp: str) -> str:
    """Return a readable timestamp for transcript headings."""
    if not timestamp:
        return "Unknown time"

    normalized = str(timestamp).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(timestamp)


def _transcript_filename(profile_name: str, export_format: str = "markdown") -> str:
    """Build a filesystem-safe transcript filename."""
    safe_profile = re.sub(r"[^a-zA-Z0-9._-]+", "-", profile_name or "mneme").strip("-")
    if not safe_profile:
        safe_profile = "mneme"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    extension = "json" if export_format == "json" else "md"
    return f"mneme-{safe_profile}-transcript-{stamp}.{extension}"


def _build_markdown_transcript(messages, profile_name: str, instance_name: str) -> str:
    """Build a portable Markdown transcript for the active profile."""
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Mneme Transcript - {instance_name or profile_name or 'Profile'}",
        "",
        f"- Profile: {profile_name or 'unknown'}",
        f"- Exported: {exported_at}",
        f"- Messages: {len(messages)}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        sender = str(msg.get("sender") or "unknown").strip() or "unknown"
        label = "User" if sender == "user" else "Assistant" if sender == "assistant" else sender.title()
        timestamp = _format_transcript_timestamp(msg.get("timestamp", ""))
        content = str(msg.get("content") or "").rstrip()

        lines.extend([
            f"## {timestamp} - {label}",
            "",
            content if content else "_[empty message]_",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def _build_importable_json_transcript(messages) -> str:
    """Build a JSON transcript accepted by scripts/import_conversation.py."""
    export_messages = []
    for msg in messages:
        sender = str(msg.get("sender") or "").strip()
        if sender not in ("user", "assistant"):
            sender = "assistant" if sender == "system" else sender

        export_messages.append({
            "role": sender,
            "content": str(msg.get("content") or ""),
            "timestamp": str(msg.get("timestamp") or ""),
        })

    return json.dumps(export_messages, indent=2, ensure_ascii=False) + "\n"


@app.route('/api/export/transcript', methods=['GET'])
def export_transcript():
    """
    Download the current profile conversation as a transcript.

    This is intentionally a real app export path, not an AI/tool command, so
    users do not need @run or @artifact to save their conversations.
    """
    try:
        if db is None:
            return jsonify({"error": "Database not initialized"}), 503

        export_format = (request.args.get("format", "markdown") or "markdown").strip().lower()
        if export_format in ("md", "markdown"):
            export_format = "markdown"
        elif export_format != "json":
            return jsonify({"error": "Unsupported transcript format. Use markdown or json."}), 400

        rows = db.execute_query("""
            SELECT id, timestamp, sender, content
            FROM messages
            ORDER BY timestamp ASC, id ASC
        """)
        messages = [dict(row) for row in rows]

        storage_cfg = config.get("storage", {}) if config else {}
        identity_cfg = config.get("identity", {}) if config else {}
        profile_name = storage_cfg.get("active_profile", "main")
        instance_name = identity_cfg.get("instance_name") or profile_name

        if export_format == "json":
            transcript = _build_importable_json_transcript(messages)
            content_type = "application/json; charset=utf-8"
        else:
            transcript = _build_markdown_transcript(messages, profile_name, instance_name)
            content_type = "text/markdown; charset=utf-8"

        filename = _transcript_filename(profile_name, export_format)

        return Response(
            transcript,
            content_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Mneme-Message-Count": str(len(messages)),
                "X-Mneme-Transcript-Format": export_format,
            },
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/messages/cleanup-orphans', methods=['POST'])
def cleanup_orphan_messages():
    """
    Clean up orphaned user messages that have no AI response.

    Called by frontend on:
    - Live interruption (catch block in sendMessage)
    - Page startup (before rendering history)

    Durable stream reconnect (v1): if a turn is currently generating for this
    profile, the trailing turn is protected so cleanup can't delete the
    in-flight user row (or its pre-allocated empty assistant shell).

    Response: {"deleted": N, "restored_text": "..." | null}
    """
    try:
        protect = generation_registry.is_active(_current_profile_name())
        result = db.cleanup_orphan_messages(protect_trailing_turn=protect)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/chat/cancel', methods=['POST'])
def cancel_generation():
    """
    Cooperatively cancel the in-flight turn for the active profile.

    Called by the frontend stop-button flow BEFORE save-partial /
    cleanup-orphans. The worker closes the turn generator (raising
    GeneratorExit inside process_message_stream — the pre-v1 kill semantics
    those endpoints were designed around) and the in-flight guard clears, so
    the follow-up save-partial / cleanup calls behave exactly as before.

    NOT called on silent disconnects or page load — a dropped socket must
    keep generating (that's the whole point of durable stream reconnect).

    Response: {"cancelled": true, "finished": bool}
    """
    try:
        finished = generation_registry.cancel(_current_profile_name())
        return jsonify({"cancelled": True, "finished": bool(finished)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/chat/generation-status', methods=['GET'])
def generation_status():
    """
    Report whether a turn is currently generating for the active profile.

    Durable stream reconnect (v1): the frontend polls this on page load (and
    after a mid-stream socket death) to show a "still writing" indicator and
    wait for the turn to land, instead of treating the disconnect as a failure.

    Response: {"active": bool}
    """
    try:
        return jsonify({"active": generation_registry.is_active(_current_profile_name())})
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

        # Durable stream reconnect (v1): a continuation is also a full turn that
        # persists (it merges the continuation back into the DB message), so it
        # runs on the worker and participates in the in-flight guard too.
        profile = _current_profile_name()
        try:
            worker = generation_registry.start(
                profile,
                manager.continue_message_stream(int(interrupted_message_id)),
            )
        except GenerationInProgress:
            return jsonify({
                "error": "generation_in_progress",
                "message": "Mneme is still writing a response. Please wait for it to finish."
            }), 409

        def generate():
            for event in worker.events():
                yield f"data: {json.dumps(event)}\n\n"

        return Response(
            generate(),
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

        model_id = _normalize_model_id(model_id)
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

def _normalize_model_id(model_id):
    """
    Strip the date suffix from new-format Claude model IDs.
    'claude-haiku-4-5-20251001' → 'claude-haiku-4-5'
    Old-format IDs (claude-3-opus-20240229) are left unchanged.
    """
    import re
    # New format: claude-{family}-{major}-{minor}[-{8-digit-date}]
    # Only strip if the last segment is exactly 8 digits (a date stamp)
    return re.sub(r'^(claude-[a-z]+-\d+-\d+)-\d{8}$', r'\1', model_id)


def _data_dir():
    """
    Derive the profiles data directory from the active config's storage template.

    Mirrors the resolution home_migration._data_dir_for uses for install
    descriptions, so profile listing/creation/switching agree with relocation
    and import about where profile folders live.
    """
    storage = config.get("storage", {})
    template = storage.get("database_path_template", storage.get("database_path", ""))

    if template and "{profile}" in template:
        base = template.split("{profile}")[0]
        base_path = Path(base)
        if base_path.is_absolute():
            return base_path
        return get_mneme_home() / base_path
    if template:
        return Path(template).parent.parent
    return get_mneme_home() / "data"


@app.route('/api/profiles', methods=['GET'])
def list_profiles():
    """
    List all available profiles.

    Scans data/ for subdirectories containing memory.db.
    Returns profile metadata (name, display name, model, message count).
    """
    try:
        import sqlite3 as _sqlite3

        # Read base model from root config.json (not overlaid in-memory config)
        base_model_id = ""
        root_config_path = get_mneme_home() / "config.json"
        if root_config_path.exists():
            try:
                with open(root_config_path, 'r', encoding='utf-8') as f:
                    root_cfg = json.load(f)
                base_model_id = root_cfg.get("model", {}).get("default", "")
            except Exception:
                pass

        storage = config.get("storage", {})
        data_dir = _data_dir()

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
        data_dir = _data_dir()

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
            profile_config["model"] = {"default": _normalize_model_id(model_id)}

        with open(profile_dir / "config.json", 'w', encoding='utf-8') as f:
            json.dump(profile_config, f, indent=2, ensure_ascii=False)

        # Copy system_instructions.example.txt if it exists (template — stays at project root)
        example_instructions = get_project_root() / "system_instructions.example.txt"
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
        data_dir = _data_dir()

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
        # New installs always use local embeddings — no OpenAI key, no choice.
        # The OpenAI embedding path still exists in embeddings.py for existing
        # users who set retrieval.embedding_provider = "openai" manually.
        embedding_provider = 'local'
        elevenlabs_key = (data.get('elevenlabs_key') or '').strip()
        instance_name = (data.get('instance_name') or '').strip()
        model_id = (data.get('model') or 'claude-sonnet-4-6').strip()

        if not anthropic_key:
            return jsonify({"error": "Anthropic API key is required"}), 400

        # Build config from example template. Templates (*.example.*) are code
        # and stay at the project root; the written user state goes to the
        # resolved Mneme home (%LOCALAPPDATA%/Mneme for fresh installs).
        project_root = get_project_root()
        mneme_home = get_mneme_home()
        mneme_home.mkdir(parents=True, exist_ok=True)
        example_path = project_root / "config.example.json"
        config_path = mneme_home / "config.json"

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
        new_config["api_keys"]["elevenlabs"] = elevenlabs_key
        new_config["identity"]["user_name"] = user_name
        new_config["identity"]["instance_name"] = instance_name
        new_config["model"]["default"] = model_id
        retrieval_cfg = new_config.setdefault("retrieval", {})
        retrieval_cfg["embedding_provider"] = embedding_provider
        if embedding_provider == "local" and "similarity_threshold" not in data:
            # Measured on the actual (asymmetric) retrieval path — query embeddings
            # carry the BGE query prefix, message embeddings don't — related
            # query->message pairs scored ~0.54-0.75, unrelated ~0.31-0.53, so the
            # OpenAI-tuned 0.25 default filters nothing. See config.example.json
            # _threshold_note for the measurements justifying 0.50.
            retrieval_cfg["similarity_threshold"] = 0.50

        # Write config.json
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        print(f"✓ Configuration written to {config_path}")

        # Copy system_instructions.example.txt to home (for legacy/fallback)
        import shutil
        example_instructions = project_root / "system_instructions.example.txt"
        root_instructions = mneme_home / "system_instructions.txt"
        if example_instructions.exists() and not root_instructions.exists():
            shutil.copy2(str(example_instructions), str(root_instructions))
            print(f"✓ System instructions created")

        # Create per-profile config and instructions for the default "main" profile
        # Without this, profile listing shows the folder slug "main" instead of the instance name
        active_profile = new_config.get("storage", {}).get("active_profile", "main")
        db_template = new_config.get("storage", {}).get("database_path", "./data/{profile}/memory.db")
        if "{profile}" in db_template:
            data_base = Path(db_template.split("{profile}")[0])
        else:
            data_base = Path(db_template.replace("/memory.db", "")).parent
        data_root = data_base if data_base.is_absolute() else mneme_home / data_base
        profile_dir = data_root / active_profile
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
# SETUP-MODE IMPORT ("Import from a previous Mneme")
# =============================================================================

@app.route('/api/setup/detect-installs', methods=['GET'])
def setup_detect_installs():
    """Scan common locations for a previous Mneme install to import from."""
    if not setup_mode:
        return jsonify({"error": "Not in setup mode"}), 403
    try:
        # A database-only folder can be useful for diagnostics, but setup
        # import needs the root config to preserve API keys, storage paths,
        # and profile selection and to boot successfully afterward.
        installs = [
            install for install in find_candidate_installs(exclude=get_mneme_home())
            if install.get("has_config")
        ]
        return jsonify({"installs": installs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/setup/validate-source', methods=['POST'])
def setup_validate_source():
    """Describe a user-supplied folder path as a candidate Mneme install."""
    if not setup_mode:
        return jsonify({"error": "Not in setup mode"}), 403
    try:
        data = request.get_json() or {}
        path = (data.get('path') or '').strip()
        if not path:
            return jsonify({"error": "path is required"}), 400
        info = describe_install(path)
        if info is None:
            return jsonify({"error": "That folder doesn't look like a Mneme install."}), 400
        if not info.get("has_config"):
            return jsonify({
                "error": "That folder has Mneme data but no config.json, so it cannot be imported as a complete install."
            }), 400
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/setup/import', methods=['POST'])
def setup_import():
    """
    Import a previous Mneme install's user state into the current home.

    Copies data/, config.json, and system_instructions.txt from the source
    install into get_mneme_home(), then transitions out of setup mode exactly
    like /api/setup does.
    """
    global setup_mode

    if not setup_mode:
        return jsonify({"error": "Not in setup mode"}), 403
    try:
        data = request.get_json() or {}
        path = (data.get('path') or '').strip()
        if not path:
            return jsonify({"error": "path is required"}), 400

        info = describe_install(path)
        if info is None:
            return jsonify({"error": "That folder doesn't look like a Mneme install."}), 400
        if not info.get("has_config"):
            return jsonify({
                "error": "That folder has Mneme data but no config.json, so it cannot be imported as a complete install."
            }), 400

        report = copy_install(path, get_mneme_home())

        init_system()
        setup_mode = False

        import threading as _threading
        _threading.Thread(target=_run_startup_entity_backfill, daemon=True).start()

        print("✓ Setup complete — imported from previous install!")
        return jsonify({"success": True, "report": report})

    except MigrationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =============================================================================
# HOME RELOCATION (legacy app-folder installs -> %LOCALAPPDATA%/Mneme)
# =============================================================================

def _relocation_available():
    """True iff this is a legacy install that hasn't relocated or declined."""
    if setup_mode:
        return False
    try:
        if get_mneme_home().resolve() != get_project_root().resolve():
            return False
    except OSError:
        return False
    if (get_default_home() / "config.json").exists():
        return False
    if config and config.get("storage", {}).get("relocation_declined"):
        return False
    return True


def _run_relocation():
    """Background worker for /api/relocate. Never deletes anything."""
    def on_progress(done_bytes, total_bytes, label):
        with _relocation_lock:
            _relocation_state["done_bytes"] = done_bytes
            _relocation_state["total_bytes"] = total_bytes

    try:
        report = copy_install(
            get_project_root(), get_default_home(),
            leave_note=True, on_progress=on_progress,
        )
        with _relocation_lock:
            _relocation_state["dst"] = report["dst"]
            _relocation_state["done"] = True
    except MigrationError as e:
        with _relocation_lock:
            _relocation_state["error"] = str(e)
    except Exception as e:
        with _relocation_lock:
            _relocation_state["error"] = str(e)
    finally:
        with _relocation_lock:
            _relocation_state["in_progress"] = False


@app.route('/api/relocation/status', methods=['GET'])
def relocation_status():
    """Availability + live progress for the app-folder-to-home relocation."""
    with _relocation_lock:
        state = dict(_relocation_state)
    return jsonify({
        "available": _relocation_available(),
        "in_progress": state["in_progress"],
        "done": state["done"],
        "error": state["error"],
        "done_bytes": state["done_bytes"],
        "total_bytes": state["total_bytes"],
        "dst": state["dst"],
    })


@app.route('/api/relocation/decline', methods=['POST'])
def relocation_decline():
    """Permanently dismiss the relocation prompt for this install."""
    try:
        config.setdefault("storage", {})["relocation_declined"] = True
        save_config(config)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/relocate', methods=['POST'])
def relocate():
    """Start the background copy of this legacy install into its Mneme home."""
    # The UI calls this only after checking relocation/status, but keep the
    # endpoint safe on its own too. Without this guard a stale tab or manual
    # request could attempt a second copy after the new home has become live.
    if not _relocation_available():
        return jsonify({"error": "Relocation is not available for this install"}), 409

    with _relocation_lock:
        if _relocation_state["in_progress"]:
            return jsonify({"error": "Relocation already in progress"}), 409
        _relocation_state["in_progress"] = True
        _relocation_state["done"] = False
        _relocation_state["error"] = None
        _relocation_state["done_bytes"] = 0
        _relocation_state["total_bytes"] = 0
        _relocation_state["dst"] = ""

    threading.Thread(target=_run_relocation, daemon=True).start()
    return jsonify({"started": True})


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
        system_cfg = config.get('system', {})

        # Mask API keys — show last 4 chars only
        api_keys = config.get('api_keys', {})
        def mask_key(key):
            if not key:
                return ''
            return '••••••••' + key[-4:] if len(key) > 4 else '••••'

        configured_default_model = model_cfg.get('default', 'claude-sonnet-4-6')
        if manager:
            active_model = manager.model
        elif model_cfg.get('use_testing', False):
            active_model = model_cfg.get('testing', 'claude-haiku-4-5')
        else:
            active_model = configured_default_model
        model_caps = get_model_capabilities(active_model)

        return jsonify({
            # Identity
            'user_name': identity_cfg.get('user_name', ''),
            'instance_name': identity_cfg.get('instance_name', ''),
            # API keys (masked)
            'anthropic_key_masked': mask_key(api_keys.get('anthropic', '')),
            'openai_key_masked': mask_key(api_keys.get('openai', '')),
            'elevenlabs_key_masked': mask_key(api_keys.get('elevenlabs', '')),
            # Model
            'model_default': configured_default_model,
            'active_model': active_model,
            'use_testing_model': model_cfg.get('use_testing', False),
            'temperature': model_cfg.get('temperature', 1.0),
            'active_context_window_tokens': model_caps.context_window_tokens,
            'active_supports_1m_context': model_caps.supports_1m_context,
            'max_recent_messages_tokens': max_recent_window_for_model(active_model),
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
            # System
            'keep_pc_awake': system_cfg.get('keep_pc_awake', False),
            'keep_pc_awake_supported': power_management.is_supported(),
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
            if not 1024 <= val <= 15000:
                return jsonify({"error": "thinking_budget must be between 1024 and 15000"}), 400
            config.setdefault('thinking', {})['budget_tokens'] = val
            updated['thinking_budget'] = val

        # --- Context ---
        if 'recent_messages_tokens' in data:
            val = int(data['recent_messages_tokens'])
            model_cfg_for_limit = config.get('model', {})
            active_model_for_limit = (
                model_cfg_for_limit.get('testing', 'claude-haiku-4-5')
                if model_cfg_for_limit.get('use_testing', False)
                else model_cfg_for_limit.get('default', 'claude-sonnet-4-6')
            )
            max_recent = max_recent_window_for_model(active_model_for_limit)
            if not 10000 <= val <= max_recent:
                return jsonify({"error": f"recent_messages_tokens must be between 10000 and {max_recent} for {active_model_for_limit}"}), 400
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

        # --- System (global, not per-profile) ---
        if 'keep_pc_awake' in data:
            val = bool(data['keep_pc_awake'])
            config.setdefault('system', {})['keep_pc_awake'] = val
            updated['keep_pc_awake'] = val
            # Apply immediately — no restart required.
            try:
                power_management.apply_setting(val)
            except Exception as e:
                print(f"[PowerManagement] Failed to apply keep_pc_awake setting: {e}")

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
            manager._refresh_active_prompt_window(ca.recent_budget)

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


SYSTEM_INSTRUCTIONS_MAX_BYTES = 102400


@app.route('/api/system-instructions', methods=['GET'])
def get_system_instructions_route():
    """Return the raw content of the effective system-instructions file."""
    try:
        path, source = resolve_instructions_path(config)

        template_path = Path(__file__).parent.parent.parent / "system_instructions.example.txt"
        try:
            template_text = template_path.read_text(encoding="utf-8")
        except OSError:
            template_text = ""

        if path.exists():
            content = path.read_text(encoding="utf-8")
        else:
            content = template_text
            source = "template"

        return jsonify({
            "content": content,
            "source": source,
            "template": template_text,
            "max_bytes": SYSTEM_INSTRUCTIONS_MAX_BYTES,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system-instructions', methods=['POST'])
def update_system_instructions_route():
    """Write the raw content to the active profile's system_instructions.txt.

    Writes atomically (temp file + os.replace) so a crash mid-write can never
    truncate the live prompt.
    """
    try:
        data = request.get_json()
        if not data or 'content' not in data or data['content'] is None:
            return jsonify({"error": "Instructions cannot be empty"}), 400

        content = data['content']
        if not isinstance(content, str) or not content.strip():
            return jsonify({"error": "Instructions cannot be empty"}), 400

        if len(content.encode("utf-8")) > SYSTEM_INSTRUCTIONS_MAX_BYTES:
            return jsonify({"error": "Instructions too large (max 100 KB)"}), 400

        target_dir = Path(config["storage"]["database_path"]).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "system_instructions.txt"

        tmp_path = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=str(target_dir), prefix="system_instructions.", suffix=".tmp")
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(target))
            tmp_path = None
        except OSError as e:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return jsonify({"error": str(e)}), 500

        return jsonify({"success": True, "source": "profile"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _apply_provider_threshold(provider):
    """
    Persist the correct per-provider similarity_threshold after a verified
    migration (0.50 local / 0.25 openai) and sync the live context assembler.

    `retrieval` is a global (not profile-scoped) config section, so this writes
    to the root config.json via save_config, matching how the settings endpoint
    handles retrieval.similarity_threshold.
    """
    val = PROVIDER_SIMILARITY_THRESHOLD.get(provider, 0.25)
    config.setdefault('retrieval', {})['similarity_threshold'] = val
    save_config(config)
    if manager and getattr(manager, 'context_assembler', None):
        manager.context_assembler.similarity_threshold = val
    print(f"  Migration: similarity_threshold set to {val} for provider '{provider}'")


def _ensure_local_embedding_provider():
    """
    Switch the running app to local embeddings before starting migration.

    The migration worker re-embeds to the *current* provider/model. The UI
    button promises "migrate to on-device embeddings", so existing OpenAI users
    must be switched first.
    """
    global config, manager

    retrieval = config.setdefault('retrieval', {})
    current_provider = retrieval.get('embedding_provider', 'openai')
    current_model = getattr(getattr(manager, 'embedder', None), 'model', '')
    if current_provider == 'local' and current_model == 'bge-small-en-v1.5':
        return False

    previous_provider = current_provider
    retrieval['embedding_provider'] = 'local'
    try:
        new_embedder = create_embedding_generator(config)
    except Exception:
        retrieval['embedding_provider'] = previous_provider
        raise

    if not save_config(config):
        retrieval['embedding_provider'] = previous_provider
        raise RuntimeError("Could not save embedding provider change")

    manager.embedder = new_embedder
    manager.context_assembler.embedder = new_embedder
    manager.background_queue.embedder = new_embedder
    manager.command_handler.embedder = new_embedder
    print("  Migration: switched embedding provider to local")
    return True


@app.route('/api/embeddings/migration-status', methods=['GET'])
def embeddings_migration_status():
    """Detection + live job progress for the embedding migration/backfill."""
    try:
        if not manager:
            return jsonify({"error": "System not ready"}), 503
        status = migration_manager.build_status(manager.db, manager.embedder, config)
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/embeddings/migrate', methods=['POST'])
def embeddings_migrate():
    """
    Start the embedding migration in the background.

    Creates a timestamped backup FIRST (in the worker), then re-embeds every
    message whose stored embedding is missing or from a different model, and on
    a fully verified run persists the correct per-provider similarity_threshold.
    Idempotent/resumable: calling again picks up any remaining rows.
    """
    try:
        if not manager:
            return jsonify({"error": "System not ready"}), 503

        switched_provider = _ensure_local_embedding_provider()

        storage_cfg = config.get("storage", {})
        system_cfg = config.get("system", {})
        backup_dir = get_backup_path(config)
        cloud_dir = storage_cfg.get("cloud_backup_path") or None
        keep_count = system_cfg.get("backup_keep_count", 3)

        result = migration_manager.start(
            manager.db, manager.embedder, config,
            backup_dir=backup_dir, cloud_backup_dir=cloud_dir, keep_count=keep_count,
            on_complete=_apply_provider_threshold,
        )
        status = migration_manager.build_status(manager.db, manager.embedder, config)
        status["started"] = result["started"]
        status["reason"] = result["reason"]
        status["switched_provider"] = switched_provider
        return jsonify(status)
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
        # Route all deletion through the database lifecycle method so dependent
        # retrieval logs, embeddings, and future message-owned data are cleaned.
        if db.get_message(message_id):
            db.delete_message(message_id)
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


def _run_startup_backup():
    """Create a database backup on server startup."""
    try:
        set_startup_status(background_work=["Creating startup backup"])
        storage_cfg = config.get("storage", {})
        system_cfg = config.get("system", {})
        backup_dir = get_backup_path(config)
        cloud_dir = storage_cfg.get("cloud_backup_path") or None
        keep_count = system_cfg.get("backup_keep_count", 3)
        result = db.create_backup(backup_dir, cloud_backup_dir=cloud_dir, keep_count=keep_count)
        if result:
            print(f"  Auto-backup: {Path(result).name}")
        else:
            print("  Auto-backup: failed (check logs)")
    except Exception as e:
        print(f"  Auto-backup error: {e}")
    finally:
        set_startup_status(background_work=[])


def _run_startup_entity_backfill():
    """Background thread: process messages that missed entity assignment last session."""
    try:
        pending = db.get_unchecked_message_count()
        if pending:
            set_startup_status(background_work=[f"Assigning entities for {pending} missed messages"])
        processed = manager.background_queue.run_startup_backfill()
        if processed:
            print(f"✓ Startup backfill complete ({processed} messages assigned)")
    except Exception as e:
        count = db.get_unchecked_message_count()
        print(f"⚠ Startup entity backfill failed ({count} messages still pending): {e}")
        print(f"  When credits are available, run: python scripts/backfill_message_entities.py")
    finally:
        set_startup_status(background_work=[])


def _run_normal_startup():
    """Initialize Mneme, then launch non-blocking startup maintenance."""
    try:
        init_system()

        # Auto-backup on startup
        if config.get("system", {}).get("enable_auto_backup", False):
            _run_startup_backup()

        # Backfill any messages that missed entity assignment last session (in background)
        threading.Thread(target=_run_startup_entity_backfill, daemon=True).start()

    except Exception:
        # init_system already recorded the failure for /api/startup/status.
        return


def main():
    """Start the Flask server."""
    global setup_mode

    if needs_setup():
        # Boot in setup mode — serve setup UI only
        setup_mode = True
        set_startup_status(
            state="ready",
            phase="Setup required",
            detail="Mneme is ready to run the first-time setup wizard.",
        )
        print("=" * 70)
        print("  MNEME — FIRST-TIME SETUP")
        print("=" * 70)
        print()
        print("  No configuration found. Starting setup wizard...")
        print()
        port = 8080
    else:
        try:
            port = load_config().get("system", {}).get("server_port", 8080)
        except Exception:
            port = 8080

        threading.Thread(target=_run_normal_startup, daemon=True).start()

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

    # Release the keep-awake lock on clean shutdown.
    atexit.register(power_management.release)

    # Start server
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == "__main__":
    main()
