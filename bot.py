import os
import json
import asyncio
import datetime
import xml.etree.ElementTree as ET
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from googletrans import Translator

# ══════════════════════════════════════════════════════════════════════════════
#  KEEP-ALIVE SERVER
# ══════════════════════════════════════════════════════════════════════════════

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ViraBot is alive!")
    def log_message(self, format, *args):
        pass

def run_server():
    server = HTTPServer(("0.0.0.0", 8080), PingHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  PER-SERVER CONFIG
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE = "config.json"

DEFAULT_GUILD_CONFIG: dict = {
    "welcome_channel":  None,
    "log_channel":      None,
    "level_channel":    None,
    "invite_channel":   None,
    "youtube_channel":  None,
    "youtube_id":       None,
    "autorole":         None,
    "welcome_message":  "Welcome {mention} to **{guild}**!",
    "last_yt_video":    None,
    "xp":               {},
    "invites":          {},
}

XP_PER_MESSAGE = 15
XP_BASE        = 100
XP_MULTIPLIER  = 1.5

# configs is a dict: { "guild_id_str": { ...config... } }
configs: dict[str, dict] = {}


def load_configs() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            # Detect old flat format (no guild IDs as keys) and migrate
            first_key = next(iter(data), None)
            if first_key and not first_key.isdigit():
                print("[Config] Old format detected, migrating to per-server format...")
                migrated = {
                    "1441672296870707337": data,
                    "1493934306643677244": {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_GUILD_CONFIG.items()},
                }
                return migrated
            # Fill missing keys for each guild
            for gid in data:
                for k, v in DEFAULT_GUILD_CONFIG.items():
                    data[gid].setdefault(k, v.copy() if isinstance(v, dict) else v)
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_configs() -> None:
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(configs, f, indent=2)
    except OSError as e:
        print(f"[SAVE ERROR] {e}")


def get_cfg(guild_id: int) -> dict:
    gid = str(guild_id)
    if gid not in configs:
        configs[gid] = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_GUILD_CONFIG.items()}
        save_configs()
    return configs[gid]


configs = load_configs()


def xp_for_level(level: int) -> int:
    return int(XP_BASE * (XP_MULTIPLIER ** (level - 1)))


def get_level(xp: int) -> int:
    level = 1
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_placeholder(text: str, member: discord.Member) -> str:
    return (
        text
        .replace("{mention}", member.mention)
        .replace("{user}",    str(member))
        .replace("{guild}",   member.guild.name)
    )


async def send_log(guild_id: int, embed: discord.Embed) -> None:
    cfg = get_cfg(guild_id)
    ch_id = cfg.get("log_channel")
    if not ch_id:
        return
    ch = bot.get_channel(int(ch_id))
    if ch:
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass


async def find_inviter(guild: discord.Guild) -> discord.User | None:
    old_cache = invite_cache.get(guild.id, {})
    print(f"[Invite] Old cache has {len(old_cache)} entries for {guild.name}")
    for attempt in range(3):
        await asyncio.sleep(2 + attempt * 2)
        try:
            new_invites = await guild.invites()
            print(f"[Invite] Attempt {attempt+1}: fetched {len(new_invites)} invites")
            for inv in new_invites:
                if inv.uses > old_cache.get(inv.code, 0):
                    print(f"[Invite] Found: code={inv.code} inviter={inv.inviter}")
                    invite_cache[guild.id] = {i.code: i.uses for i in new_invites}
                    return inv.inviter
            invite_cache[guild.id] = {i.code: i.uses for i in new_invites}
            print(f"[Invite] No changed invite found on attempt {attempt+1}")
        except Exception as e:
            print(f"[Invite] Attempt {attempt+1} failed: {e}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  INTENTS & BOT
# ══════════════════════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members         = True
intents.message_content = True
intents.invites         = True

bot        = commands.Bot(command_prefix="!", intents=intents)
tree       = bot.tree
translator = Translator()

invite_cache: dict[int, dict[str, int]] = {}


# ══════════════════════════════════════════════════════════════════════════════
#  YOUTUBE POLLING (per guild)
# ══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=5)
async def check_youtube():
    for guild in bot.guilds:
        cfg = get_cfg(guild.id)
        yt_id      = cfg.get("youtube_id")
        yt_ch_id   = cfg.get("youtube_channel")
        last_video = cfg.get("last_yt_video")

        if not yt_id or not yt_ch_id:
            continue

        channel = bot.get_channel(int(yt_ch_id))
        if not channel:
            continue

        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={yt_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()

            root  = ET.fromstring(text)
            ns    = {"atom": "http://www.w3.org/2005/Atom"}
            entry = root.find("atom:entry", ns)
            if entry is None:
                continue

            vid_id   = entry.find("yt:videoId", {"yt": "http://www.youtube.com/xml/schemas/2015"})
            title_el = entry.find("atom:title", ns)
            link_el  = entry.find("atom:link", ns)

            if vid_id is None:
                continue

            video_id  = vid_id.text
            title     = title_el.text if title_el is not None else "New Video"
            video_url = link_el.attrib.get("href", f"https://youtu.be/{video_id}") if link_el is not None else f"https://youtu.be/{video_id}"

            if video_id == last_video:
                continue

            cfg["last_yt_video"] = video_id
            save_configs()

            embed = discord.Embed(
                title=title,
                url=video_url,
                description="New video just dropped on the official Vira Arena YouTube channel!",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")
            embed.set_footer(text="ViraBot • YouTube")
            await channel.send(embed=embed)

        except Exception as e:
            print(f"[YouTube] Error for {guild.name}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await tree.sync()
    for guild in bot.guilds:
        get_cfg(guild.id)  # ensure config exists for each guild
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            print(f"[Invites] Cached {len(invites)} invites for {guild.name}")
        except Exception as e:
            print(f"[Invites] Failed to cache invites for {guild.name}: {e}")
    if not check_youtube.is_running():
        check_youtube.start()
    print(f"[ViraBot] Logged in as {bot.user} (ID: {bot.user.id})")
    print("[ViraBot] Ready.")


@bot.event
async def on_member_join(member: discord.Member):
    cfg = get_cfg(member.guild.id)

    autorole_id = cfg.get("autorole")
    if autorole_id:
        role = member.guild.get_role(int(autorole_id))
        if role:
            try:
                await member.add_roles(role, reason="ViraBot autorole")
            except discord.HTTPException as e:
                print(f"[Autorole] Failed: {e}")

    wc_id = cfg.get("welcome_channel")
    if wc_id:
        wc = member.guild.get_channel(int(wc_id))
        if wc:
            try:
                await wc.send(fmt_placeholder(cfg["welcome_message"], member))
            except discord.HTTPException:
                pass

    embed = discord.Embed(title="Member Joined", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User",        value=f"{member} (`{member.id}`)", inline=False)
    embed.add_field(name="Account Age", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=False)
    embed.set_footer(text=f"Member #{member.guild.member_count} • ViraBot")
    await send_log(member.guild.id, embed)

    bot.loop.create_task(handle_invite(member))


async def handle_invite(member: discord.Member):
    cfg     = get_cfg(member.guild.id)
    inviter = await find_inviter(member.guild)

    if inviter:
        uid = str(inviter.id)
        if uid not in cfg["invites"]:
            cfg["invites"][uid] = {"total": 0, "left": 0, "members": []}
        cfg["invites"][uid]["total"] += 1
        cfg["invites"][uid]["members"].append(member.id)
        save_configs()

    inv_ch_id = cfg.get("invite_channel")
    if not inv_ch_id:
        return
    inv_ch = bot.get_channel(int(inv_ch_id))
    if not inv_ch:
        return

    if inviter:
        uid  = str(inviter.id)
        data = cfg["invites"].get(uid, {"total": 0, "left": 0})
        real = data["total"] - data["left"]
        text = f"{member.mention} joined using {inviter.mention}'s invite. They now have **{real}** invite(s)."
    else:
        text = f"{member.mention} joined the server."

    try:
        await inv_ch.send(text)
    except discord.HTTPException:
        pass


@bot.event
async def on_member_remove(member: discord.Member):
    cfg = get_cfg(member.guild.id)
    for uid, data in cfg["invites"].items():
        if member.id in data.get("members", []):
            data["left"] = data.get("left", 0) + 1
            save_configs()
            break

    try:
        new_invites = await member.guild.invites()
        invite_cache[member.guild.id] = {inv.code: inv.uses for inv in new_invites}
    except Exception:
        pass

    embed = discord.Embed(title="Member Left", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
    embed.add_field(
        name="Joined",
        value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown",
        inline=False
    )
    embed.set_footer(text="ViraBot")
    await send_log(member.guild.id, embed)

    await asyncio.sleep(1)
    try:
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                e = discord.Embed(title="Member Kicked", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
                e.add_field(name="Kicked User", value=f"{member} (`{member.id}`)", inline=False)
                e.add_field(name="Moderator",   value=str(entry.user) if entry.user else "Unknown", inline=False)
                e.add_field(name="Reason",      value=entry.reason or "No reason provided", inline=False)
                e.set_footer(text="ViraBot Audit Log")
                await send_log(member.guild.id, e)
                break
    except Exception:
        pass


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await asyncio.sleep(1)
    reason = "No reason provided"
    moderator = "Unknown"
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                reason    = entry.reason or "No reason provided"
                moderator = str(entry.user) if entry.user else "Unknown"
                break
    except Exception:
        pass
    e = discord.Embed(title="Member Banned", color=discord.Color.dark_red(), timestamp=discord.utils.utcnow())
    e.add_field(name="Banned User", value=f"{user} (`{user.id}`)", inline=False)
    e.add_field(name="Moderator",   value=moderator, inline=False)
    e.add_field(name="Reason",      value=reason, inline=False)
    e.set_footer(text="ViraBot Audit Log")
    await send_log(guild.id, e)


@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User):
    await asyncio.sleep(1)
    reason = "No reason provided"
    moderator = "Unknown"
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            if entry.target.id == user.id:
                reason    = entry.reason or "No reason provided"
                moderator = str(entry.user) if entry.user else "Unknown"
                break
    except Exception:
        pass
    e = discord.Embed(title="Member Unbanned", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    e.add_field(name="Unbanned User", value=f"{user} (`{user.id}`)", inline=False)
    e.add_field(name="Moderator",     value=moderator, inline=False)
    e.add_field(name="Reason",        value=reason, inline=False)
    e.set_footer(text="ViraBot Audit Log")
    await send_log(guild.id, e)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    timed_out_before = before.timed_out_until
    timed_out_after  = after.timed_out_until

    if timed_out_after and (not timed_out_before or timed_out_after > discord.utils.utcnow()):
        await asyncio.sleep(1)
        moderator = "Unknown"
        reason    = "No reason provided"
        try:
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if entry.target.id == after.id:
                    moderator = str(entry.user) if entry.user else "Unknown"
                    reason    = entry.reason or "No reason provided"
                    break
        except Exception:
            pass
        e = discord.Embed(title="Member Timed Out", color=discord.Color.yellow(), timestamp=discord.utils.utcnow())
        e.add_field(name="User",      value=f"{after} (`{after.id}`)", inline=False)
        e.add_field(name="Moderator", value=moderator, inline=False)
        e.add_field(name="Until",     value=f"<t:{int(timed_out_after.timestamp())}:F>", inline=False)
        e.add_field(name="Reason",    value=reason, inline=False)
        e.set_footer(text="ViraBot Audit Log")
        await send_log(after.guild.id, e)

    elif timed_out_before and not timed_out_after:
        e = discord.Embed(title="Timeout Removed", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        e.add_field(name="User", value=f"{after} (`{after.id}`)", inline=False)
        e.set_footer(text="ViraBot Audit Log")
        await send_log(after.guild.id, e)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    cfg      = get_cfg(message.guild.id)
    uid      = str(message.author.id)
    xp_store = cfg["xp"]
    user_xp  = xp_store.get(uid, {"xp": 0, "level": 1})
    old_level = user_xp["level"]

    user_xp["xp"] += XP_PER_MESSAGE
    new_level        = get_level(user_xp["xp"])
    user_xp["level"] = new_level
    xp_store[uid]    = user_xp
    save_configs()

    if new_level > old_level:
        lv_ch_id = cfg.get("level_channel")
        if lv_ch_id:
            lv_ch = bot.get_channel(int(lv_ch_id))
            if lv_ch:
                e = discord.Embed(
                    title="Level Up!",
                    description=f"{message.author.mention} just reached **Level {new_level}**!",
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                e.set_thumbnail(url=message.author.display_avatar.url)
                e.add_field(name="Total XP", value=str(user_xp["xp"]), inline=True)
                e.add_field(name="Level",    value=str(new_level),      inline=True)
                e.set_footer(text="ViraBot Levels")
                try:
                    await lv_ch.send(embed=e)
                except discord.HTTPException:
                    pass

    await bot.process_commands(message)


# ══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

def admin_error(msg="You need Administrator permission."):
    async def handler(interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
    return handler


@tree.command(name="setwelcomechannel", description="Set the welcome channel.")
@app_commands.describe(channel="Welcome channel")
@app_commands.checks.has_permissions(administrator=True)
async def setwelcomechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = get_cfg(interaction.guild_id)
    cfg["welcome_channel"] = channel.id
    save_configs()
    await interaction.response.send_message(f"Welcome channel set to {channel.mention}.", ephemeral=True)
setwelcomechannel.error(admin_error())


@tree.command(name="setlogchannel", description="Set the audit log channel.")
@app_commands.describe(channel="Log channel")
@app_commands.checks.has_permissions(administrator=True)
async def setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = get_cfg(interaction.guild_id)
    cfg["log_channel"] = channel.id
    save_configs()
    await interaction.response.send_message(f"Log channel set to {channel.mention}.", ephemeral=True)
setlogchannel.error(admin_error())


@tree.command(name="setlevelchannel", description="Set the channel for level up announcements.")
@app_commands.describe(channel="Level channel")
@app_commands.checks.has_permissions(administrator=True)
async def setlevelchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = get_cfg(interaction.guild_id)
    cfg["level_channel"] = channel.id
    save_configs()
    await interaction.response.send_message(f"Level channel set to {channel.mention}.", ephemeral=True)
setlevelchannel.error(admin_error())


@tree.command(name="setinvitechannel", description="Set the channel for invite announcements.")
@app_commands.describe(channel="Invite channel")
@app_commands.checks.has_permissions(administrator=True)
async def setinvitechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = get_cfg(interaction.guild_id)
    cfg["invite_channel"] = channel.id
    save_configs()
    await interaction.response.send_message(f"Invite channel set to {channel.mention}.", ephemeral=True)
setinvitechannel.error(admin_error())


@tree.command(name="setyoutubechannel", description="Set the Discord channel for YouTube announcements.")
@app_commands.describe(channel="YouTube announcement channel")
@app_commands.checks.has_permissions(administrator=True)
async def setyoutubechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = get_cfg(interaction.guild_id)
    cfg["youtube_channel"] = channel.id
    save_configs()
    await interaction.response.send_message(f"YouTube channel set to {channel.mention}.", ephemeral=True)
setyoutubechannel.error(admin_error())


@tree.command(name="setyoutubeid", description="Set the YouTube channel ID to track.")
@app_commands.describe(channel_id="YouTube channel ID (starts with UC...)")
@app_commands.checks.has_permissions(administrator=True)
async def setyoutubeid(interaction: discord.Interaction, channel_id: str):
    cfg = get_cfg(interaction.guild_id)
    cfg["youtube_id"]    = channel_id
    cfg["last_yt_video"] = None
    save_configs()
    await interaction.response.send_message(f"YouTube channel ID set to `{channel_id}`.", ephemeral=True)
setyoutubeid.error(admin_error())


@tree.command(name="setautorole", description="Set a role to auto-assign when a member joins.")
@app_commands.describe(role="The role to assign")
@app_commands.checks.has_permissions(administrator=True)
async def setautorole(interaction: discord.Interaction, role: discord.Role):
    cfg = get_cfg(interaction.guild_id)
    cfg["autorole"] = role.id
    save_configs()
    await interaction.response.send_message(f"Autorole set to {role.mention}.", ephemeral=True)
setautorole.error(admin_error())


@tree.command(name="setwelcome", description="Set the welcome message. Use {mention}, {user}, {guild}.")
@app_commands.describe(message="Welcome message template")
@app_commands.checks.has_permissions(administrator=True)
async def setwelcome(interaction: discord.Interaction, message: str):
    cfg = get_cfg(interaction.guild_id)
    cfg["welcome_message"] = message
    save_configs()
    preview = fmt_placeholder(message, interaction.user)  # type: ignore[arg-type]
    await interaction.response.send_message(f"Welcome message updated!\n\nPreview:\n{preview}", ephemeral=True)
setwelcome.error(admin_error())


@tree.command(name="settings", description="View current ViraBot configuration.")
@app_commands.checks.has_permissions(administrator=True)
async def settings(interaction: discord.Interaction):
    cfg = get_cfg(interaction.guild_id)
    def fc(ch_id) -> str:
        if not ch_id:
            return "Not set"
        ch = interaction.guild.get_channel(int(ch_id))
        return ch.mention if ch else f"<#{ch_id}> (deleted?)"
    def fr(r_id) -> str:
        if not r_id:
            return "Not set"
        r = interaction.guild.get_role(int(r_id))
        return r.mention if r else f"<@&{r_id}> (deleted?)"
    e = discord.Embed(title="ViraBot Settings", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
    e.add_field(name="Welcome Channel", value=fc(cfg["welcome_channel"]), inline=True)
    e.add_field(name="Log Channel",     value=fc(cfg["log_channel"]),     inline=True)
    e.add_field(name="Level Channel",   value=fc(cfg["level_channel"]),   inline=True)
    e.add_field(name="Invite Channel",  value=fc(cfg["invite_channel"]),  inline=True)
    e.add_field(name="YouTube Channel", value=fc(cfg["youtube_channel"]), inline=True)
    e.add_field(name="YouTube ID",      value=cfg["youtube_id"] or "Not set", inline=True)
    e.add_field(name="Autorole",        value=fr(cfg["autorole"]),        inline=True)
    e.add_field(name="Welcome Message", value=cfg["welcome_message"],     inline=False)
    e.set_footer(text="ViraBot Settings")
    await interaction.response.send_message(embed=e, ephemeral=True)
settings.error(admin_error())


@tree.command(name="kick", description="Kick a member.")
@app_commands.describe(member="Member to kick", reason="Reason for kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"Kicked {member.mention}. Reason: {reason}", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"Failed to kick: {e}", ephemeral=True)
kick.error(admin_error("You need Kick Members permission."))


@tree.command(name="ban", description="Ban a member.")
@app_commands.describe(member="Member to ban", reason="Reason for ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"Banned {member.mention}. Reason: {reason}", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"Failed to ban: {e}", ephemeral=True)
ban.error(admin_error("You need Ban Members permission."))


@tree.command(name="unban", description="Unban a user by ID.")
@app_commands.describe(user_id="User ID to unban", reason="Reason for unban")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        await interaction.response.send_message(f"Unbanned {user}. Reason: {reason}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to unban: {e}", ephemeral=True)
unban.error(admin_error("You need Ban Members permission."))


@tree.command(name="timeout", description="Timeout a member.")
@app_commands.describe(member="Member to timeout", minutes="Duration in minutes", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
    try:
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=reason)
        await interaction.response.send_message(f"Timed out {member.mention} for {minutes} minute(s). Reason: {reason}", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"Failed to timeout: {e}", ephemeral=True)
timeout.error(admin_error("You need Moderate Members permission."))


@tree.command(name="untimeout", description="Remove timeout from a member.")
@app_commands.describe(member="Member to untimeout")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    try:
        await member.timeout(None)
        await interaction.response.send_message(f"Removed timeout from {member.mention}.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"Failed: {e}", ephemeral=True)
untimeout.error(admin_error("You need Moderate Members permission."))


@tree.command(name="purge", description="Delete multiple messages.")
@app_commands.describe(amount="Number of messages to delete (max 100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        await interaction.response.send_message("Amount must be between 1 and 100.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted {len(deleted)} message(s).", ephemeral=True)
purge.error(admin_error("You need Manage Messages permission."))


@tree.command(name="rank", description="Check your rank or someone else's rank.")
@app_commands.describe(user="The user to check (leave empty for yourself)")
async def rank(interaction: discord.Interaction, user: discord.Member = None):
    cfg    = get_cfg(interaction.guild_id)
    target = user or interaction.user
    uid    = str(target.id)
    data   = cfg["xp"].get(uid, {"xp": 0, "level": 1})
    xp     = data.get("xp", 0)
    level  = data.get("level", 1)
    next_xp = xp_for_level(level + 1)
    sorted_users = sorted(cfg["xp"].items(), key=lambda x: x[1].get("xp", 0), reverse=True)
    rank_pos = next((i + 1 for i, (u, _) in enumerate(sorted_users) if u == uid), len(sorted_users))
    e = discord.Embed(title=f"{target.display_name}'s Rank", color=discord.Color.blurple())
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="Level",    value=str(level),    inline=True)
    e.add_field(name="XP",       value=str(xp),       inline=True)
    e.add_field(name="Next Level", value=str(next_xp), inline=True)
    e.add_field(name="Server Rank", value=f"#{rank_pos}", inline=True)
    e.set_footer(text="ViraBot Levels")
    await interaction.response.send_message(embed=e)


@tree.command(name="leaderboard", description="Show the XP leaderboard.")
async def leaderboard(interaction: discord.Interaction):
    cfg = get_cfg(interaction.guild_id)
    sorted_users = sorted(cfg["xp"].items(), key=lambda x: x[1].get("xp", 0), reverse=True)[:10]
    e = discord.Embed(title="XP Leaderboard", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
    if not sorted_users:
        e.description = "No data yet."
    else:
        lines = []
        for i, (uid, data) in enumerate(sorted_users, 1):
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else f"User {uid}"
            lines.append(f"**#{i}** {name} — Level {data.get('level',1)} ({data.get('xp',0)} XP)")
        e.description = "\n".join(lines)
    e.set_footer(text="ViraBot Levels")
    await interaction.response.send_message(embed=e)


@tree.command(name="invites", description="Check your invites or someone else's invites.")
@app_commands.describe(user="The user to check (leave empty for yourself)")
async def invites(interaction: discord.Interaction, user: discord.Member = None):
    cfg       = get_cfg(interaction.guild_id)
    inv_ch_id = cfg.get("invite_channel")
    if inv_ch_id and interaction.channel_id != int(inv_ch_id):
        ch      = interaction.guild.get_channel(int(inv_ch_id))
        mention = ch.mention if ch else "the invite channel"
        await interaction.response.send_message(f"Use this command in {mention}.", ephemeral=True)
        return
    target = user or interaction.user
    uid    = str(target.id)
    data   = cfg["invites"].get(uid, {"total": 0, "left": 0})
    total  = data.get("total", 0)
    left   = data.get("left", 0)
    real   = total - left
    e = discord.Embed(title=f"{target.display_name}'s Invites", color=discord.Color.blurple())
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="Total Invites", value=str(total), inline=True)
    e.add_field(name="Left Server",   value=str(left),  inline=True)
    e.add_field(name="Real Invites",  value=str(real),  inline=True)
    e.set_footer(text="ViraBot Invites")
    await interaction.response.send_message(embed=e)


@tree.command(name="translate", description="Translate any text to English.")
@app_commands.describe(text="Text to translate")
async def translate(interaction: discord.Interaction, text: str):
    await interaction.response.defer()
    try:
        result     = translator.translate(text, dest="en")
        translated = result.text
        src_lang   = result.src
        if src_lang == "en":
            await interaction.followup.send(f"{interaction.user.display_name} said (already in English):\n{translated}")
        else:
            await interaction.followup.send(f"{interaction.user.display_name} said ({src_lang.upper()} to EN):\n{translated}")
    except Exception as ex:
        await interaction.followup.send(f"Translation failed: {ex}")


@tree.command(name="botinfo", description="About ViraBot.")
async def botinfo(interaction: discord.Interaction):
    try:
        owner = await bot.fetch_user(1491318129501016164)
        owner_str = f"{owner.mention} ({owner})"
    except Exception:
        owner_str = "<@1491318129501016164>"
    e = discord.Embed(title="ViraBot", description="The official bot of Vira Arena.", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
    e.add_field(name="Developed by", value=owner_str, inline=False)
    e.add_field(name="Features", value="Welcome • Logs • Levels • Invites • Translation • YouTube Feed • Autorole", inline=False)
    e.set_footer(text="ViraBot • Official")
    await interaction.response.send_message(embed=e, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════════════════════════════

token = os.getenv("TOKEN")
if not token:
    try:
        with open("token.txt", "r") as f:
            token = f.read().strip()
    except FileNotFoundError:
        print("[ERROR] TOKEN not found! Set TOKEN env variable or create token.txt file.")
        exit(1)
bot.run(token)
