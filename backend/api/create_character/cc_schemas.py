from typing import Any, Optional, Literal
from pydantic import BaseModel, model_validator


class BodyProfile(BaseModel):
    body_type: str = "proportional"
    height: Literal["short", "average", "tall"] = "average"
    breast_size: Optional[Literal["small", "medium", "large", "very_large"]] = None
    butt_size: Optional[Literal["compact", "medium", "rounded", "large"]] = None
    outfit_preset: Literal["casual", "elegant", "sporty", "home"] = "casual"

    @model_validator(mode="after")
    def normalize_empty_fields(self):
        if self.breast_size == "":
            self.breast_size = None
        if self.butt_size == "":
            self.butt_size = None
        return self


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
    model_type: Literal["anime", "real", "manhwa"] = "anime"
    appearance: Optional[str] = None
    visual_body: Optional[str] = None
    visual_face: Optional[str] = None
    visual_default_outfit: Optional[str] = None
    visual_style_tags: Optional[str] = None
    wardrobe: dict[str, str] = {}
    tag_overrides: dict[str, Any] = {}
    tags: list[str] = []
    is_public: bool = True
    avatar_draft_id: Optional[str] = None
    selected_avatar_url: Optional[str] = None
    custom_avatar: bool = False
    identity_consent_confirmed: bool = False
    body_profile: Optional[BodyProfile] = None


class CreateCharacterAvatarRequest(BaseModel):
    name: str
    gender: Literal["female", "male"] = "female"
    model_type: Literal["anime", "real", "manhwa"] = "anime"
    appearance: str
    visual_body: Optional[str] = None
    visual_face: Optional[str] = None
    visual_default_outfit: Optional[str] = None
    visual_style_tags: Optional[str] = None
    wardrobe: dict[str, str] = {}
    tag_overrides: dict[str, Any] = {}
