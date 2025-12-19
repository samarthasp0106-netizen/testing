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

# ================== LOG FORWARDING (Dynamic - command se set hoga) ==================
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
                    logging.info("Log forwarding loaded from file.")
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
        data['chat_id'] = chat_id
    with open(LOG_SETTINGS_FILE, 'w') as f:
        json.dump(data, f)

class TelegramLogger(logging.Handler):
    def emit(self, record):
        if log_bot is None or log_chat_id is None:
            return  # Settings nahi hain to mat bhej
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

load_log_settings()  # Start pe load kar

# ================== LOG SETTINGS COMMANDS ==================
async def setlogtoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_TG_ID:
        await update.message.reply_text("⚠️ Only owner can set log token!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setlogtoken <bot_token>")
        return
    token = context.args[0]
    global log_bot
    try:
        log_bot = Bot(token=token)
        await log_bot.send_message(chat_id=OWNER_TG_ID, text="✅ Log bot token test successful!")
        save_log_settings(token=token)
        await update.message.reply_text("✅ Log bot token set aur test successful!")
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid token: {str(e)}")

async def setlogchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_TG_ID:
        await update.message.reply_text("⚠️ Only owner can set log chat!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setlogchat <chat_id>")
        return
    try:
        chat_id = int(context.args[0])
        global log_chat_id
        log_chat_id = chat_id
        save_log_settings(chat_id=chat_id)
        await update.message.reply_text(f"✅ Log chat ID set to {chat_id}")
        if log_bot:
            await log_bot.send_message(chat_id=chat_id, text="✅ Log forwarding activated here!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def viewlogsettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_TG_ID:
        return
    token_status = "Set" if log_bot else "Not set"
    chat_status = log_chat_id if log_chat_id else "Not set"
    await update.message.reply_text(
        f"📋 Log Settings:\n"
        f"Token: {token_status}\n"
        f"Chat ID: {chat_status}"
    )

# Baki variables aur functions same...

# ================== /RESTART COMMAND (Tera path) ==================
async def restart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != OWNER_TG_ID:
        await update.message.reply_text("⚠️ Only owner!")
        return
    await update.message.reply_text("🔄 Restarting...")
    try:
        os.system("screen -S lol3bot -X quit > /dev/null 2>&1")
        restart_cmd = "cd /home/ubuntu/testing && screen -dmS lol3bot bash vpssetup.sh"
        subprocess.Popen(restart_cmd, shell=True)
        await update.message.reply_text("✅ New instance started!")
        os._exit(0)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ================== MAIN BOT ==================
def main_bot():
    # ... (application setup same jaise pehle)

    # New log commands add
    application.add_handler(CommandHandler("setlogtoken", setlogtoken))
    application.add_handler(CommandHandler("setlogchat", setlogchat))
    application.add_handler(CommandHandler("viewlogsettings", viewlogsettings))

    # Restart aur baki sab handlers same

    # restore_tasks_on_start() call kar

    logging.info("Bot started – Log settings command se configure kar sakta hai!")
    application.run_polling()

if __name__ == "__main__":
    main_bot()
