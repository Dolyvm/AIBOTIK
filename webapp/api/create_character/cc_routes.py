from fastapi import APIRouter

router = APIRouter(prefix="/api/create_character", tags=["create_character"])


@router.post("")
async def create_character_endpoint():
    ...