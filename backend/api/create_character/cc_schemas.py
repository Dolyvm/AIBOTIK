from typing import Optional, Literal
from pydantic import BaseModel


class CreateCharacterRequest(BaseModel):
    name: str
    short_description: Optional[str] = None
    description: str
    personality: str
    scenario: str
    first_message: str
    heat_level: int = 0
    alternate_greetings: list[str] = []
    gender: Literal["female", "male"] = "female"
    model_type: Literal["anime", "real"] = "anime"
    appearance: Optional[str] = None
    visual_body: Optional[str] = None
    visual_face: Optional[str] = None
    visual_default_outfit: Optional[str] = None
    visual_style_tags: Optional[str] = None
    wardrobe: dict[str, str] = {}
    avatar_url: Optional[str] = None
    tags: list[str] = []
