import os
import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, time, timedelta
import pytz
from flask import Flask
from threading import Thread

# --- KONFIGURASI ---
TOKEN = os.environ.get('reminder_bot')  # Ambil token dari Secrets
TIMEZONE = pytz.timezone('Asia/Jakarta')

# --- INTENTS & SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=['rem!', 'Rem!', 'REM!'],
                   intents=intents,
                   case_insensitive=True,
                   help_command=None)

scheduled_reminders = {}
DAY_MAP = {
    "senin": 0,
    "selasa": 1,
    "rabu": 2,
    "kamis": 3,
    "jumat": 4,
    "sabtu": 5,
    "minggu": 6
}


# --- EVENT ---
@bot.event
async def on_ready():
    check_scheduled_reminders.start()
    print(f"Bot sudah online sebagai {bot.user}")


# --- LOOP REMINDER ---
@tasks.loop(minutes=1)
async def check_scheduled_reminders():
    now = datetime.now(TIMEZONE)
    current_time = now.time().replace(second=0, microsecond=0)
    current_day = now.weekday()

    for guild_id, reminders in scheduled_reminders.items():
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        for unique_key, (jam, menit, channel_id,
                         repeat_days_list) in reminders.items():
            target_time = time(jam, menit)
            if current_time == target_time and current_day in [
                    DAY_MAP.get(d.lower(), -1) for d in repeat_days_list
            ]:
                channel = guild.get_channel(channel_id)
                if channel:
                    pesan_asli = unique_key.rsplit('_', 1)[0]
                    await channel.send(
                        f"⏰ **[REMINDER]** Sudah waktunya: **{pesan_asli}**")


# --- FLASK KEEP ALIVE ---
app = Flask('')


@app.route('/')
def home():
    return "Bot is alive!"


def run():
    app.run(host='0.0.0.0', port=5000)


def keep_alive():
    Thread(target=run).start()


# --- COMMAND UTAMA (rem, list, edit, hapus, bantuan) ---
# (kode command kamu di sini tetap sama, tidak perlu diubah)
# ... salin semua command kamu tanpa ubah apapun ...

# --- JALANKAN ---
keep_alive()  # <--- INI WAJIB ADA
bot.run(TOKEN)
