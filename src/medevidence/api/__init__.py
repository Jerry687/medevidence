"""Versioned FastAPI transport for the bounded M1A PubMed workflow."""

from .app import ApiDependencies, create_app

__all__ = ["ApiDependencies", "create_app"]
