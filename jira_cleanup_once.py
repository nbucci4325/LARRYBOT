"""
One-shot cleanup: scans the channel, keeps only the newest "Task Updated"
message per Jira task, deletes the older ones, then exits.
"New Task Created" messages are never deleted.

Designed to run on a schedule (GitHub Actions). Reads settings from
environment variables:
    DISCORD_TOKEN, CHANNEL_ID, BACKFILL_LIMIT (optional, default 500)
"""

import asyncio
import logging
import os
import re
import sys

import discord

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
BACKFILL_LIMIT = int(os.getenv("BACKFILL_LIMIT") or "500")

KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
UPDATE_MARKER = "task updated"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jira-cleanup-once")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

exit_code = 0


def update_key(message: discord.Message) -> str | None:
    """Jira key if this is a webhook 'Task Updated' message, else None."""
    if message.webhook_id is None:
        return None
    for embed in message.embeds:
        if embed.title and UPDATE_MARKER in embed.title.lower():
            m = KEY_RE.search(embed.title)
            if m:
                return m.group(1)
    return None


@client.event
async def on_ready():
    global exit_code
    try:
        channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(CHANNEL_ID)
        seen: set[str] = set()
        scanned = deleted = 0

        # Newest -> oldest: first update per key is the keeper, the rest are stale.
        async for msg in channel.history(limit=BACKFILL_LIMIT):
            scanned += 1
            key = update_key(msg)
            if key is None:
                continue
            if key not in seen:
                seen.add(key)
                continue
            try:
                await msg.delete()
                deleted += 1
                log.info("Deleted outdated update for %s (message %s)", key, msg.id)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                log.error("Missing Manage Messages permission in the channel")
                exit_code = 1
                break

        log.info("Done. Scanned %d messages, deleted %d, tracking %d tasks",
                 scanned, deleted, len(seen))
    except Exception:
        log.exception("Cleanup failed")
        exit_code = 1
    finally:
        await client.close()


client.run(TOKEN, log_handler=None)
sys.exit(exit_code)
