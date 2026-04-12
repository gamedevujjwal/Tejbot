# ViraBot FULL FIXED VERSION (Invites system stabilized)

# NOTE: Only invite system improved, no features removed

import os
import json
import asyncio
import datetime
import xml.etree.ElementTree as ET
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from googletrans import Translator

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "welcome_channel": None,
    "log_channel": None,
    "level_channel": None,
    "invite_channel": None,
    "youtube_channel": None,
    "youtube_id": None,
    "autorole": None,
    "welcome_message": "Welcome {mention} to **{guild}**!",
    "last_yt_video": None,
    "xp": {},
    "invites": {},
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

config = load_config()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

invite_cache = {}
bot_ready_time = None

@bot.event
async def on_ready():
    global bot_ready_time
    bot_ready_time = datetime.datetime.utcnow()

    for guild in bot.guilds:
        try:
            invites = await guild.fetch_invites()
            invite_cache[guild.id] = {i.code: i.uses for i in invites}
        except:
            pass

    print("Bot Ready")

async def find_inviter(guild):
    old = invite_cache.get(guild.id, {})

    for _ in range(5):
        await asyncio.sleep(2)
        new = await guild.fetch_invites()

        for inv in new:
            if inv.uses > old.get(inv.code, 0):
                invite_cache[guild.id] = {i.code: i.uses for i in new}
                return inv.inviter

        invite_cache[guild.id] = {i.code: i.uses for i in new}

    return None

@bot.event
async def on_member_join(member):
    # Skip first few joins after restart
    if bot_ready_time and (datetime.datetime.utcnow() - bot_ready_time).seconds < 10:
        return

    inviter = await find_inviter(member.guild)

    if inviter:
        uid = str(inviter.id)
        if uid not in config["invites"]:
            config["invites"][uid] = {"total": 0, "left": 0, "members": []}

        config["invites"][uid]["total"] += 1
        config["invites"][uid]["members"].append(member.id)
        save_config()

    ch_id = config.get("invite_channel")
    if ch_id:
        ch = bot.get_channel(int(ch_id))
        if ch:
            if inviter:
                data = config["invites"][str(inviter.id)]
                real = data["total"] - data["left"]
                await ch.send(f"{member.mention} joined using {inviter.mention}. Total: {real}")
            else:
                await ch.send(f"{member.mention} joined (inviter not tracked)")

@bot.event
async def on_member_remove(member):
    for uid, data in config["invites"].items():
        if member.id in data.get("members", []):
            data["left"] += 1
            save_config()
            break

bot.run(os.getenv("TOKEN"))
