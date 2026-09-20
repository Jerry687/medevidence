"""Local API entry point; all execution is explicit and service-backed."""

from __future__ import annotations

from fastapi import FastAPI

from medevidence.api.research_routes import create_research_router
from medevidence.tools.research_application import ResearchApplicationPort


def create_local_research_app(application: ResearchApplicationPort) -> FastAPI:
    """Expose the full research application while preserving its approval boundary."""
    app = FastAPI(
        title="MedEvidence local research",
        version="1.0.0-local",
        description="Public-source research assistance; explicit human approval before export.",
        docs_url=None,
        redoc_url=None,
    )
    app.include_router(create_research_router(application))
    return app


def main() -> None:
    """Start on loopback only, with no credential or source fallback."""
    import uvicorn

    from medevidence.infrastructure.local_runtime_settings import LocalRuntimeSettings
    from medevidence.local_runtime import open_local_application

    settings = LocalRuntimeSettings.from_env()
    with open_local_application(settings) as service:
        uvicorn.run(create_local_research_app(service), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
