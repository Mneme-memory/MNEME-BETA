# Scripts — Reference

Scripts are standalone utilities. Run from the repo root: `python scripts/<name>.py`.

Most scripts require the database and config to be present (`data/<profile>/memory.db`, `config.json`).

Single-use scripts (migrations, backfills, one-off fixes, abandoned graph features) live in `scripts/internal/` and are gitignored.

---

## Essential

| Script | Purpose |
|--------|---------|
| `verify_setup.py` | Check that config, DB, and API keys are all in order |
| `chat.py` | Terminal chat interface — quickest way to test backend changes |
| `init_db.py` | Initialize a fresh database |
| `tray.py` | System tray launcher for Mneme |

---

## Entity Management

| Script | Purpose |
|--------|---------|
| `list_entities.py` | List all entities in the database |
| `manage_entities.py` | View, edit, merge entities interactively |
| `manage_aliases.py` | View, add, remove, split entity aliases |
| `regenerate_entity_summaries.py` | Regenerate botched entity summaries (scan for refusals, fix specific months/entities) |

---

## Diagnostics

| Script | Purpose |
|--------|---------|
| `diagnose_database.py` | Check database health (FK constraints, locks, integrity) |
| `diagnose_context.py` | Inspect what's in conversation history and how it's processed |
