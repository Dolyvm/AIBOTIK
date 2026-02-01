import logging

from .cc_schemas import CreateCharacterRequest

# ═══════════════════════════════════════════════════════════════════════════
# КАРТОЧКИ ДЛЯ UI
# ═══════════════════════════════════════════════════════════════════════════

styleCards = [
    {
        "title": "Аниме",
        "value": "anime",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Реалистично",
        "value": "real",
        "img": "/content/characters/emily.png"
    }
]

ageCards = [
    {
        "title": "18",
        "value": "18",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "20-30",
        "value": "25",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "30-40",
        "value": "35",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "40-50",
        "value": "45",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "60+",
        "value": "70",
        "img": "/content/characters/aiko.png"
    }
]

nationalityCards = [
    {
        "title": "Американская",
        "value": "american",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Азиатская",
        "value": "asian",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Русская",
        "value": "russian",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Итальянская",
        "value": "italian",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Латино",
        "value": "latin",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Немецкая",
        "value": "german",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Японская",
        "value": "japanese",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Индийская",
        "value": "indian",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Арабская",
        "value": "arab",
        "img": "/content/characters/aiko.png"
    }
]

eyeColorCards = [
    {
        "title": "Карие",
        "value": "brown",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Синие",
        "value": "blue",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Зеленые",
        "value": "green",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Серые",
        "value": "grey",
        "img": "/content/characters/aiko.png"
    }
]


hairColorCards = [
    {
        "title": "Черные",
        "value": "black",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Коричневые",
        "value": "brown",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Блонд",
        "value": "blond",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Красные",
        "value": "red",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Серые",
        "value": "grey",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Белые",
        "value": "white",
        "img": "/content/characters/aiko.png"
    }
]


haircutCards = [
    {
        "title": "Прямые волосы",
        "value": "straight haircut",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Косы",
        "value": "braids haircut",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Кудрявые",
        "value": "curly hair",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Пучок",
        "value": "hair in bun",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Короткие",
        "value": "pixie haircut",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Хвостик",
        "value": "ponytail hair",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Два хвостика",
        "value": "two ponytails hair",
        "img": "/content/characters/aiko.png"
    }
]

bodyTypeCards = [
    {
        "title": "Очень худой",
        "value": "anorexic slender body",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Худой",
        "value": "petite slim body",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Спортивный",
        "value": "fit body",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Пышный",
        "value": "curvy body",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Толстый",
        "value": "fat body",
        "img": "/content/characters/aiko.png"
    }
]

boobSizeCards = [
    {
        "title": "Маленькая",
        "value": "small breasts",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Средняя",
        "value": "beautiful breasts",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Большая",
        "value": "big breasts",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Огромная",
        "value": "huge breasts",
        "img": "/content/characters/aiko.png"
    }
]

assSizeCards = [
    {
        "title": "Маленькая",
        "value": "small ass",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Средняя",
        "value": "fit ass",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Большая",
        "value": "big round ass",
        "img": "/content/characters/aiko.png"
    },
    {
        "title": "Огромная",
        "value": "huge round ass",
        "img": "/content/characters/aiko.png"
    }
]

clothesItems = [
    "Бикини",
    "Голый",
    "Форма медсестры",
    "Длинное платье",
    "Баскетбольная форма",
    "Футбольная форма",
    "Свадебное платье",
    "Форма бортпроводника",
    "Платье принцессы",
    "Одежда для йоги",
    "Школьная форма",
    "Форма секретаря",
    "Костюм ведьмы",
    "Наряд горничной",
    "Женские средневековые доспехи",
    "Полицейская форма",
    "Форма учителя",
    "Костюм ангела",
    "Балетная юбка",
    "Свободная рубашка"
]

preferencesItems = [
    "Подчинение",
    "Доминирование",
    "Игрушка",
    "Бондаж",
    "На улице",
    "Вуайеризм",
    "Ругань",
    "Шлепки",
    "Групповой секс",
    "Обмен Женами",
    "Унижение",
    "Рванье Одежды",
    "Связывание (БДСМ)",
    "Порнография",
    "Форма",
    "Анальный секс",
    "С завязанными глазами",
    "Оральный секс",
    "Анальная пробка",
    "Игра со свечами",
    "Ошейник и поводок",
    "Внутреннее семяизвержение",
    "Эякуляция на лицо",
    "Глубокая глотка",
    "Дилдо",
    "Сзади (догги-стайл)",
    "Двойное проникновение",
    "Куни (оральный секс женщинам)",
    "Вставление пальцев",
    "Фистинг",
    "Секс с едой",
    "Запретная любовь",
    "Дергать за волосы",
    "Наручники"
]

jobItems = [
    "Профессор",
    "Массажист",
    "Фитнес-тренер",
    "Секретарь",
    "Повар",
    "Инструктор по йоге",
    "Бортпроводник",
    "Медсестра",
    "Учитель",
    "Полицейский",
    "Танцовщица",
    "Актриса",
    "Студентка колледжа",
    "Модель",
    "Официантка"
]

personalityItems = [
    "Заботливый",
    "Мудрец",
    "Невинный",
    "Соблазнительница",
    "Доминант",
    "Покорный",
    "Любовник",
    "Фанатик",
    "Апатичный",
    "Доверенное лицо"
]

relationshipItems = [
    "Падчерица",
    "Мачеха",
    "Любовница",
    "Одноклассник",
    "Коллега",
    "Учитель",
    "Девушка",
    "Друг с привилегиями",
    "Жена",
    "Друг"
]

stepsList = [
    {
        "type": "nameInput",
        "id": "nameInput",
        "title": "Введите имя нового персонажа"
    },
    {
        "type": "imgSelect",
        "id": "style",
        "title": "Выбрать стиль",
        "items": styleCards
    },
    {
        "type": "imgSelect",
        "id": "age",
        "title": "Выбрать возраст",
        "items": ageCards
    },
    {
        "type": "imgSelect",
        "id": "nationality",
        "title": "Выбрать национальность",
        "items": nationalityCards
    },
    {
        "type": "imgSelect",
        "id": "eyes_color",
        "title": "Выбрать цвет глаз",
        "items": eyeColorCards
    },
    {
        "type": "imgSelect",
        "id": "hair_color",
        "title": "Выбрать цвет волос",
        "items": hairColorCards
    },
    {
        "type": "imgSelect",
        "id": "haircut",
        "title": "Выбрать прическу",
        "items": haircutCards
    },
    {
        "type": "imgSelect",
        "id": "body_type",
        "title": "Выбрать телосложение",
        "items": bodyTypeCards
    },
    {
        "type": "imgSelect",
        "id": "boobs_size",
        "title": "Выбрать размер груди",
        "items": boobSizeCards
    },
    {
        "type": "imgSelect",
        "id": "ass_size",
        "title": "Выбрать размер жопы",
        "items": assSizeCards
    },

    {
        "type": "textSelect",
        "id": "clothing",
        "title": "Выберите одежду",
        "items": clothesItems
    },
    {
        "type": "textMultiSelect",
        "id": "preferences",
        "title": "Выберите предпочтения",
        "items": preferencesItems
    },
    {
        "type": "textSelect",
        "id": "job",
        "title": "Выберите профессию",
        "items": jobItems
    },
    {
        "type": "textSelect",
        "id": "personality",
        "title": "Выберите характер",
        "items": personalityItems
    },
    {
        "type": "textSelect",
        "id": "relationship",
        "title": "Выберите ваши взаимоотношения",
        "items": relationshipItems
    }
]


personality_to_prompt = {
    "Заботливый": "Тёплая, защищающая, ставит чужое благополучие выше своего.",
    "Мудрец": "Спокойная, рассудительная, направляет словами и опытом.",
    "Невинный": "Чистосердечная, доверчивая, смотрит на мир без подозрений.",
    "Соблазнительница": "Притягательная, лукавая, влияет через обаяние и намёки.",
    "Доминант": "Властная, уверенная, привыкла отдавать приказы и вести за собой.",
    "Покорный": "Смиренная, послушная, ищет указаний и защиты.",
    "Любовник": "Чувственная, страстная, выражает себя через эмоции и близость.",
    "Фанатик": "Одержимая, фанатично преданная, подчиняет всё своей вере или идее.",
    "Апатичный": "Отрешённая, безразличная, говорит мало и без интереса.",
    "Доверенное лицо": "Надёжная, скрытная, говорит честно и хранит тайны."
}

job_to_tags = {
    "Профессор": ["Teacher", "Academic"],
    "Массажист": ["Massage", "Relaxation"],
    "Фитнес-тренер": ["Fitness", "Athletic"],
    "Секретарь": ["Office", "Professional"],
    "Повар": ["Chef", "Kitchen"],
    "Инструктор по йоге": ["Yoga", "Fitness"],
    "Бортпроводник": ["Flight", "Travel"],
    "Медсестра": ["Nurse", "Medical"],
    "Учитель": ["Teacher", "School"],
    "Полицейский": ["Police", "Uniform"],
    "Танцовщица": ["Dancer", "Performance"],
    "Актриса": ["Actress", "Celebrity"],
    "Студентка колледжа": ["Student", "School"],
    "Модель": ["Model", "Fashion"],
    "Официантка": ["Waitress", "Service"]
}

personality_to_tags = {
    "Заботливый": ["Caring", "Sweet"],
    "Мудрец": ["Wise", "Calm"],
    "Невинный": ["Cute", "Shy", "Innocent"],
    "Соблазнительница": ["Flirtatious", "Seductive"],
    "Доминант": ["Dominant", "Commanding"],
    "Покорный": ["Submissive", "Shy"],
    "Любовник": ["Passionate", "Romantic"],
    "Фанатик": ["Intense", "Devoted"],
    "Апатичный": ["Cold", "Distant"],
    "Доверенное лицо": ["Trustworthy", "Reliable"]
}

preference_to_tags = {
    # BDSM группа
    "Подчинение": "BDSM",
    "Доминирование": "BDSM",
    "Бондаж": "BDSM",
    "Связывание (БДСМ)": "BDSM",
    "Ошейник и поводок": "BDSM",
    "Наручники": "BDSM",
    "С завязанными глазами": "Blindfold",
    # Групповое
    "Групповой секс": "Group",
    "Обмен Женами": "Swinger",
    "Двойное проникновение": "DP",
    # Публичное
    "На улице": "Public",
    "Вуайеризм": "Voyeur",
    # Игрушки
    "Игрушка": "Toys",
    "Анальная пробка": "Toys",
    "Дилдо": "Toys",
    # Грубое
    "Шлепки": "Spanking",
    "Унижение": "Humiliation",
    "Рванье Одежды": "Rough",
    "Дергать за волосы": "Rough",
    "Ругань": "Dirty Talk",
    # Сексуальные акты
    "Анальный секс": "Anal",
    "Оральный секс": "Oral",
    "Глубокая глотка": "Deepthroat",
    "Куни (оральный секс женщинам)": "Oral",
    "Вставление пальцев": "Fingering",
    "Фистинг": "Fisting",
    "Сзади (догги-стайл)": "Doggy",
    # Финишы
    "Внутреннее семяизвержение": "Creampie",
    "Эякуляция на лицо": "Facial",
    # Другое
    "Игра со свечами": "Waxplay",
    "Секс с едой": "Foodplay",
    "Запретная любовь": "Taboo",
    "Порнография": "Porn",
    "Форма": "Uniform"
}


def generate_tags(req: CreateCharacterRequest) -> list[str]:
    tags = set()

    if req.style == "anime":
        tags.add("Anime")
    else:
        tags.add("Realistic")

    job_tags = job_to_tags.get(req.job, [])
    tags.update(job_tags)

    pers_tags = personality_to_tags.get(req.personality, [])
    tags.update(pers_tags)

    for pref in (req.preferences or []):
        if pref in preference_to_tags:
            tags.add(preference_to_tags[pref])

    tags.add("NSFW")
    tags.add("Adult")

    return list(tags)


def build_personality_with_preferences(req: CreateCharacterRequest) -> str:
    base = personality_to_prompt.get(req.personality, req.personality)

    if req.preferences:
        prefs_text = ", ".join(req.preferences)
        return f"{base} Предпочтения в интимной сфере: {prefs_text}."

    return base


def build_llm_prompt(req: CreateCharacterRequest) -> str:
    from shared.services.prompt_service import get_prompt

    prompt_template = get_prompt("cc_scenario_prompt")
    return prompt_template.format(
        name=req.name,
        job=req.job,
        personality=req.personality,
        relationship=req.relationship,
        nationality=req.nationality
    ).strip()


def build_description_prompt(req: CreateCharacterRequest) -> str:
    from shared.services.prompt_service import get_prompt

    prompt_template = get_prompt("cc_description_prompt")
    return prompt_template.format(
        name=req.name,
        age=req.age,
        nationality=req.nationality,
        job=req.job,
        personality=req.personality,
        relationship=req.relationship,
        preferences=', '.join(req.preferences) if req.preferences else 'не указаны'
    ).strip()


def build_first_mes_prompt(req: CreateCharacterRequest, scenario: str) -> str:
    from shared.services.prompt_service import get_prompt

    prompt_template = get_prompt("cc_first_mes_prompt")
    return prompt_template.format(
        name=req.name,
        personality=req.personality,
        job=req.job,
        relationship=req.relationship,
        preferences=', '.join(req.preferences) if req.preferences else 'не указаны',
        scenario=scenario
    ).strip()
