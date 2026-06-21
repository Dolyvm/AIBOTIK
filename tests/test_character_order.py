from shared.character_order import normalize_character_name, sort_main_characters


def _names(characters):
    return [character["name"] for character in characters]


def test_main_character_order_skips_missing_characters():
    characters = [
        {"id": "yuna", "name": "Юна"},
        {"id": "mom", "name": "Момо"},
        {"id": "seraphima", "name": "Серафима"},
        {"id": "hon", "name": "Хон Ю Бин"},
    ]

    assert _names(sort_main_characters(characters)) == [
        "Хон Ю Бин",
        "Момо",
        "Юна",
        "Серафима",
    ]


def test_main_character_order_places_unknown_characters_at_bottom():
    characters = [
        {"id": "new-z", "name": "Бета Новая"},
        {"id": "yuna", "name": "Юна"},
        {"id": "new-a", "name": "Ааа Новая"},
        {"id": "mom", "name": "Момо"},
    ]

    assert _names(sort_main_characters(characters)) == [
        "Момо",
        "Юна",
        "Ааа Новая",
        "Бета Новая",
    ]


def test_character_name_normalization_handles_spacing_case_and_yo():
    assert normalize_character_name("  ЭРЕН   ЙЁГЕР ") == normalize_character_name("эрен йегер")


def test_main_character_order_supports_known_name_alias():
    characters = [
        {"id": "next", "name": "Макс Фолл"},
        {"id": "pak", "name": "Пак Чжуен"},
        {"id": "prev", "name": "Мия"},
    ]

    assert _names(sort_main_characters(characters)) == [
        "Мия",
        "Пак Чжуен",
        "Макс Фолл",
    ]
