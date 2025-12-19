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

# ================== LOG FORWARDING (Command se set kar sakta hai) ==================
LOG_SETTINGS_FILE = "log_settings.json"

log_bot = None
log_chat_id = None

def load_log_settings():
    global log_bot, log_chat_id
    if os.path.exists(LOG_SETTINGS_FILE):
        try:
            with open(LOG_SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                token = data.get('token')
                chat_id = data.get('chat_id')
                if token and chat_id:
                    log_bot = Bot(token=token)
                    log_chat_id = int(chat_id)
                    logging.info("Log forwarding settings loaded from file.")
        except Exception as e:
            logging.error(f"Log settings load error: {e}")

def save_log_settings(token=None, chat_id=None):
    data = {}
    if os.path.exists(LOG_SETTINGS_FILE):
        try:
            with open(LOG_SETTINGS_FILE, 'r') as f:
                data = json.load(f)
        except:
            pass
    if token is not None:
        data['token'] = token
    if chat_id is not None:
        data['chat_id'] = str(chat_id)
    with open(LOG_SETTINGS_FILE, 'w') as f:
        json.dump(data, f)

class TelegramLogger(logging.Handler):
    def emit(self, record):
        if log_bot is None or log_chat_id is None:
            return
        try:
            log_entry = self.format(record)
            if len(log_entry) > 4090:
                log_entry = log_entry[:4090] + "..."
            asyncio.create_task(
                log_bot.send_message(
                    chat_id=log_chat_id,
                    text=f"<code>{log_entry}</code>",
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
            )
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('instagram_bot.log'),
        logging.StreamHandler(),
        TelegramLogger()
    ]
)

load_log_settings()

# ================== LOG SETTINGS COMMANDS ==================
async def setlogtoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TG_ID:
        await update.message.reply_text("⚠️ Only owner!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setlogtoken <bot_token>")
        return
    token = context.args[0]
    global log_bot
    try:
        log_bot = Bot(token=token)
        await log_bot.send_message(chat_id=OWNER_TG_ID, text="✅ Log token test OK!")
        save_log_settings(token=token)
        await update.message.reply_text("✅ Log token set & tested!")
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid token: {e}")

async def setlogchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TG_ID:
        await update.message.reply_text("⚠️ Only owner!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setlogchat <chat_id>")
        return
    try:
        chat_id = int(context.args[0])
        global log_chat_id
        log_chat_id = chat_id
        save_log_settings(chat_id=chat_id)
        await update.message.reply_text(f"✅ Log chat set to {chat_id}")
        if log_bot:
            await log_bot.send_message(chat_id=chat_id, text="✅ Logs yahan aayenge ab!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def viewlogsettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TG_ID:
        return
    token_status = "Set" if log_bot else "Not set"
    chat_status = log_chat_id if log_chat_id else "Not set"
    await update.message.reply_text(f"Log Settings:\nToken: {token_status}\nChat ID: {chat_status}")

# ================== RESTORE TASKS ==================
def restore_tasks_on_start():
    global users_tasks, persistent_tasks
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, 'r') as f:
                loaded = json.load(f)
                persistent_tasks = loaded.get('persistent', [])
                users_tasks = loaded.get('users', {})
            logging.info("Tasks restored")
        else:
            logging.info("Fresh start - no tasks.json")
    except Exception as e:
        logging.error(f"Restore error: {e}")

# ================== /RESTART COMMAND ==================
async def restart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TG_ID:
        await update.message.reply_text("⚠️ Only owner!")
        return
    await update.message.reply_text("🔄 Restarting bot...")
    try:
        os.system("screen -S lol3bot -X quit > /dev/null 2>&1")
        restart_cmd = "cd /home/ubuntu/testing && screen -dmS lol3bot bash vpssetup.sh"
        subprocess.Popen(restart_cmd, shell=True)
        await update.message.reply_text("✅ New bot started!")
        os._exit(0)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ================== MAIN BOT ==================
def main_bot():
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connect_timeout=60, read_timeout=60, write_timeout=60)
    
    # Application define kar pehle
    application = Application.builder().token(BOT_TOKEN).request(request).build()
    global APP
    APP = application

    # Tasks restore
    restore_tasks_on_start()

    # Switch monitor if exists
    try:
        monitor_thread = threading.Thread(target=switch_monitor, daemon=True)
        monitor_thread.start()
    except NameError:
        pass

    # Post init
    async def post_init(app):
        try:
            for user_id, tasks_list in list(users_tasks.items()):
                for task in tasks_list:
                    if task.get('type') == 'message_attack' and task['status'] == 'running':
                        await send_resume_notification(user_id, task)
        except:
            pass
    application.post_init = post_init

    # Ab sab handlers add kar (application define hone ke baad)
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
    application.add_handler(CommandHandler("restart", restart_handler))
    
    # Log settings commands
    application.add_handler(CommandHandler("setlogtoken", setlogtoken))
    application.add_handler(CommandHandler("setlogchat", setlogchat))
    application.add_handler(CommandHandler("viewlogsettings", viewlogsettings))

    # Conversation handlers jo pehle the (add kar dena)
    # application.add_handler(conv_login) etc.

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logging.info("🚀 Bot started successfully – Log forwarding command se set kar sakta hai!")
    print("Bot running... Use /setlogtoken and /setlogchat later.")
    application.run_polling()

if __name__ == "__main__":
    main_bot()
