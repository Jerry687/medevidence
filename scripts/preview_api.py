"""API preview only: research requests explicitly return unavailable."""

from fastapi import FastAPI

from medevidence.api.research_routes import create_research_router

app = FastAPI(title="MedEvidence development preview — research runtime not configured")
app.include_router(create_research_router(None))
