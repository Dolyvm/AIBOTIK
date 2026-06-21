from __future__ import annotations

import unicodedata
from typing import Any


MAIN_CHARACTER_NAME_ORDER: tuple[str, ...] = (
    "Хон Ю Бин",
    "Момо",
    "Анжелика",
    "Юн Мин У",
    "Юна",
    "Годжо",
    "Кай",
    "Аска Лэнгли",
    "Леви Аккерман",
    "Юно Гасай",
    "Макима",
    "Ким",
    "Анета",
    "Мия",
    "Пак Чхуен",
    "Макс Фолл",
    "Пауэр",
    "Сукуна",
    "Феликс",
    "Хотару",
    "Акира",
    "Моргана Вэйн",
    "Ха Сон",
    "Эрен Йегер",
    "Лиза",
    "Мисато Кацураги",
    "Дазай Осаму",
    "Аяка",
    "Джиро",
    "Саске Учиха",
    "Уэнздей",
    "Химико",
    "Тарталья",
    "Куронэ",
    "Сяо",
    "Нана",
    "Кейя Альберих",
    "Джессика",
    "Чо Джа Хён",
    "Аой",
    "Соль Джи Ан",
    "Аполлинария",
    "Асахи",
    "Шэнь Хэ",
    "Рэндзо",
    "Джун",
    "Бен",
    "Юки",
    "Макото",
    "Хейзел",
    "Август",
    "Иоши",
    "Даниэль",
    "Каэда",
    "Агнес",
    "Лилит",
    "Малефисента",
    "Серафима",
)


def normalize_character_name(value: str | None) -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = normalized.replace("Ё", "Е").replace("ё", "е").casefold()
    return " ".join(normalized.split())


_MAIN_CHARACTER_ORDER_INDEX = {
    normalize_character_name(name): index
    for index, name in enumerate(MAIN_CHARACTER_NAME_ORDER)
}

_MAIN_CHARACTER_NAME_ALIASES = {
    normalize_character_name("Пак Чжуен"): normalize_character_name("Пак Чхуен"),
}


def main_character_sort_key(character: dict[str, Any]) -> tuple[int, int, str, str]:
    name = normalize_character_name(character.get("name"))
    ordered_name = _MAIN_CHARACTER_NAME_ALIASES.get(name, name)
    character_id = str(character.get("id") or "")
    order_index = _MAIN_CHARACTER_ORDER_INDEX.get(ordered_name)

    if order_index is not None:
        return (0, order_index, "", character_id)

    return (1, len(MAIN_CHARACTER_NAME_ORDER), name, character_id)


def sort_main_characters(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(characters, key=main_character_sort_key)
