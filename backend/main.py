"""Archer Backend Package"""

# Compatibility entrypoint for both:
# - python -m uvicorn backend.main:app (from repo root)
# - uvicorn main:app (from Docker)
try:
    from .archer.app import app
except ImportError:
    from archer.app import app

__all__ = ["app"]
