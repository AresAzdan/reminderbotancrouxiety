import os
import json
import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, time
import pytz
from flask import Flask
from threading import Thread

# --- KONFIGURASI ---
TOKEN = os.environ.get('reminder_bot')  # Ambil token dari Secrets
TIMEZONE = pytz.timezone('Asia/Jakarta')
DATA_FILE = "reminders.json"

# --- INTENTS & SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=['rem!', 'Rem!', 'REM!'],
                   intents=intents,
                   case_insensitive=True,
                   help_command=None)

# --- DATA ---
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        scheduled_reminders = json.load(f)
else:
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


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(scheduled_reminders, f, indent=2)


# --- EVENT ---
@bot.event
async def on_ready():
    check_scheduled_reminders.start()
    print(f"✅ Bot sudah online sebagai {bot.user}")


# --- LOOP REMINDER ---
@tasks.loop(minutes=1)
async def check_scheduled_reminders():
    now = datetime.now(TIMEZONE)
    current_time = now.time().replace(second=0, microsecond=0)
    current_day = now.weekday()

    for guild_id, reminders in scheduled_reminders.items():
        for key, reminder in reminders.items():
            jam = reminder["jam"]
            menit = reminder["menit"]
            pesan = reminder["pesan"]
            channel_id = reminder["channel_id"]
            hari = [DAY_MAP.get(d.lower(), -1) for d in reminder["hari"]]

            if current_time.hour == jam and current_time.minute == menit and current_day in hari:
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"⏰ **[REMINDER]** Sudah waktunya: **{pesan}**")


# --- COMMANDS ---
@bot.command(name="rem")
async def reminder(ctx, waktu_hari, *, pesan: str):
    """Buat reminder baru"""
    guild_id = str(ctx.guild.id)
    channel_id = ctx.channel.id

    try:
        waktu_split = waktu_hari.split(',')
        waktu = waktu_split[0]
        jam, menit = map(int, waktu.split(':'))
        hari = waktu_split[1:] if len(waktu_split) > 1 else ["senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu"]
    except:
        await ctx.send("❌ Format salah. Contoh: `rem!rem 08:30,senin,rabu minum air`")
        return

    if guild_id not in scheduled_reminders:
        scheduled_reminders[guild_id] = {}

    reminder_id = str(len(scheduled_reminders[guild_id]) + 1)
    scheduled_reminders[guild_id][reminder_id] = {
        "jam": jam,
        "menit": menit,
        "pesan": pesan,
        "channel_id": channel_id,
        "hari": hari
    }
    save_data()
    await ctx.send(f"✅ Reminder ditambahkan: **{pesan}** pada **{waktu_hari}**")


@bot.command(name="list")
async def list_reminders(ctx):
    """Lihat semua reminder"""
    guild_id = str(ctx.guild.id)
    if guild_id not in scheduled_reminders or not scheduled_reminders[guild_id]:
        await ctx.send("📭 Tidak ada reminder aktif.")
        return

    pesan = "🗓 **Daftar Reminder:**\n"
    for i, (key, r) in enumerate(scheduled_reminders[guild_id].items(), start=1):
        hari_text = ','.join(r['hari'])
        pesan += f"{i}. {r['pesan']} - {r['jam']:02d}:{r['menit']:02d} ({hari_text})\n"

    await ctx.send(pesan)


@bot.command(name="edit")
async def edit_reminder(ctx, nomor: int, waktu_hari, *, pesan_baru: str):
    """Ubah reminder"""
    guild_id = str(ctx.guild.id)
    if guild_id not in scheduled_reminders or not scheduled_reminders[guild_id]:
        await ctx.send("❌ Tidak ada reminder untuk diedit.")
        return

    try:
        reminder_key = list(scheduled_reminders[guild_id].keys())[nomor - 1]
    except IndexError:
        await ctx.send("❌ Nomor reminder tidak ditemukan.")
        return

    waktu_split = waktu_hari.split(',')
    waktu = waktu_split[0]
    jam, menit = map(int, waktu.split(':'))
    hari = waktu_split[1:] if len(waktu_split) > 1 else ["senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu"]

    scheduled_reminders[guild_id][reminder_key].update({
        "jam": jam,
        "menit": menit,
        "pesan": pesan_baru,
        "hari": hari
    })
    save_data()
    await ctx.send(f"✏️ Reminder {nomor} diperbarui jadi: **{pesan_baru}** pada **{waktu_hari}**")


@bot.command(name="hapus", aliases=["del", "delete"])
async def delete_reminder(ctx, nomor: int):
    """Hapus reminder"""
    guild_id = str(ctx.guild.id)
    if guild_id not in scheduled_reminders or not scheduled_reminders[guild_id]:
        await ctx.send("❌ Tidak ada reminder untuk dihapus.")
        return

    try:
        reminder_key = list(scheduled_reminders[guild_id].keys())[nomor - 1]
        del scheduled_reminders[guild_id][reminder_key]
        save_data()
        await ctx.send(f"🗑 Reminder {nomor} telah dihapus.")
    except IndexError:
        await ctx.send("❌ Nomor reminder tidak ditemukan.")


@bot.command(name="bantuan", aliases=["help"])
async def help_command(ctx):
    """Tampilkan panduan"""
    teks = (
        "📝 **Panduan ReminderBot**\n"
        "`rem!rem <WAKTU> <PESAN>` - buat reminder\n"
        "`rem!rem 08:30,senin,rabu minum air`\n"
        "`rem!list` - lihat semua reminder\n"
        "`rem!edit <NOMOR> <WAKTU,HARI> <PESAN>`\n"
        "`rem!hapus <NOMOR>` - hapus reminder\n"
    )
    await ctx.send(teks)


# --- FLASK KEEP ALIVE (untuk Render/Replit) ---
app = Flask('')


@app.route('/')
def home():
    return "Bot is alive!"


def run():
    app.run(host='0.0.0.0', port=5000)


def keep_alive():
    Thread(target=run).start()


# --- JALANKAN ---
keep_alive()
bot.run(TOKEN)
