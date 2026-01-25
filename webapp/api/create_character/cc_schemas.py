import enum
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, field_validator

clothes_to_prompt = {
    "Бикини": "black two-piece bikini",
    "Голый": "naked",
    "Форма медсестры": "white nurse uniform with red cross emblem",
    "Длинное платье": "long simple black evening dress with deep neckline",
    "Баскетбольная форма": "orange basketball jersey with number 23 and matching shorts",
    "Футбольная форма": "red soccer uniform with white stripes and black shorts",
    "Свадебное платье": "white wedding dress with veil and train",
    "Форма бортпроводника": "blue flight attendant uniform with scarf and hat",
    "Платье принцессы": "pink princess ball gown with tiara and puffy sleeves",
    "Одежда для йоги": "black yoga pants and light grey sports top",
    "Школьная форма": "plaid skirt with white blouse and tie",
    "Форма секретаря": "white button-up blouse with black pencil skirt",
    "Костюм ведьмы": "black witch costume with pointy hat and broom",
    "Наряд горничной": "black and white french maid outfit with apron",
    "Женские средневековые доспехи": "silver female knight armor with breastplate and gauntlets",
    "Полицейская форма": "navy blue police uniform with badge and duty belt",
    "Форма учителя": "professional blazer with glasses",
    "Костюм ангела": "white angel costume with wings and halo",
    "Балетная юбка": "pink ballet tutu with leotard and ballet shoes",
    "Свободная рубашка": "loose oversized white button-down shirt"
}

job_to_prompt = {
    "Профессор": "professor",
    "Массажист": "masseuse",
    "Фитнес-тренер": "fitness trainer",
    "Секретарь": "secretary",
    "Повар": "chef",
    "Инструктор по йоге": "yoga instructor",
    "Бортпроводник": "flight attendant",
    "Медсестра": "nurse",
    "Учитель": "teacher",
    "Полицейский": "police officer",
    "Танцовщица": "dancer",
    "Актриса": "actress",
    "Студентка колледжа": "college student",
    "Модель": "model",
    "Официантка": "waitress"
}


class CreateCharacterRequest(BaseModel):
    name: str
    style: str
    age: str
    nationality: str
    eyes_color: str
    hair_color: str
    haircut: str
    body_type: str
    boobs_size: str
    ass_size: str
    clothing: str
    preferences: list[str]
    job: str
    personality: str
    relationship: str

    def build_visual(self):
        visual = dict()
        visual["body"] = (
            f"{self.age} years old, "
            f"{self.body_type}, "
            f"{self.body_type}, "
            f"{self.haircut}, "
            f"{self.hair_color} hair, "
            f"{self.boobs_size}, "
            f"{self.ass_size}"
        )
        visual["face"] = (
            f"{self.eyes_color} eyes"
        )
        visual["default_outfit"] = clothes_to_prompt[self.clothing]
        return visual
