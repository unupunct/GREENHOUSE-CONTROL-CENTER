"""Safety status now lives in services/commissioning.py (database-backed
checklist). This module is kept as the import point for the check list."""

from app.services.commissioning import CHECKS

REQUIRED_CHECKS = [c.id for c in CHECKS]
