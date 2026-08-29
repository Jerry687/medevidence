"""Infrastructure adapters selected only by the application composition root."""

from .langgraph_checkpoint import (
    LANGGRAPH_CHECKPOINT_SCHEMA,
    OFFICIAL_CHECKPOINT_TABLES,
    LangGraphCheckpointInfrastructureError,
    create_strict_checkpoint_serializer,
    postgres_checkpoint_saver,
    setup_postgres_checkpointing,
)

__all__ = [
    "LANGGRAPH_CHECKPOINT_SCHEMA",
    "OFFICIAL_CHECKPOINT_TABLES",
    "LangGraphCheckpointInfrastructureError",
    "create_strict_checkpoint_serializer",
    "postgres_checkpoint_saver",
    "setup_postgres_checkpointing",
]
