import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta

reminders = {}

@commands.command()
async def remind(ctx, waktu: str, *, pesan: str):
    """Contoh: rem! 17:00 olahraga atau !remind 08:30 drink water"""
    try:
        jam, menit = map(int, waktu.split(":"))
        now = datetime.now()
        target = now.replace(hour=jam, minute=menit, second=0, microsecond=0)

        if target < now:
            target += timedelta(days=1)

        selisih = (target - now).total_seconds()

        await ctx.send(f"✅ Reminder diset untuk {target.strftime('%H:%M')} - Pesan: '{pesan}'")

        await asyncio.sleep(selisih)
        await ctx.send(f"⏰ {ctx.author.mention} Reminder: {pesan}")

    except ValueError:
        await ctx.send("⚠️ Format salah! Gunakan `rem! HH:MM pesan`")

async def setup(bot):
    bot.add_command(remind)
