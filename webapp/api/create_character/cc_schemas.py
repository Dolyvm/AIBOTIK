import enum
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, field_validator


class CreateCharacterRequest(BaseModel):
