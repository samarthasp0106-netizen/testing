import argparse
import json
import os
import time
import random
import logging
import unicodedata
import sqlite3
import re
import subprocess
import sys
from playwright.sync_api import sync_playwright
import urllib.parse
import pty
import errno
from typing import Dict, List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import threading
import uuid
import signal
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
import asyncio
from dotenv import load_dotenv
from playwright_stealth import stealth_sync
from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, TwoFactorRequired, PleaseWaitFewMinutes, RateLimitError, LoginRequired
import psutil
from queue import Queue, Empty

load_dotenv()

# ================== LOG FORWARDING SETUP ==================
LOG_BOT_TOKEN = "YOUR_SECOND_BOT_TOKEN_HERE"  # Dusra bot ka token daal (ya same bot ka)
LOG_CHAT_ID = 123456789  # Apna TG ID ya private group ID jahan logs jaayenge

log_bot = Bot(token=LOG_BOT_TOKEN)

class TelegramLogger(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            if len(log_entry) > 4090:
                log_entry = log_entry[:4090] + "..."
            asyncio.create_task(
                log_bot.send_message(
                    chat_id=LOG_CHAT_ID,
                    text=f"<code>{log_entry}</code>",
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
            )
        except Exception:
            pass  # Agar bot down ho to ignore

# Logging setup with Telegram forwarding
logging.basicConfig(
    level=logging.INFO,  # DEBUG se INFO kiya taaki spam na ho, change kar sakta hai
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('instagram_bot.log'),
        logging.StreamHandler(),
        TelegramLogger()  # Ye add kiya logs Telegram pe bhejne ke liye
    ]
)

# Baki variables same
user_fetching = set()
user_cancel_fetch = set()
AUTHORIZED_FILE = 'authorized_users.json'
TASKS_FILE = 'tasks.json'
OWNER_TG_ID = int(os.environ.get('OWNER_TG_ID'))
BOT_TOKEN = os.environ.get('BOT_TOKEN')
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

authorized_users = []
users_data: Dict[int, Dict] = {}
users_pending: Dict[int, Dict] = {}
users_tasks: Dict[int, List[Dict]] = {}
persistent_tasks = []
running_processes: Dict[int, subprocess.Popen] = {}
waiting_for_otp = {}
user_queues = {}
user_fetching = set()

os.makedirs('sessions', exist_ok=True)

# ... (baki saara code jo pehle tha – functions, patches wagera same rahega)

# ================== RESTART COMMAND ==================
async def restart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != OWNER_TG_ID:
        await update.message.reply_text("⚠️ Sirf owner hi /restart kar sakta hai! ⚠️")
        return

    await update.message.reply_text("🔄 Bot restart ho raha hai...\nOld process band + naya background mein start kar raha hu.")

    try:
        # Old screen session kill
        os.system("screen -S lol3bot -X quit > /dev/null 2>&1")

        # Naya session start (path change kar apne hisaab se)
        restart_cmd = "cd /root/lol3 && screen -dmS lol3bot bash vpssetup.sh"
        subprocess.Popen(restart_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        await update.message.reply_text("✅ Naya bot successfully background mein start ho gaya!\nMain band ho raha hu...")

        # Current process exit
        os._exit(0)

    except Exception as e:
        await update.message.reply_text(f"❌ Restart fail: {str(e)}")
        logging.error(f"Restart error: {e}")

# ================== MAIN BOT SETUP ==================
def main_bot():
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    application = Application.builder().token(BOT_TOKEN).request(request).build()
    global APP, LOOP
    APP = application
    LOOP = asyncio.get_event_loop()
    
    restore_tasks_on_start()
    
    monitor_thread = threading.Thread(target=switch_monitor, daemon=True)
    monitor_thread.start()
    
    async def post_init(app):
        for user_id, tasks_list in list(users_tasks.items()):
            for task in tasks_list:
                if task.get('type') == 'message_attack' and task['status'] == 'running':
                    await send_resume_notification(user_id, task)
    
    application.post_init = post_init

    # Sab handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("viewmyac", viewmyac))
    application.add_handler(CommandHandler("setig", setig))
    application.add_handler(CommandHandler("pair", pair_command))
    application.add_handler(CommandHandler("unpair", unpair_command))
    application.add_handler(CommandHandler("switch", switch_command))
    application.add_handler(CommandHandler("threads", threads_command))
    application.add_handler(CommandHandler("viewpref", viewpref))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("task", task_command))
    application.add_handler(CommandHandler("add", add_user))
    application.add_handler(CommandHandler("remove", remove_user))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("logout", logout_command))
    application.add_handler(CommandHandler("kill", cmd_kill))
    application.add_handler(CommandHandler("flush", flush))
    application.add_handler(CommandHandler("usg", usg_command))
    application.add_handler(CommandHandler("cancel", cancel_handler))
    
    # NAYA: Restart command
    application.add_handler(CommandHandler("restart", restart_handler))

    # Conversation handlers same...
    conv_login = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_username)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_password)],
        },
        fallbacks=[],
    )
    application.add_handler(conv_login)

    # ... (baki conv_plogin, conv_slogin, conv_attack wagera same jaise pehle the)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🚀 Instagram Spamming Bot started ")
    logging.info("Bot successfully started with new features.")
    application.run_polling()

if __name__ == "__main__":
    main_bot()