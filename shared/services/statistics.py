import math
from typing import List, Dict, Any

from sqlalchemy import select, func, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import User, Event
from shared.subscription_plans import PLAN_LIMITS


class StatisticsService:
    @staticmethod
    async def get_all_users_count(session: AsyncSession) -> int:
        """
        Get total count of all users in the database

        Args:
            session: Async SQLAlchemy session

        Returns:
            int: Total number of users
        """
        query = select(func.count(User.telegram_id))
        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_users_with_chats(session: AsyncSession) -> int:
        """
        Get count of users who have started at least one chat

        Args:
            session: Async SQLAlchemy session

        Returns:
            int: Number of unique users who started at least one chat
        """
        query = (
            select(func.count(distinct(Event.user_id)))
            .where(Event.event_type == "character_chat_started")
        )
        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_top_characters_info(session: AsyncSession, head: int = 10) -> List[Dict[str, Any]]:
        """
        Топ-N персонажей по метрикам:
        * просмотры
        * кол-во созданных чатов
        * конверсия = (уникальные чаты с персонажем / просмотры) * 100
        * сообщения
        """
        query = text("""
            WITH view_stats AS (
                SELECT 
                    entity_id AS character_id,
                    COUNT(*) AS views
                FROM events
                WHERE event_type = 'character_click'
                  AND entity_type = 'characters'
                GROUP BY entity_id
            ),
            chat_stats AS (
                SELECT
                    c.target_id,
                    COUNT(DISTINCT c.id) AS chats
                FROM chats c
                WHERE c.target_id IS NOT NULL
                  AND c.chat_type = 'character'
                GROUP BY c.target_id
            ),
            message_stats AS (
                SELECT
                    (e.meta->>'character_id') AS target_id,
                    COUNT(e.id) AS messages
                FROM events e
                WHERE e.event_type = 'message_sent'
                    AND e.meta->>'character_id' IS NOT NULL
                GROUP BY (e.meta->>'character_id')
            ),
            image_stats AS (
                SELECT 
                    (e.meta->>'character_id') AS character_id,
                    COUNT(e.id) AS images
                FROM events e
                WHERE e.event_type = 'image_generated'
                    AND e.meta->>'character_id' IS NOT NULL
                GROUP BY (e.meta->>'character_id')
            )
            SELECT 
                ch.name AS "Персонаж",
                COALESCE(v.views, 0) AS "Просмотры",
                COALESCE(cs.chats, 0) AS "Чаты",
                CASE 
                    WHEN COALESCE(v.views, 0) > 0 
                    THEN ROUND(COALESCE(cs.chats, 0)::numeric / v.views * 100, 1)
                    ELSE 0
                END AS "Конверсия (%)",
                COALESCE(ms.messages, 0) AS "Сообщения",
                COALESCE(img.images, 0) AS "Фотографии"
            FROM characters ch
            LEFT JOIN view_stats v ON v.character_id = ch.id
            LEFT JOIN chat_stats cs ON cs.target_id = ch.id
            LEFT JOIN message_stats ms ON ms.target_id = ch.id
            LEFT JOIN image_stats img ON img.character_id = ch.id
            ORDER BY "Просмотры" DESC
            LIMIT :head
        """)

        result = await session.execute(query, {"head": head})
        rows = result.mappings().all()

        return [dict(row) for row in rows]

    @staticmethod
    async def get_top_worlds_info(session: AsyncSession, head: int = 10) -> List[Dict[str, Any]]:
        """
        Топ-N миров по метрикам:
        * просмотры персонажей этого мира
        * кол-во созданных чатов с персонажами мира
        * конверсия = (чаты / просмотры) * 100
        * сообщения в чатах с персонажами мира
        """
        query = text("""
            WITH view_stats AS (
                SELECT 
                    entity_id AS world_id,
                    COUNT(*) AS views
                FROM events
                WHERE event_type = 'world_click'
                  AND entity_type = 'worlds'
                GROUP BY entity_id
            ),
            chat_stats AS (
                SELECT
                    c.target_id,
                    COUNT(DISTINCT c.id) AS chats
                FROM chats c
                WHERE c.target_id IS NOT NULL
                  AND c.chat_type = 'world'
                GROUP BY c.target_id
            ),
            message_stats AS (
                SELECT
                    (e.meta->>'world_id') AS target_id,
                    COUNT(e.id) AS messages
                FROM events e
                WHERE e.event_type = 'message_sent'
                    AND e.meta->>'world_id' IS NOT NULL
                GROUP BY (e.meta->>'world_id')
            )
            SELECT 
                w.name AS "Мир",
                COALESCE(v.views, 0) AS "Просмотры",
                COALESCE(cs.chats, 0) AS "Чаты",
                CASE 
                    WHEN COALESCE(v.views, 0) > 0 
                    THEN ROUND(COALESCE(cs.chats, 0)::numeric / v.views * 100, 1)
                    ELSE 0
                END AS "Конверсия (%)",
                COALESCE(ms.messages, 0) AS "Сообщения"
            FROM worlds w
            LEFT JOIN view_stats v ON v.world_id = w.id
            LEFT JOIN chat_stats cs ON cs.target_id = w.id
            LEFT JOIN message_stats ms ON ms.target_id = w.id
            ORDER BY "Просмотры" DESC
            LIMIT :head
        """)

        result = await session.execute(query, {"head": head})
        rows = result.mappings().all()

        return [dict(row) for row in rows]

    @staticmethod
    async def get_churned_users_summary(session: AsyncSession, days_threshold: int = 7) -> Dict[str, Any]:
        """
        Сводная статистика по ушедшим пользователям (не было событий > days_threshold дней).
        Возвращает словарь с:
        * общее количество ушедших пользователей
        * процент ушедших от всех пользователей
        * среднее количество дней неактивности
        * Всего событий от ушедших
        * Распределение по последним событиям (считает, сколько раз то или иное событие было финальным). Пример:
            {
              "message_sent": 45,
              "image_generated": 12,
              "character_click": 8,
              "chat_created": 5
            }
        """
        query = text("""
            WITH user_activity AS (
                SELECT 
                    user_id,
                    MAX(created_at) AS last_event_at,
                    COUNT(*) AS total_events
                FROM events
                GROUP BY user_id
            ),
            churned_users AS (
                SELECT 
                    ua.*,
                    u.username,
                    EXTRACT(DAY FROM (NOW() - ua.last_event_at))::INT AS days_inactive
                FROM user_activity ua
                JOIN users u ON u.telegram_id = ua.user_id
                WHERE ua.last_event_at < NOW() - (interval '1 day' * :days_threshold)
            ),
            last_events AS (
                SELECT DISTINCT ON (user_id)
                    user_id,
                    event_type
                FROM events
                ORDER BY user_id, created_at DESC
            )
            SELECT 
                COUNT(*) AS "Всего ушедших",
                ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM users), 1) AS "Процент от всех пользователей",
                COALESCE(AVG(days_inactive)::NUMERIC(10,1), 0) AS "Среднее дней неактивности",
                SUM(total_events) AS "Всего событий от ушедших",
                (
                    SELECT jsonb_object_agg(event_type, count)
                    FROM (
                        SELECT le.event_type, COUNT(*) as count
                        FROM last_events le
                        WHERE le.user_id IN (SELECT user_id FROM churned_users)
                        GROUP BY le.event_type
                    ) t
                ) AS "Распределение по последним событиям"
            FROM churned_users
        """)

        result = await session.execute(query, {"days_threshold": days_threshold})
        row = result.mappings().first()

        return dict(row) if row else {}

    @staticmethod
    async def get_users_table(
        session: AsyncSession,
        page: int = 1,
        per_page: int = 50,
        search: str = "",
    ) -> Dict[str, Any]:
        """Возвращает постраничный список пользователей с тарифом и usage за текущий месяц."""
        from datetime import datetime
        period = datetime.utcnow().strftime("%Y-%m")

        search_clause = ""
        params: Dict[str, Any] = {"period": period, "limit": per_page, "offset": (page - 1) * per_page}
        if search:
            search_clause = "WHERE u.username ILIKE :search OR CAST(u.telegram_id AS TEXT) LIKE :search"
            params["search"] = f"%{search}%"

        count_query = text(f"""
            SELECT COUNT(*) FROM users u
            {search_clause}
        """)
        count_result = await session.execute(count_query, params)
        total = count_result.scalar_one()

        rows_query = text(f"""
            SELECT
                u.telegram_id,
                u.username,
                u.subscription_plan,
                u.subscription_end_date,
                u.last_active_at,
                u.created_at,
                COALESCE(mu.messages_sent, 0)      AS messages_sent,
                COALESCE(mu.images_generated, 0)   AS images_generated,
                COALESCE(mu.characters_created, 0) AS characters_created,
                COALESCE(mu.worlds_created, 0)     AS worlds_created,
                COALESCE(mu.content_edits, 0)      AS content_edits,
                COALESCE(mu.avatar_generations, 0) AS avatar_generations,
                COALESCE(mu.bonus_messages_sent, 0)      AS bonus_messages_sent,
                COALESCE(mu.bonus_images_generated, 0)   AS bonus_images_generated,
                COALESCE(mu.bonus_characters_created, 0) AS bonus_characters_created,
                COALESCE(mu.bonus_worlds_created, 0)     AS bonus_worlds_created,
                COALESCE(mu.bonus_content_edits, 0)      AS bonus_content_edits,
                COALESCE(mu.bonus_avatar_generations, 0) AS bonus_avatar_generations
            FROM users u
            LEFT JOIN monthly_usage mu
                ON mu.user_id = u.telegram_id AND mu.period = :period
            {search_clause}
            ORDER BY u.last_active_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """)
        rows_result = await session.execute(rows_query, params)
        rows = rows_result.mappings().all()

        from shared.models import SubscriptionPlan
        users = []
        for row in rows:
            try:
                plan = SubscriptionPlan(row["subscription_plan"])
            except (ValueError, KeyError):
                plan = SubscriptionPlan.FREE
            plan_cfg = PLAN_LIMITS[plan]

            usage_types = {
                "messages": ("messages_sent", "bonus_messages_sent"),
                "images": ("images_generated", "bonus_images_generated"),
                "characters_created": ("characters_created", "bonus_characters_created"),
                "worlds_created": ("worlds_created", "bonus_worlds_created"),
                "content_edits": ("content_edits", "bonus_content_edits"),
                "avatar_generations": ("avatar_generations", "bonus_avatar_generations"),
            }
            usage_summary = {}
            for ut, (db_field, bonus_field) in usage_types.items():
                used = row[db_field]
                bonus = row[bonus_field]
                plan_limit = plan_cfg.get(ut, 0)
                total_limit = plan_limit + bonus
                usage_summary[ut] = {"used": used, "limit": total_limit, "bonus": bonus}

            users.append({
                "telegram_id": row["telegram_id"],
                "username": row["username"],
                "plan": plan.value,
                "plan_display_name": plan_cfg["display_name"],
                "subscription_end_date": row["subscription_end_date"],
                "last_active_at": row["last_active_at"],
                "created_at": row["created_at"],
                "usage": usage_summary,
            })

        total_pages = max(1, math.ceil(total / per_page))
        return {
            "users": users,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

