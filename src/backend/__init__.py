"""
Mneme Backend Package

Contains core functionality:

Phase 1:
- Database operations
- Configuration management
- Schema definitions
- Command-line interface

Phase 2:
- Embedding generation (OpenAI)
- Semantic search and retrieval

Phase 3:
- Conversation management
- Context assembly (token-based)
- Command system (@remember, @recall, etc.)
- Background processing (auto-tagging, embeddings)
"""

# Phase 1 modules
from .database import Database, DatabaseError
from .config import load_config, ConfigError
from .schema import create_database_schema, verify_schema

# Phase 2 modules
from .embeddings import (
    EmbeddingGenerator,
    LocalEmbeddingGenerator,
    EmbeddingError,
    create_embedding_generator,
    embedding_to_json,
    embedding_from_json,
)
from .retrieval import MemoryRetriever, RetrievalError

# Phase 3 modules
from .conversation import ConversationManager, ConversationError
from .context import ContextAssembler, ContextError
from .commands import CommandHandler, CommandError
from .background import BackgroundQueue, BackgroundError

__all__ = [
    # Phase 1
    "Database",
    "DatabaseError",
    "load_config",
    "ConfigError",
    "create_database_schema",
    "verify_schema",
    # Phase 2
    "EmbeddingGenerator",
    "LocalEmbeddingGenerator",
    "EmbeddingError",
    "create_embedding_generator",
    "embedding_to_json",
    "embedding_from_json",
    "MemoryRetriever",
    "RetrievalError",
    # Phase 3
    "ConversationManager",
    "ConversationError",
    "ContextAssembler",
    "ContextError",
    "CommandHandler",
    "CommandError",
    "BackgroundQueue",
    "BackgroundError",
]
