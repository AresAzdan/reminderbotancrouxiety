# main.py
import os
import re
import json
import aiosqlite
import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta, time as dt_time
import pytz
from flask import Flask
from threading import Thread
app = Flask(__name__) 
# -----------------------
# Konfigurasi
# -----------------------
TOKEN = os.environ.get("reminder_bot")  # nama env var sesuai kesepakatan
TZ = pytz.timezone("Asia/Jakarta")
DB_FILE = "reminders.db"

# -----------------------
# Intents & Bot setup
# -----------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=["rem!", "Rem!", "REM!"],
                   intents=intents,
                   case_insensitive=True,
                   help_command=None)

# -----------------------
# Helper: month + weekday maps
# -----------------------
MONTH_MAP = {
    # English full
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    # English abbr
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    # Indonesian full
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    # Indonesian abbr variations
    "janv":1, "okt": 10, "okt.": 10, "des": 12, "sept":9, "oktober":10, "okt":10, "okt.":10
}

WEEKDAY_MAP = {
    "monday": 0, "mon": 0, "senin": 0,
    "tuesday": 1, "tue": 1, "selasa": 1,
    "wednesday": 2, "wed": 2, "rabu": 2,
    "thursday": 3, "thu": 3, "kamis": 3,
    "friday": 4, "fri": 4, "jumat": 4, "jum":4,
    "saturday": 5, "sat": 5, "sabtu": 5,
    "sunday": 6, "sun": 6, "minggu": 6
}

# -----------------------
# DB helpers (aiosqlite)
# -----------------------
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                dt_iso TEXT,            -- for one-time reminders (ISO in TZ)
                hour INTEGER,           -- for weekly reminders
                minute INTEGER,         -- for weekly reminders
                weekdays TEXT,          -- JSON list of ints for weekly reminders
                repeat INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()

async def add_one_time(guild_id, channel_id, user_id, message, dt_iso):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO reminders (guild_id, channel_id, user_id, message, dt_iso, repeat, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (str(guild_id), channel_id, user_id, message, dt_iso, datetime.now(TZ).isoformat()))
        await db.commit()

async def add_weekly(guild_id, channel_id, user_id, message, hour, minute, weekdays):
    wd_json = json.dumps(weekdays)
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO reminders (guild_id, channel_id, user_id, message, hour, minute, weekdays, repeat, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (str(guild_id), channel_id, user_id, message, hour, minute, wd_json, datetime.now(TZ).isoformat()))
        await db.commit()

async def fetch_due_one_time(now_iso):
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT id, guild_id, channel_id, user_id, message FROM reminders WHERE dt_iso = ? AND repeat = 0", (now_iso,))
        rows = await cur.fetchall()
        return rows

async def delete_reminder_by_id(rid):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM reminders WHERE id = ?", (rid,))
        await db.commit()

async def fetch_weekly_for_time(hour, minute, weekday):
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT id, guild_id, channel_id, user_id, message, weekdays FROM reminders WHERE repeat = 1 AND hour = ? AND minute = ?", (hour, minute))
        rows = await cur.fetchall()
        result = []
        for r in rows:
            rid, guild_id, channel_id, user_id, message, weekdays_json = r
            wds = json.loads(weekdays_json)
            if weekday in wds:
                result.append((rid, guild_id, channel_id, user_id, message))
        return result

# -----------------------
# Parsing input
# -----------------------
time_regex = re.compile(r'(?P<h>\d{1,2}):(?P<m>\d{2})')

def extract_time(text):
    m = time_regex.search(text)
    if not m:
        return None, text
    h = int(m.group('h')) % 24
    minute = int(m.group('m')) % 60
    # remove the time token from text
    new_text = (text[:m.start()] + text[m.end():]).strip()
    return (h, minute), new_text

def find_month_in_tokens(tokens):
    for i, t in enumerate(tokens):
        key = t.lower().strip(",. ")
        if key in MONTH_MAP:
            return i, key
    return None, None

def parse_date_flexible(text):
    """
    Returns:
      - ('one_time', dt) with tz-aware datetime in TZ
      - ('weekly', [weekday_ints], hour, minute)
      - ('time_only', hour, minute)
      - None on fail
    Acceptable input examples:
      "10 Oktober 17:00", "Oktober 10 17:00", "17:00 10/10", "senin 17:00", "senin,rabu 08:30"
    """
    text = text.strip()
    # normalize commas
    text = text.replace("/", " ").replace("-", " ").replace(".", " ")
    tokens = text.split()
    # extract time first
    time_part, rest = extract_time(text)
    # rest tokens:
    rest_tokens = rest.split()
    # if rest contains weekday words
    weekdays = []
    for t in rest_tokens:
        key = t.lower().strip(",")
        if key in WEEKDAY_MAP:
            weekdays.append(WEEKDAY_MAP[key])
    if weekdays:
        if time_part:
            return ("weekly", weekdays, time_part[0], time_part[1])
        else:
            return None  # need a time with weekday
    # try to find month name
    idx, month_key = find_month_in_tokens(rest_tokens)
    if idx is not None:
        # expect day near it (either before or after)
        # try day before
        day = None
        month = MONTH_MAP[month_key]
        # look left
        if idx - 1 >= 0:
            try:
                day_candidate = int(re.sub(r'\D','', rest_tokens[idx-1]))
                day = day_candidate
            except:
                day = None
        # look right
        if day is None and idx + 1 < len(rest_tokens):
            try:
                day_candidate = int(re.sub(r'\D','', rest_tokens[idx+1]))
                day = day_candidate
            except:
                day = None
        if day is None:
            return None
        # build datetime
        now = datetime.now(TZ)
        year = now.year
        dt = TZ.localize(datetime(year, month, day, *(time_part if time_part else (0,0))))
        # if in past, bump year
        if dt < now:
            try:
                dt = TZ.localize(datetime(year+1, month, day, *(time_part if time_part else (0,0))))
            except:
                pass
        return ("one_time", dt)
    # try numeric date like day month as numbers (e.g., 10 11)
    nums = [int(t) for t in rest_tokens if t.isdigit()]
    if nums:
        # heuristics: if len(nums) >=1 and time exists -> treat first numeric as day
        if time_part and nums:
            day = nums[0]
            # try to find month from remaining tokens or default to current month
            month = datetime.now(TZ).month
            now = datetime.now(TZ)
            try:
                dt = TZ.localize(datetime(now.year, month, day, time_part[0], time_part[1]))
                if dt < now:
                    dt = TZ.localize(datetime(now.year+1, month, day, time_part[0], time_part[1]))
                return ("one_time", dt)
            except:
                pass
    # if only time provided -> schedule today or tomorrow if time passed
    if time_part and not rest_tokens:
        now = datetime.now(TZ)
        h, m = time_part
        dt = TZ.localize(datetime(now.year, now.month, now.day, h, m))
        if dt < now:
            dt = dt + timedelta(days=1)
        return ("one_time", dt)
    return None

# -----------------------
# Background checker
# -----------------------
@tasks.loop(minutes=1)
async def check_reminders_loop():
    now = datetime.now(TZ)
    # check one-time that match current minute
    now_iso = now.replace(second=0, microsecond=0).isoformat()
    rows = await fetch_due_one_time(now_iso)
    for r in rows:
        rid, guild_id, channel_id, user_id, message = r
        guild = bot.get_guild(int(guild_id))
        if not guild:
            await delete_reminder_by_id(rid)
            continue
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(f"⏰ <@{user_id}> {message}")
        await delete_reminder_by_id(rid)
    # check weekly
    hour = now.hour
    minute = now.minute
    weekday = now.weekday()
    weekly_rows = await fetch_weekly_for_time(hour, minute, weekday)
    for rid, guild_id, channel_id, user_id, message in weekly_rows:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(f"⏰ <@{user_id}> {message}")

# -----------------------
# Commands
# -----------------------
@bot.command(name="rem")
async def cmd_rem(ctx, *, rest: str):
    """
    Usage:
    rem!rem 08:30 minum air
    rem!rem 10 Oktober 18:00 ulang tahun
    rem!rem senin 08:00 olahraga
    rem!rem 08:30,senin,rabu minum air
    """
    if ctx.guild is None:
        await ctx.send("❌ Gunakan di server (tidak di DM).")
        return

# Parsing waktu dulu
parsed = parse_date_flexible(rest)
if not parsed:
    # --- Tambahan: deteksi jam saja ---
    import re
    from datetime import datetime, timedelta
    import pytz
    
    tz = pytz.timezone("Asia/Jakarta")
    now = datetime.now(tz)
    
    time_only = re.search(r'(\d{1,2})[:.](\d{2})', rest)
    if time_only:
        hour, minute = map(int, time_only.groups())
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at < now:
            at += timedelta(days=1)
        message = rest[time_only.end():].strip()
        kind = "one_time"
    # ✅ Tambahan penting — tandai parsed agar sistem tahu parsing berhasil
        parsed = (kind, at, message)
        else:
          await ctx.send("❌ Gagal mengenali waktu. Contoh: 'rem!rem 18 Oktober 20:00 meeting'")
          return
      
    if len(parsed) == 3:
       at, kind, message = parsed
    elif len(parsed) == 2:
        at, kind = parsed
        message = None
          else:
            await ctx.send("Format perintah salah. Gunakan: rem!rem [waktu] [pesan]")
            return


        # Cari posisi terakhir waktu/tanggal agar sisa teks jadi pesan
        match = time_regex.search(rest)
        cut_index = match.end() if match else 0

        # Tambah pencarian nama bulan
        for month_name in MONTH_MAP.keys():
            idx = re.search(rf"\b{month_name}\b", rest, re.IGNORECASE)
            if idx:
                cut_index = max(cut_index, idx.end())

        # Ambil sisa kalimat setelah waktu/bulan
        message = rest[cut_index:].strip()
        if not message:
            message = "(tanpa pesan)"

        kind = parsed[0]
        if kind == "one_time":
            dt = parsed[1]
            await add_one_time(
                ctx.guild.id,
                ctx.channel.id,
                ctx.author.id,
                message,
                dt.replace(second=0, microsecond=0).isoformat(),
            )
            human = dt.astimezone(TZ).strftime("%d %b %Y %H:%M")
            await ctx.send(f"✅ Reminder sekali diset untuk **{human}** — {message}")
        elif kind == "weekly":
            _, wds, h, m = parsed
            await add_weekly(
                ctx.guild.id,
                ctx.channel.id,
                ctx.author.id,
                message,
                h,
                m,
                wds,
            )
            days_str = ", ".join(
                [
                    list(WEEKDAY_MAP.keys())[list(WEEKDAY_MAP.values()).index(d)]
                    for d in wds
                ]
            ) if wds else "N/A"
            await ctx.send(
                f"🔁 Reminder berulang diset setiap **{days_str}** jam **{h:02d}:{m:02d}** — {message}"
            )
        else:
            await ctx.send("❌ Format tidak dikenali.")

@bot.command(name="list", aliases=["show","all"])
async def cmd_list(ctx):
    if ctx.guild is None:
        await ctx.send("❌ Gunakan di server.")
        return
    guild_id = str(ctx.guild.id)
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT id, message, dt_iso, hour, minute, weekdays, repeat FROM reminders WHERE guild_id = ?", (guild_id,))
        rows = await cur.fetchall()
    if not rows:
        await ctx.send("📭 Tidak ada reminder aktif.")
        return
    lines = []
    for r in rows:
        rid, message, dt_iso, hour, minute, weekdays_json, repeat = r
        if repeat == 0 and dt_iso:
            dt = datetime.fromisoformat(dt_iso).astimezone(TZ)
            lines.append(f"{rid}. (once) {message} — {dt.strftime('%d %b %Y %H:%M')}")
        else:
            wds = json.loads(weekdays_json) if weekdays_json else []
            lines.append(f"{rid}. (weekly) {message} — {hour:02d}:{minute:02d} on {wds}")
    await ctx.send("🗒️ Daftar reminder:\n" + "\n".join(lines))

@bot.command(name="edit")
async def cmd_edit(ctx, rid: int, *, rest: str):
    if ctx.guild is None:
        await ctx.send("❌ Gunakan di server.")
        return
    # get existing
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT id FROM reminders WHERE id = ? AND guild_id = ?", (rid, str(ctx.guild.id)))
        row = await cur.fetchone()
    if not row:
        await ctx.send("❌ Reminder tidak ditemukan.")
        return
    # expect rest like: "10 Oktober 18:00 pesan baru" or "08:30,senin new msg"
    parts = rest.strip().split(maxsplit=1)
    if not parts:
        await ctx.send("❌ Format salah.")
        return
    parser_input = parts[0]
    new_message = parts[1] if len(parts) > 1 else ""
    if "," in parser_input:
        toks = parser_input.split(",")
        time_token = toks[0]
        extra_days = toks[1:]
        parser_input_full = time_token + " " + " ".join(extra_days)
    else:
        parser_input_full = rest
    parsed = parse_date_flexible(parser_input_full)
    if not parsed:
        await ctx.send("❌ Gagal mengenali waktu.")
        return
    if parsed[0] == "one_time":
        dt = parsed[1].replace(second=0, microsecond=0).isoformat()
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("UPDATE reminders SET dt_iso = ?, hour = NULL, minute = NULL, weekdays = NULL, repeat = 0, message = ? WHERE id = ?",
                             (dt, new_message, rid))
            await db.commit()
        await ctx.send(f"✏️ Reminder {rid} diperbarui ke {dt} — {new_message}")
    else:  # weekly
        _, wds, h, m = parsed
        wd_json = json.dumps(wds)
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("UPDATE reminders SET dt_iso = NULL, hour = ?, minute = ?, weekdays = ?, repeat = 1, message = ? WHERE id = ?",
                             (h, m, wd_json, new_message, rid))
            await db.commit()
        await ctx.send(f"✏️ Reminder {rid} diperbarui ke weekly {wds} {h:02d}:{m:02d} — {new_message}")

@bot.command(name="hapus", aliases=["del","delete","remove"])
async def cmd_delete(ctx, rid: int):
    if ctx.guild is None:
        await ctx.send("❌ Gunakan di server.")
        return
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM reminders WHERE id = ? AND guild_id = ?", (rid, str(ctx.guild.id)))
        await db.commit()
    await ctx.send(f"🗑️ Reminder {rid} berhasil dihapus (kalau ada).")

@bot.command(name="bantuan", aliases=["help"])
async def cmd_help(ctx):
    teks = ("📝 **Panduan Reminder**\n"
            "`rem!rem <WAKTU/DATE> <PESAN>` contoh:\n"
            "`rem!rem 08:30 minum air`\n"
            "`rem!rem 10 Oktober 18:00 ulang tahun`\n"
            "`rem!rem senin 08:00 olahraga`\n"
            "`rem!list`\n"
            "`rem!edit <ID> <WAKTU/DATE> <PESAN>`\n"
            "`rem!hapus <ID>`\n")
    await ctx.send(teks)

# -----------------------
# Startup
# -----------------------
@app.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

def start_keep_alive():
    Thread(target=run_flask, daemon=True).start()

@bot.event
async def on_connect():
    # init DB on connect (ensures file exists before tasks start)
    await init_db()

@bot.event
async def on_ready():
    # start the check loop if not already running
    if not check_reminders_loop.is_running():
        check_reminders_loop.start()
    print(f"✅ Bot siap sebagai {bot.user}")

# start flask keep-alive and run bot
if __name__ == "__main__":
    start_keep_alive()
    if not TOKEN:
        print("❌ TOKEN tidak ditemukan. Pastikan env var 'reminder_bot' terpasang.")
    bot.run(TOKEN)
