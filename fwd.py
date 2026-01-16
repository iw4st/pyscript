import asyncio
import logging
import requests
import os

from telethon import TelegramClient, events
from telethon.tl.types import UpdateMessageReactions, ReactionEmoji
from telethon.errors import SlowModeWaitError

# ========= НАСТРОЙКИ через переменные окружения =========
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
session_name = "my_session"

TARGET_CHAT_ID = int(os.environ['TARGET_CHAT_ID'])
SOURCE_PEER = int(os.environ['SOURCE_PEER'])
INTERVAL_SECONDS = int(os.environ.get('INTERVAL_SECONDS', 310))

BOT_TOKEN = os.environ['BOT_TOKEN']
OWNER_ID = int(os.environ['OWNER_ID'])
# ========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)

logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger("TG")

stop_flag = False
reaction_cache = {}
bot_message_map = {}

# ===== BOT SEND =====
def send_bot_message(text: str):
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": OWNER_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=10
    ).json()
    return resp["result"]["message_id"]

def edit_bot_message(bot_msg_id: int, new_text: str):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
        json={
            "chat_id": OWNER_ID,
            "message_id": bot_msg_id,
            "text": new_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=10
    )

# ===== FORWARD LOOP =====
async def forward_loop(client: TelegramClient):
    logger.info("Цикл пересылки запущен")
    while not stop_flag:
        try:
            msgs = await client.get_messages(SOURCE_PEER, limit=1)
            if msgs:
                try:
                    await client.forward_messages(TARGET_CHAT_ID, msgs[0])
                    logger.info(f"Переслано сообщение {msgs[0].id}")
                except SlowModeWaitError as e:
                    logger.warning(f"Slow mode: ждём {e.seconds + 1} сек")
                    await asyncio.sleep(e.seconds + 1)
            await asyncio.sleep(INTERVAL_SECONDS)
        except Exception:
            logger.exception("Ошибка пересылки")
            await asyncio.sleep(INTERVAL_SECONDS)

# ===== MAIN =====
async def main():
    logger.info("Запуск клиента")
    client = TelegramClient(session_name, api_id, api_hash)
    await client.start()
    logger.info("Telegram подключён")

    @client.on(events.Raw)
    async def reaction_handler(event):
        if not isinstance(event, UpdateMessageReactions):
            return

        peer = event.peer
        if getattr(peer, "channel_id", None) != TARGET_CHAT_ID and getattr(peer, "chat_id", None) != TARGET_CHAT_ID:
            return

        chat = await client.get_entity(peer)
        msg_id = event.msg_id
        key = (chat.id, msg_id)

        old = reaction_cache.get(key, set())
        new = set()
        if event.reactions and event.reactions.recent_reactions:
            for r in event.reactions.recent_reactions:
                if not r.peer_id:
                    continue
                emoji = r.reaction.emoticon if isinstance(r.reaction, ReactionEmoji) else "❓"
                new.add((r.peer_id.user_id, emoji))

        added = new - old
        removed = old - new
        reaction_cache[key] = new

        message = await client.get_messages(chat, ids=msg_id)
        link = f"https://t.me/{chat.username}/{message.id}" if getattr(chat, "username", None) else f"tg://openmessage?chat_id={chat.id}&message_id={message.id}"

        for user_id, emoji in added:
            user = await client.get_entity(user_id)
            username = f"@{user.username}" if user.username else "нет user"
            text = f"🔥 <b>Реакция поставлена</b>\n\n👤 <b>Пользователь:</b> {username}\n🎭 <b>Реакция:</b> {emoji}\n\n🔗 <b>Сообщение:</b>\n{link}"
            bot_msg_id = send_bot_message(text)
            bot_message_map[(chat.id, msg_id, user_id, emoji)] = bot_msg_id

        for user_id, emoji in removed:
            map_key = (chat.id, msg_id, user_id, emoji)
            bot_msg_id = bot_message_map.get(map_key)
            if not bot_msg_id:
                continue
            user = await client.get_entity(user_id)
            username = f"@{user.username}" if user.username else "нет user"
            new_text = f"🔥 <b>Реакция поставлена</b>\n\n👤 <b>Пользователь:</b> {username}\n🎭 <b>Реакция:</b> {emoji} <b>(удалена)</b>\n\n🔗 <b>Сообщение:</b>\n{link}"
            edit_bot_message(bot_msg_id, new_text)

    asyncio.create_task(forward_loop(client))
    while not stop_flag:
        await asyncio.sleep(1)
    await client.disconnect()
    logger.info("Скрипт завершён")

if __name__ == "__main__":
    asyncio.run(main())
