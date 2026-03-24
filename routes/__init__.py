from .patients import router as patients_router
from .sessions import router as sessions_router
from .analytics import router as analytics_router
from .ai import router as ai_router

__all__ = ["patients_router", "sessions_router", "analytics_router", "ai_router"]
