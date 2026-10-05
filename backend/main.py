from app import app
from evidence.runtime import SignalEvidenceMiddleware, router as evidence_router

# Keep the legacy application untouched. This wrapper adds the unified evidence
# contract at deployment time and records eligible /v1/search picks before they
# leave the server.
app.add_middleware(SignalEvidenceMiddleware)
app.include_router(evidence_router)
