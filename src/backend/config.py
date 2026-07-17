"""
Configuration Management for Mneme Memory System

Loads, validates, and migrates configuration settings.
Handles backward compatibility with old phase-based config format.

USAGE:
    from config import load_config
    config = load_config()
    api_key = config["api_keys"]["anthropic"]
"""

import json
import os
import sys
from pathlib import Path

try:
    from src.backend.model_capabilities import max_recent_window_for_model
except ModuleNotFoundError:
    from model_capabilities import max_recent_window_for_model


class ConfigError(Exception):
    """Custom exception for configuration errors."""
    pass


def get_project_root():
    """Finds the root directory of the Mneme project (the app code)."""
    return Path(__file__).parent.parent.parent


def get_default_home():
    """
    The platform-default Mneme home, ignoring any legacy fallback.

    %LOCALAPPDATA%\\Mneme on Windows — deliberately NOT Roaming/Documents/
    OneDrive territory, so live SQLite files are never cloud-synced and
    per-user writability keeps the @run sandbox ACL grants working.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "Mneme"


def get_mneme_home():
    """
    Resolve the Mneme home directory — where user state lives.

    User state = config.json, data/, and the live system_instructions.txt.
    The app folder holds only code and *.example.* templates.

    Resolution order:
      1. MNEME_HOME environment variable (explicit override)
      2. %LOCALAPPDATA%/Mneme, if it already holds a config.json
      3. The app folder, if it holds a config.json (legacy layout)
      4. %LOCALAPPDATA%/Mneme (default for fresh installs)

    Re-evaluated on every call (no caching) so tests and the relocation
    flow always see the current state of the world.
    """
    env_home = os.environ.get("MNEME_HOME")
    if env_home:
        return Path(env_home)

    default_home = get_default_home()
    if (default_home / "config.json").exists():
        return default_home

    legacy_root = get_project_root()
    if (legacy_root / "config.json").exists():
        return legacy_root

    return default_home


def load_config(config_path=None):
    """
    Loads configuration from config.json file.
    Automatically migrates old phase-based configs to the new format.
    """
    if config_path is None:
        config_path = get_mneme_home() / "config.json"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise ConfigError(
            f"Configuration file not found at: {config_path}\n\n"
            f"SETUP REQUIRED:\n"
            f"1. Copy 'config.example.json' to 'config.json'\n"
            f"2. Edit config.json and add your API keys\n"
            f"3. Run this script again"
        )

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"Configuration file has invalid JSON syntax:\n"
            f"Error: {e}\n\n"
            f"Check {config_path} for syntax errors (missing commas, brackets, etc.)"
        )
    except Exception as e:
        raise ConfigError(f"Could not read configuration file: {e}")

    # Migrate old format if detected
    if _is_legacy_config(config):
        config = migrate_legacy_config(config)

    validate_config(config)
    config = resolve_paths(config)
    config = load_profile_config(config)
    config = normalize_context_window(config)

    return config


def _is_legacy_config(config):
    """Detect old phase-based config format."""
    return any(key in config for key in [
        "phase2", "phase3", "phase4", "phase5_graph",
        "phase6_concepts", "phase7_attachments", "phase8_summaries",
        "phase9_tts", "phase9_timeline", "phase10_thinking", "phase11_notes"
    ]) or ("api" in config and "anthropic_key" in config.get("api", {}))


def _deep_get(d, *keys, default=None):
    """Safely navigate nested dicts."""
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key, default)
        else:
            return default
    return d


def migrate_legacy_config(config):
    """
    Migrates old phase-based config to new flat structure.
    Preserves any new-format keys that already exist.
    """
    new = {}

    # --- api_keys ---
    old_api = config.get("api", {})
    new["api_keys"] = {
        "anthropic": old_api.get("anthropic_key", ""),
        "openai": old_api.get("openai_key", ""),
        "elevenlabs": old_api.get("elevenlabs_key", ""),
    }

    # --- storage (unchanged) ---
    new["storage"] = config.get("storage", {})

    # --- identity (was buried in phase9_timeline) ---
    timeline = config.get("phase9_timeline", {})
    new["identity"] = {
        "user_name": timeline.get("user_name", ""),
        "instance_name": timeline.get("instance_name", ""),
    }

    # --- model (was phase3.conversation) ---
    conv = _deep_get(config, "phase3", "conversation", default={})
    new["model"] = {
        "default": conv.get("model_production", "claude-sonnet-4-6"),
        "testing": conv.get("model_testing", "claude-haiku-4-5"),
        "use_testing": conv.get("use_testing_model", False),
        "provider": conv.get("provider", "anthropic"),
        "temperature": conv.get("temperature", 1.0),
        "max_tokens": conv.get("max_tokens", 60000),
        "streaming": conv.get("enable_streaming", True),
    }

    # --- thinking (was phase10_thinking) ---
    think = config.get("phase10_thinking", {})
    new["thinking"] = {
        "enabled": think.get("enabled", True),
        "budget_tokens": think.get("budget_tokens", 10000),
        "show_in_ui": think.get("show_thinking", True),
    }

    # --- context (was phase3.context, minus dead max_tokens cap) ---
    ctx = _deep_get(config, "phase3", "context", default={})
    new["context"] = {
        "recent_messages_tokens": ctx.get("recent_context_tokens", 70000),
        "memory_tokens": ctx.get("memory_context_tokens", 15000),
        "duplicate_window_minutes": ctx.get("duplicate_window_minutes", 30),
    }

    # --- retrieval (merged from phase2 + performance + memory + phase3.background) ---
    emb = _deep_get(config, "phase2", "embeddings", default={})
    ret = _deep_get(config, "phase2", "retrieval", default={})
    perf = config.get("performance", {})
    mem = config.get("memory", {})
    bg = _deep_get(config, "phase3", "background", default={})
    imp = _deep_get(config, "phase2", "importance", default={})
    new["retrieval"] = {
        "embeddings_model": emb.get("model", "text-embedding-3-small"),
        "embeddings_dimensions": emb.get("dimensions", 1536),
        "max_results": perf.get("max_retrieval_results", 20),
        "similarity_threshold": ret.get("similarity_threshold", 0.25),
        "semantic_weight": ret.get("semantic_weight", 0.4),
        "importance_weight": ret.get("importance_weight", 0.4),
        "recency_weight": ret.get("recency_weight", 0.2),
        "deep_archive_age_days": mem.get("deep_archive_age_days", 180),
        "embedding_immediate": bg.get("embedding_immediate", True),
    }
    if "rubric" in imp:
        new["retrieval"]["importance_rubric"] = imp["rubric"]

    # --- caching (was phase4.caching) ---
    cache = _deep_get(config, "phase4", "caching", default={})
    new["caching"] = {
        "enabled": cache.get("enabled", True),
        "extended_ttl": cache.get("use_extended_ttl", True),
        "adaptive_threshold_minutes": cache.get("adaptive_threshold_minutes", 60),
        "transition_interval_minutes": cache.get("transition_interval_minutes", 55),
        "auto_rebalance_on_startup": cache.get("auto_rebalance_on_startup", True),
        "track_metrics": cache.get("track_cache_metrics", True),
    }
    if "force_caching" in cache:
        new["caching"]["force_caching"] = cache["force_caching"]

    # --- features ---
    features = {}

    # concepts (was phase6_concepts)
    c6 = config.get("phase6_concepts", {})
    features["concepts"] = {
        "enabled": c6.get("enabled", False),
        "max_tokens": c6.get("max_tokens", 1000),
        "message_window": c6.get("message_window", 5),
        "max_concepts_retrieved": c6.get("max_concepts_retrieved", 2),
        "auto_extract": c6.get("auto_extract_enabled", True),
        "auto_extract_frequency": c6.get("auto_extract_frequency", 40),
        "auto_extract_min_words": c6.get("auto_extract_min_words", 100),
        "auto_extract_max_words": c6.get("auto_extract_max_words", 500),
    }

    # attachments (was phase7_attachments)
    c7 = config.get("phase7_attachments", {})
    c7_storage = c7.get("storage", {})
    features["attachments"] = {
        "enabled": c7.get("enabled", False),
        "max_tokens": c7.get("max_tokens", 1500),
        "max_files_displayed": c7.get("max_files_displayed", 5),
        "auto_retrieve_threshold": c7.get("auto_retrieve_threshold", 0.35),
        "describe_reminder": c7.get("describe_reminder_enabled", True),
        "storage": {
            "path": c7_storage.get("attachments_path", "./data/{profile}/attachments/"),
            "max_file_size_mb": c7_storage.get("max_file_size_mb", 25),
            "image_max_dimension": c7_storage.get("image_optimize_max_dimension", 1568),
            "thumbnail_size": c7_storage.get("thumbnail_size", 300),
        },
        "supported_types": c7.get("supported_types", {}),
    }

    # entity_summaries (merged from phase5_graph + phase8_summaries)
    c5 = config.get("phase5_graph", {})
    c8 = config.get("phase8_summaries", {})
    features["entity_summaries"] = {
        "enabled": c8.get("enabled", False) or c5.get("enabled", False),
        "auto_extract_entities": c5.get("auto_extract", True),
        "max_entities_per_retrieval": c8.get("max_entities_per_retrieval", 3),
        "max_tokens": c8.get("max_summary_tokens", 5000),
        "incremental_update_limit": c8.get("incremental_update_limit", 10),
        "assignment_batch_size": c8.get("entity_assignment_batch_size", 30),
    }

    # tts (was phase9_tts)
    c9t = config.get("phase9_tts", {})
    features["tts"] = {
        "enabled": c9t.get("enabled", False),
        "model_id": c9t.get("model_id", "eleven_flash_v2_5"),
        "voice_id": c9t.get("voice_id", ""),
        "output_format": c9t.get("output_format", "mp3_44100_128"),
        "cache_enabled": c9t.get("cache_enabled", True),
    }

    # timeline (was phase9_timeline, minus identity fields)
    features["timeline"] = {
        "enabled": timeline.get("enabled", False),
        "days_to_show": timeline.get("days_to_show", 7),
        "max_tokens_per_day": timeline.get("max_tokens_per_day", 400),
        "summary_model": timeline.get("summary_model", "claude-haiku-4-5"),
        "temperature": timeline.get("generation_temperature", 0.3),
    }

    # notes (was phase11_notes)
    c11 = config.get("phase11_notes", {})
    features["notes"] = {
        "enabled": c11.get("enabled", False),
        "max_tokens": c11.get("max_tokens", 5000),
        "cleanup_threshold_pct": c11.get("cleanup_threshold_pct", 80),
        "cleanup_interval_messages": c11.get("cleanup_interval_messages", 50),
    }

    new["features"] = features

    # --- commands (was phase3.commands) ---
    cmds = _deep_get(config, "phase3", "commands", default={})
    # Migrate old parameter names in autonomy list
    autonomy_renames = {
        "retrieval_threshold": "similarity_threshold",
        "recent_context_tokens": "recent_messages_tokens",
        "memory_context_tokens": "memory_tokens",
    }
    old_autonomy = cmds.get("instance_autonomy", [
        "similarity_threshold", "semantic_weight", "importance_weight",
        "recency_weight", "recent_messages_tokens", "memory_tokens", "temperature"
    ])
    new["commands"] = {
        "max_iterations": cmds.get("max_instance_iterations", 6),
        "instance_autonomy": [autonomy_renames.get(p, p) for p in old_autonomy],
    }

    # --- costs, security, system (mostly unchanged) ---
    new["costs"] = config.get("costs", {})
    new["security"] = config.get("security", {})
    new["system"] = config.get("system", {})

    # Move server port to system if it was in phase3.server
    server_port = _deep_get(config, "phase3", "server", "port", default=None)
    if server_port is not None:
        new["system"]["server_port"] = server_port

    return new


def validate_config(config):
    """
    Validates required configuration settings.
    Works with both new and migrated configs.
    """
    # Check required sections
    required_sections = ["api_keys", "storage"]
    for section in required_sections:
        if section not in config:
            raise ConfigError(f"Missing required section in config: [{section}]")

    # Validate API key
    api_keys = config["api_keys"]
    anthropic = api_keys.get("anthropic", "")
    if not anthropic or anthropic == "YOUR_ANTHROPIC_API_KEY_HERE":
        raise ConfigError(
            "Anthropic API key not configured.\n\n"
            "SETUP REQUIRED:\n"
            "1. Get an API key from: https://console.anthropic.com/\n"
            "2. Open config.json\n"
            "3. Replace 'YOUR_ANTHROPIC_API_KEY_HERE' with your actual key\n"
            "4. Save the file and run this script again"
        )

    # Validate storage paths
    if "database_path" not in config["storage"]:
        raise ConfigError("Missing 'database_path' in [storage] section")
    if "backup_path" not in config["storage"]:
        raise ConfigError("Missing 'backup_path' in [storage] section")

    # Validate numeric ranges
    deep_archive = config.get("retrieval", {}).get("deep_archive_age_days")
    if deep_archive is not None:
        if not isinstance(deep_archive, (int, float)) or deep_archive < 30 or deep_archive > 3650:
            raise ConfigError("retrieval.deep_archive_age_days must be between 30 and 3650")

    max_results = config.get("retrieval", {}).get("max_results")
    if max_results is not None:
        if not isinstance(max_results, (int, float)) or max_results < 1 or max_results > 1000:
            raise ConfigError("retrieval.max_results must be between 1 and 1000")

    return True


def resolve_paths(config):
    """
    Converts relative paths to absolute paths.
    Handles {profile} substitution.

    Relative paths resolve against the Mneme home (user-state root),
    not the app folder. For legacy installs the two are the same dir.
    """
    mneme_home = get_mneme_home()
    active_profile = config.get("storage", {}).get("active_profile", "")

    # Resolve database path
    db_path = config["storage"]["database_path"]
    if "{profile}" in db_path and active_profile:
        config["storage"]["database_path_template"] = db_path
        db_path = db_path.replace("{profile}", active_profile)
        config["storage"]["database_path"] = db_path
    if not os.path.isabs(db_path):
        db_path = str(mneme_home / db_path)
        config["storage"]["database_path"] = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Resolve backup path
    backup_path = config["storage"]["backup_path"]
    if "{profile}" in backup_path and active_profile:
        config["storage"]["backup_path_template"] = backup_path
        backup_path = backup_path.replace("{profile}", active_profile)
        config["storage"]["backup_path"] = backup_path
    if not os.path.isabs(backup_path):
        backup_path = str(mneme_home / backup_path)
        config["storage"]["backup_path"] = backup_path
    Path(backup_path).mkdir(parents=True, exist_ok=True)

    # Resolve optional cloud/off-device backup path
    cloud_backup_path = config["storage"].get("cloud_backup_path", "")
    if cloud_backup_path:
        if "{profile}" in cloud_backup_path and active_profile:
            config["storage"]["cloud_backup_path_template"] = cloud_backup_path
            cloud_backup_path = cloud_backup_path.replace("{profile}", active_profile)
            config["storage"]["cloud_backup_path"] = cloud_backup_path
        if not os.path.isabs(cloud_backup_path):
            cloud_backup_path = str(mneme_home / cloud_backup_path)
            config["storage"]["cloud_backup_path"] = cloud_backup_path
        Path(cloud_backup_path).mkdir(parents=True, exist_ok=True)

    return config


def get_database_path(config):
    """Helper to get the database path from config."""
    return config["storage"]["database_path"]


def get_backup_path(config):
    """Helper to get the backup directory path from config."""
    return config["storage"]["backup_path"]


def normalize_context_window(config):
    """
    Clamp saved recent-history windows to the selected model's supported range.

    This runs after profile overlays are applied so profile-scoped context
    settings cannot leave scripts, chat.py, or the server with an invalid
    conversation-window value.
    """
    context = config.setdefault("context", {})
    current = context.get("recent_messages_tokens", 50000)
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = 50000

    model_cfg = config.get("model", {})
    active_model = (
        model_cfg.get("testing", "claude-haiku-4-5")
        if model_cfg.get("use_testing", False)
        else model_cfg.get("default", "claude-sonnet-4-6")
    )
    max_recent = max_recent_window_for_model(active_model)
    context["recent_messages_tokens"] = min(max(current, 10_000), max_recent)
    return config


def save_config(config, config_path=None):
    """
    Saves configuration back to config.json file.
    Used by @config command and cost tracking.

    Restores path templates before writing so the saved file
    contains './data/{profile}/memory.db' instead of resolved absolute paths.
    """
    if config_path is None:
        config_path = get_mneme_home() / "config.json"
    else:
        config_path = Path(config_path)

    # Build a copy with templates restored (don't mutate the live config)
    import copy
    save_copy = copy.deepcopy(config)

    # Restore base (pre-overlay) values for profile-scoped keys
    # so profile overrides don't leak into the root config.json
    base = save_copy.pop("_base_config", None)
    if base:
        for key, value in base.items():
            save_copy[key] = value

    # Restore path templates if they were saved during resolve_paths()
    storage = save_copy.get("storage", {})
    if "database_path_template" in storage:
        storage["database_path"] = storage.pop("database_path_template")
    if "backup_path_template" in storage:
        storage["backup_path"] = storage.pop("backup_path_template")
    if "cloud_backup_path_template" in storage:
        storage["cloud_backup_path"] = storage.pop("cloud_backup_path_template")

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(save_copy, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving configuration: {e}")
        return False


# =============================================================================
# PROFILE CONFIG OVERLAY
# =============================================================================

# Keys that can be overridden per profile (everything else stays global)
PROFILE_SCOPED_KEYS = {"identity", "model", "thinking", "context", "features"}


def load_profile_config(config):
    """
    Load and merge per-profile config overlay on top of global config.

    Checks for data/{profile}/config.json. If it exists, deep-merges
    profile-scoped keys on top of the global config (profile wins).

    Args:
        config: The global config dict (already resolved)

    Returns:
        The config dict with profile overrides applied
    """
    db_path = config.get("storage", {}).get("database_path", "")
    if not db_path:
        return config

    profile_config_path = Path(db_path).parent / "config.json"
    if not profile_config_path.exists():
        return config

    try:
        with open(profile_config_path, 'r', encoding='utf-8') as f:
            profile_overrides = json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"⚠ Could not load profile config {profile_config_path}: {e}")
        return config

    # Snapshot base values before overlay so save_config can restore them
    import copy
    base_snapshot = {}
    for key in PROFILE_SCOPED_KEYS:
        if key in config:
            base_snapshot[key] = copy.deepcopy(config[key])

    config["_base_config"] = base_snapshot

    # Deep-merge only profile-scoped keys
    for key in PROFILE_SCOPED_KEYS:
        if key in profile_overrides:
            if isinstance(profile_overrides[key], dict) and isinstance(config.get(key), dict):
                config[key] = _deep_merge(config[key], profile_overrides[key])
            else:
                config[key] = profile_overrides[key]

    return config


def save_profile_config(config, overrides):
    """
    Save per-profile config overrides to data/{profile}/config.json.

    Args:
        config: The global config dict (for locating profile dir)
        overrides: Dict of profile-scoped settings to save
    """
    db_path = config.get("storage", {}).get("database_path", "")
    if not db_path:
        return False

    profile_config_path = Path(db_path).parent / "config.json"

    # Only save profile-scoped keys
    filtered = {k: v for k, v in overrides.items() if k in PROFILE_SCOPED_KEYS}

    try:
        with open(profile_config_path, 'w', encoding='utf-8') as f:
            json.dump(filtered, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving profile config: {e}")
        return False


def _deep_merge(base, override):
    """Deep-merge override dict into base dict. Override wins on conflicts."""
    import copy
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def update_active_profile(config, profile_name):
    """
    Switch active profile in config, re-resolve paths, reload profile overlay.

    Args:
        config: The global config dict
        profile_name: Profile folder name to switch to

    Returns:
        Updated config dict
    """
    # Restore base config values before applying new profile overlay
    # (strip the previous profile's overrides)
    base = config.pop("_base_config", None)
    if base:
        for key, value in base.items():
            config[key] = value

    # Restore path templates before re-resolving
    storage = config.get("storage", {})
    if "database_path_template" in storage:
        storage["database_path"] = storage["database_path_template"]
    if "backup_path_template" in storage:
        storage["backup_path"] = storage["backup_path_template"]
    if "cloud_backup_path_template" in storage:
        storage["cloud_backup_path"] = storage["cloud_backup_path_template"]

    storage["active_profile"] = profile_name

    # Re-resolve paths with new profile
    config = resolve_paths(config)

    # Reload profile config overlay (snapshots base before applying)
    config = load_profile_config(config)
    config = normalize_context_window(config)

    return config


if __name__ == "__main__":
    print("Testing configuration system...\n")
    try:
        config = load_config()
        print("✓ Configuration loaded successfully")
        print(f"✓ Database path: {config['storage']['database_path']}")
        print(f"✓ OpenAI key configured: {bool(config['api_keys'].get('openai'))}")
        print("\nConfiguration is valid!")
    except ConfigError as e:
        print(f"✗ Configuration error:\n{e}")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
