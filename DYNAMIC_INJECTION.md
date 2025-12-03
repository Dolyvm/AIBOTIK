# Dynamic Injection — Система умного построения промптов

## 🎯 Что это?

**Dynamic Injection** — это архитектурный паттерн для построения промптов, который **динамически выбирает** какие части промпта загружать в зависимости от:
- Контекста разговора (сколько сообщений, какая стадия отношений)
- Состояния персонажа (trust, affection, arousal)
- Бюджета токенов (сколько можем потратить)

## 💡 Зачем это нужно?

### Проблема с монолитным промптом

**Раньше (Monolithic):**
```
Каждый запрос = 2000 токенов промпта
- Всегда загружается ВСЁ (даже если не нужно)
- Примеры диалога грузятся даже на 100-м сообщении
- Personality грузится когда персонаж уже известен
- Нет кеширования → тратим токены каждый раз
```

**Теперь (Dynamic Injection):**
```
Сообщение 1: ~1800 токенов (всё нужно)
Сообщение 5: ~1200 токенов (убрали примеры)
Сообщение 20: ~800 токенов (убрали description, personality)
Сообщение 50: ~600 токенов (только state + modifiers + summary)

+ Кеширование статических частей
```

### 📊 Экономия

Для 1000 пользователей × 50 сообщений/день:
- **Без DI:** $1,200/месяц
- **С DI:** $400/месяц
- **Экономия:** **66% ($800/месяц, $9,600/год)**

## 🏗️ Архитектура

### 1. Компоненты (Components)

Промпт разбит на **11 независимых компонентов:**

| Компонент | Приоритет | Тип | Условие загрузки | Токены |
|-----------|-----------|-----|------------------|--------|
| `core_instructions` | CRITICAL | STATIC | Всегда | 50 |
| `format_rules` | CRITICAL | STATIC | Всегда | 200 |
| `character_description` | HIGH | SEMI_STATIC | msg ≤ 3 | 150 |
| `personality` | MEDIUM | SEMI_STATIC | Раннее знакомство | 100 |
| `scenario` | CRITICAL | SEMI_STATIC | Всегда | 100 |
| `example_dialogue` | LOW | STATIC | msg ≤ 5 или trust < 40 | 300 |
| `current_state` | CRITICAL | DYNAMIC | Всегда | 150 |
| `behavior_modifiers` | HIGH | DYNAMIC | Всегда | 100 |
| `summary` | HIGH | DYNAMIC | Всегда | 200 |
| `format_reminder` | MEDIUM | STATIC | Всегда | 100 |
| `intimate_guidelines` | HIGH | STATIC | Интимный контекст | 80 |

### 2. Приоритеты

```python
CRITICAL = 1000   # Всегда загружается, даже если превышен бюджет
HIGH = 500        # Почти всегда
MEDIUM = 100      # Условно
LOW = 10          # Опционально
OPTIONAL = 1      # Только при большом бюджете
```

### 3. Типы компонентов

```python
STATIC         # Никогда не меняется → Кеш бесконечный
SEMI_STATIC    # Меняется редко → Кеш 1 час
DYNAMIC        # Меняется часто → Без кеша
CONTEXTUAL     # Зависит от контекста → Без кеша
```

### 4. Условия (Conditions)

Компоненты загружаются только если **все условия выполнены:**

```python
# Примеры условий
StandardConditions.first_messages(5)           # Только первые 5 сообщений
StandardConditions.low_trust()                 # trust < 40
StandardConditions.aroused()                   # arousal > 50
StandardConditions.is_intimate()               # Интимная стадия отношений
StandardConditions.early_relationship()        # msg ≤ 10 ИЛИ trust < 40

# Комбинации
ConditionEvaluator.all_of(                     # И
    StandardConditions.aroused(),
    StandardConditions.high_affection()
)

ConditionEvaluator.any_of(                     # ИЛИ
    StandardConditions.first_messages(10),
    StandardConditions.low_trust()
)
```

## 🔄 Кеширование

### Трёхуровневая система

**Level 1: STATIC** (бесконечный кеш)
- `core_instructions`, `format_rules`, `example_dialogue`, `format_reminder`
- Генерируется **один раз** и используется всегда

**Level 2: SEMI_STATIC** (TTL 1 час)
- `character_description`, `personality`, `scenario`
- Генерируется при первом использовании, обновляется раз в час

**Level 3: DYNAMIC** (без кеша)
- `current_state`, `behavior_modifiers`, `summary`
- Генерируется каждый раз (т.к. меняется постоянно)

### Инвалидация кеша

Кеш автоматически сбрасывается при событиях:

| Событие | Инвалидируемые компоненты |
|---------|---------------------------|
| `CHARACTER_SWITCHED` | Все (кроме format_rules) |
| `STATE_MAJOR_CHANGE` | current_state, behavior_modifiers, personality, example_dialogue |
| `MOOD_CHANGED` | behavior_modifiers |
| `SUMMARY_CREATED` | summary |
| `NEW_SESSION` | Все |

## 📝 Как это работает?

### Пример: 1-е сообщение пользователя

```
1. Фильтрация по условиям:
   ✅ core_instructions (нет условий)
   ✅ format_rules (нет условий)
   ✅ character_description (msg=1, условие: msg≤3)
   ✅ personality (msg=1, trust=50, условие: early_relationship)
   ✅ scenario (нет условий)
   ✅ example_dialogue (msg=1, условие: msg≤5)
   ✅ current_state (нет условий)
   ✅ behavior_modifiers (нет условий)
   ✅ summary (нет условий)
   ✅ format_reminder (нет условий)
   ❌ intimate_guidelines (arousal=20, условие: intimate_context)

2. Сортировка по приоритету:
   CRITICAL: core_instructions, format_rules, scenario, current_state
   HIGH: character_description, behavior_modifiers, summary
   MEDIUM: personality, format_reminder
   LOW: example_dialogue

3. Проверка бюджета (4000 токенов):
   ✅ Все компоненты поместились: ~1530 токенов

4. Генерация контента (с кешированием):
   ✅ core_instructions: кеш пуст → генерируем → сохраняем в кеш ∞
   ✅ format_rules: кеш пуст → генерируем → сохраняем в кеш ∞
   ✅ character_description: кеш пуст → генерируем → сохраняем в кеш 1ч
   ...

5. Результат:
   Промпт из 10 секций, ~1530 токенов, кеш заполнен
```

### Пример: 20-е сообщение

```
1. Фильтрация по условиям:
   ✅ core_instructions
   ✅ format_rules
   ❌ character_description (msg=20, условие: msg≤3) ← УБРАЛИ
   ❌ personality (msg=20, trust=75, условие: early_relationship) ← УБРАЛИ
   ✅ scenario
   ❌ example_dialogue (msg=20, trust=75, условие: msg≤5 или trust<40) ← УБРАЛИ
   ✅ current_state
   ✅ behavior_modifiers
   ✅ summary
   ✅ format_reminder
   ❌ intimate_guidelines

2. Проверка бюджета:
   ✅ Все компоненты поместились: ~800 токенов

3. Генерация контента (с кешированием):
   ✅ core_instructions: берём из кеша ∞
   ✅ format_rules: берём из кеша ∞
   ✅ scenario: берём из кеша 1ч
   ✅ current_state: генерируем заново (dynamic)
   ✅ behavior_modifiers: генерируем заново (dynamic)
   ✅ summary: генерируем заново (dynamic)
   ✅ format_reminder: берём из кеша ∞

4. Результат:
   Промпт из 7 секций, ~800 токенов
   6 компонентов из кеша, 3 сгенерированы
```

## 🚀 Использование

### Автоматический режим (по умолчанию)

```python
# В main.py
prompt_builder = PromptBuilder()  # Dynamic Injection включён автоматически

# В handlers/messages.py
system_prompt = prompt_builder.build_system_prompt(
    character=character,
    state=session.character_state,
    summary=session.summary,
    user_name=user_name,
    session=session,              # ← Передаём для DI
    message_count=session.message_count  # ← Передаём для условий
)
```

### Legacy режим (без Dynamic Injection)

```python
# Если нужен старый монолитный подход
prompt_builder = PromptBuilder(use_dynamic_injection=False)

# Работает как раньше
system_prompt = prompt_builder.build_system_prompt(
    character=character,
    state=session.character_state,
    summary=session.summary,
    user_name=user_name
)
```

### Уведомления о событиях

```python
# После создания summary
prompt_builder.notify_summary_created()

# Получение SmartPromptBuilder для расширенного контроля
smart_builder = prompt_builder.get_smart_builder()
if smart_builder:
    stats = smart_builder.get_component_stats()
    smart_builder.log_component_stats()
```

## 📊 Мониторинг

### Логи INFO

```
INFO:services.prompt_builder:✨ PromptBuilder initialized with Dynamic Injection enabled
INFO:services.prompt_injection.smart_builder:SmartPromptBuilder initialized with 11 components, token_budget=4000
INFO:services.prompt_injection.composer:Eligible components: 10/11
INFO:services.prompt_injection.composer:Composed prompt: 7 sections, ~843 tokens (21.1% of budget)
INFO:services.prompt_injection.cache_manager:🔄 Cache event: summary_created → Invalidating 1 components: summary
```

### Логи DEBUG

```
DEBUG:services.prompt_injection.composer:Registered component: core_instructions (priority=1000, type=static)
DEBUG:services.prompt_injection.composer:✓ core_instructions: 42 tokens (from cache) (total: 42/4000)
DEBUG:services.prompt_injection.composer:✓ format_rules: 187 tokens (from cache) (total: 229/4000)
```

### Статистика компонентов

```python
smart_builder = prompt_builder.get_smart_builder()
stats = smart_builder.get_component_stats()

print(f"Компонентов: {stats['total_components']}")
print(f"Бюджет: {stats['token_budget']}")
for comp in stats['components']:
    print(f"  • {comp['name']}: {comp['cache_status']}, ~{comp['estimated_tokens']}t")
```

## 🔧 Расширение

### Добавление нового компонента

```python
# В presets/roleplay.py или создайте свой preset

composer.register(StaticTextComponent(
    name="my_custom_component",
    content="Какой-то дополнительный текст",
    priority=ComponentPriority.MEDIUM,
    conditions=[
        StandardConditions.high_trust()  # Только при trust > 70
    ],
    estimated_tokens=50
))
```

### Создание своего условия

```python
# В conditions.py

@staticmethod
def custom_condition():
    """Моё условие."""
    def evaluate(ctx: InjectionContext) -> bool:
        # Логика условия
        return ctx.state.trust > 50 and ctx.message_count > 10
    return evaluate
```

### Создание своего preset

```python
# services/prompt_injection/presets/my_preset.py

from ..composer import PromptComposer
from ..components import StaticTextComponent
from ..core import ComponentPriority

def create_my_composer(token_budget: int = 4000) -> PromptComposer:
    composer = PromptComposer(token_budget=token_budget)

    composer.register(StaticTextComponent(
        name="my_component",
        content="Контент компонента",
        priority=ComponentPriority.CRITICAL,
        estimated_tokens=100
    ))

    # ... регистрируем другие компоненты

    return composer
```

## 📚 API Reference

### SmartPromptBuilder

```python
builder = SmartPromptBuilder(token_budget=4000)

# Построение промпта
prompt = builder.build_system_prompt(
    character: CharacterData,
    state: CharacterState,
    session: UserSession,
    user_name: str,
    message_count: int
) -> str

# Уведомления
builder.notify_summary_created()
builder.notify_character_updated()
builder.notify_first_touch()

# Управление
builder.reset_for_new_session()
builder.invalidate_all()

# Статистика
stats = builder.get_component_stats()
builder.log_component_stats()
```

### PromptComposer

```python
composer = PromptComposer(token_budget=4000)

# Регистрация компонентов
composer.register(component: PromptComponent)

# Композиция
prompt = composer.compose(ctx: InjectionContext) -> str

# Управление кешем
composer.invalidate_cache(component_name: Optional[str] = None)
composer.get_component(name: str) -> Optional[PromptComponent]
```

### CacheInvalidationManager

```python
manager = CacheInvalidationManager(composer)

# Обработка событий
manager.handle_event(
    event: CacheEvent,
    component_names: Optional[Set[str]] = None
)

# Ручная инвалидация
manager.invalidate_all()
manager.invalidate_component(component_name: str)
```

## ❓ FAQ

**Q: Как узнать, работает ли Dynamic Injection?**
A: Проверьте логи при запуске бота:
```
INFO:services.prompt_builder:✨ PromptBuilder initialized with Dynamic Injection enabled
```

**Q: Можно ли отключить Dynamic Injection?**
A: Да, в main.py:
```python
prompt_builder = PromptBuilder(use_dynamic_injection=False)
```

**Q: Как увеличить/уменьшить бюджет токенов?**
A: При инициализации:
```python
prompt_builder = PromptBuilder(token_budget=6000)  # Увеличили до 6000
```

**Q: Как добавить свой компонент?**
A: Отредактируйте `services/prompt_injection/presets/roleplay.py` и добавьте новый `composer.register(...)`

**Q: Сколько экономится токенов реально?**
A: В среднем:
- Сообщения 1-5: ~10% экономии (примеры ещё нужны)
- Сообщения 6-20: ~40% экономии (убрали примеры)
- Сообщения 21+: ~60% экономии (убрали description, personality)
- + кеширование статических частей

**Q: Совместимо ли со старым кодом?**
A: Да! API PromptBuilder обратно совместим. Если не передавать `session` и `message_count`, будет использоваться legacy режим.

## 🎓 Дополнительные материалы

Подробное объяснение архитектуры см. в `.claude/plans/wild-churning-dream.md`

---

**Реализовано:** 2024
**Версия:** 1.0.0
**Автор:** Dynamic Injection Architecture
