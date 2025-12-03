"""Вспомогательные функции."""

import re
import html


def format_response(text: str) -> str:
    """
    Преобразует кастомное форматирование в HTML для Telegram.

    Правила:
    - **текст** или *текст* → <i>текст</i> (курсив для действий)
    - "текст" → <b>текст</b> (жирный для диалога)
    - Экранирует HTML символы

    Args:
        text: Исходный текст от модели

    Returns:
        Текст с HTML форматированием
    """
    # Сначала экранируем опасные HTML символы (но не те, что в нашем форматировании)
    # Сохраняем * и кавычки для обработки

    # Заменяем **текст** на <i>текст</i> (двойные звездочки - обрабатываем первыми!)
    text = re.sub(r'\*\*(.+?)\*\*', r'<i>\1</i>', text)

    # Заменяем *текст* на <i>текст</i> (одинарные звездочки - для обратной совместимости)
    text = re.sub(r'\*([^*]+?)\*', r'<i>\1</i>', text)

    # Заменяем "текст" на <b>текст</b>
    # Внимание: обрабатываем только парные кавычки
    text = re.sub(r'"([^"]+)"', r'<b>\1</b>', text)

    # Экранируем оставшиеся спецсимволы HTML кроме наших тегов
    # Для этого сначала заменим наши теги на placeholder
    placeholders = []

    def save_tag(match):
        placeholders.append(match.group(0))
        return f"<<<PLACEHOLDER_{len(placeholders)-1}>>>"

    # Сохраняем наши HTML теги
    text = re.sub(r'<[ib]>.*?</[ib]>', save_tag, text)

    # Экранируем HTML
    text = html.escape(text)

    # Восстанавливаем наши теги
    for i, placeholder_value in enumerate(placeholders):
        text = text.replace(f"&lt;&lt;&lt;PLACEHOLDER_{i}&gt;&gt;&gt;", placeholder_value)

    return text
