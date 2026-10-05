from app import app
from evidence.runtime import SignalEvidenceMiddleware, router as evidence_router

# Deployment entrypoint for the legacy runtime plus the unified evidence layer.
# A project-specific module name avoids collisions with generic `main` modules in
# test runners and deployment environments.
app.add_middleware(SignalEvidenceMiddleware)
app.include_router(evidence_router)
