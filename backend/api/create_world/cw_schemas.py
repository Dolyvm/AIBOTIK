from typing import Optional
from pydantic import BaseModel


class AlternateScenario(BaseModel):
    title: str = ""
    intro: str = ""
    gm_instructions: str = ""


class CreateWorldRequest(BaseModel):
    name: str
    short_description: Optional[str] = None
    description: str
    gm_instructions: Optional[str] = ""
    intro_message: str
    alternate_scenarios: list[AlternateScenario] = []
    cover_image_url: Optional[str] = None
    tags: list[str] = []
