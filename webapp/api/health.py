"""
webapp/api/health.py - Health check endpoint для Railway/мониторинга
"""
from fastapi import APIRouter
from datetime import datetime

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check():
    """
    Health check endpoint.
    Railway использует его для проверки что сервис жив.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "aibotik-webapp"
    }


@router.get("/api/health/ready")
async def readiness_check():
    """
    Readiness check
    """
    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat()
    }
