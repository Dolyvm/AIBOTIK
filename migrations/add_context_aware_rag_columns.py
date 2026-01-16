"""
Database migration: Add Context-Aware RAG System columns

This migration adds:
- state: JSON field for dynamic emotional states (affinity, arousal, mood)
- summary: Text field for compressed conversation history
- msgs_since_summary: Counter for triggering summarization

Run this migration after deploying the new code.
"""
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def migrate():
    """Run migration to add new columns to chats table"""

    database_url = os.getenv("DATABASE_URL", "postgresql://rpbot:password@localhost:5432/rpbot")

    # Convert to async URL
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(database_url, echo=True)

    async with engine.begin() as conn:
        print("Adding new columns to chats table...")

        # Add state column
        try:
            await conn.execute(text("""
                ALTER TABLE chats
                ADD COLUMN state TEXT DEFAULT '{"affinity": 0, "arousal": 0, "mood": "neutral"}'
            """))
            print("✓ Added 'state' column")
        except Exception as e:
            print(f"⚠ Column 'state' might already exist: {e}")

        # Add summary column
        try:
            await conn.execute(text("""
                ALTER TABLE chats
                ADD COLUMN summary TEXT DEFAULT ''
            """))
            print("✓ Added 'summary' column")
        except Exception as e:
            print(f"⚠ Column 'summary' might already exist: {e}")

        # Add msgs_since_summary column
        try:
            await conn.execute(text("""
                ALTER TABLE chats
                ADD COLUMN msgs_since_summary INTEGER DEFAULT 0
            """))
            print("✓ Added 'msgs_since_summary' column")
        except Exception as e:
            print(f"⚠ Column 'msgs_since_summary' might already exist: {e}")

        # Initialize existing chats with default values
        print("\nInitializing existing chats with default values...")
        await conn.execute(text("""
            UPDATE chats
            SET state = '{"affinity": 0, "arousal": 0, "mood": "neutral"}',
                summary = '',
                msgs_since_summary = 0
            WHERE state IS NULL OR summary IS NULL OR msgs_since_summary IS NULL
        """))
        print("✓ Initialized existing chats")

    await engine.dispose()
    print("\n✅ Migration completed successfully!")


async def rollback():
    """Rollback migration (remove columns)"""

    database_url = os.getenv("DATABASE_URL", "postgresql://rpbot:password@localhost:5432/rpbot")

    # Convert to async URL
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(database_url, echo=True)

    async with engine.begin() as conn:
        print("Rolling back migration...")

        try:
            await conn.execute(text("ALTER TABLE chats DROP COLUMN state"))
            print("✓ Removed 'state' column")
        except Exception as e:
            print(f"⚠ Error removing 'state': {e}")

        try:
            await conn.execute(text("ALTER TABLE chats DROP COLUMN summary"))
            print("✓ Removed 'summary' column")
        except Exception as e:
            print(f"⚠ Error removing 'summary': {e}")

        try:
            await conn.execute(text("ALTER TABLE chats DROP COLUMN msgs_since_summary"))
            print("✓ Removed 'msgs_since_summary' column")
        except Exception as e:
            print(f"⚠ Error removing 'msgs_since_summary': {e}")

    await engine.dispose()
    print("\n✅ Rollback completed!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        print("Running rollback...\n")
        asyncio.run(rollback())
    else:
        print("Running migration...\n")
        asyncio.run(migrate())
        print("\n" + "="*50)
        print("IMPORTANT: Restart your bot service after this migration!")
        print("="*50)
