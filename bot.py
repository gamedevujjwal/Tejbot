import os
import json
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from googletrans import Translator

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE = "config.json"

DEFAULT_CONFIG: dict = {
    "welcome_channel": None,
    "log_channel":     None,
    "welcome_message": "Welcome {mention} to **{guild}**!"
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config() -> None:
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"[CONFIG ERROR] {e}")


config = load_config()


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


async def send_log(embed: discord.Embed) -> None:
    channel_id = config.get("log_channel")
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  INTENTS & BOT
# ══════════════════════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members         = True
intents.message_content = True

bot        = commands.Bot(command_prefix="!", intents=intents)
tree       = bot.tree
translator = Translator()


# ══════════════════════════════════════════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await tree.sync()
    print(f"[ViraBot] Logged in as {bot.user} (ID: {bot.user.id})")
    print("[ViraBot] Slash commands synced.")


# ── Welcome ────────────────────────────────────────────────────────────────────
@bot.event
async def on_member_join(member: discord.Member):
    channel_id = config.get("welcome_channel")
    if channel_id:
        channel = member.guild.get_channel(int(channel_id))
        if channel:
            msg = fmt_placeholder(config["welcome_message"], member)
            try:
                await channel.send(msg)
            except discord.HTTPException:
                pass

    embed = discord.Embed(
        title="Member Joined",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User",        value=f"{member} (`{member.id}`)", inline=False)
    embed.add_field(name="Account Age", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=False)
    embed.set_footer(text=f"Member #{member.guild.member_count} • ViraBot")
    await send_log(embed)


# ── Audit Log — fetch based approach ──────────────────────────────────────────

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await discord.utils.sleep_until(
        discord.utils.utcnow() + datetime.timedelta(seconds=1)
    )
    reason = "No reason provided"
    moderator = "Unknown"
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.target.id == user.id:
            reason    = entry.reason or "No reason provided"
            moderator = str(entry.user) if entry.user else "Unknown"
            break

    embed = discord.Embed(title="Member Banned", color=discord.Color.dark_red(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Banned User", value=f"{user} (`{user.id}`)", inline=False)
    embed.add_field(name="Moderator",   value=moderator,               inline=False)
    embed.add_field(name="Reason",      value=reason,                  inline=False)
    embed.set_footer(text="ViraBot Audit Log")
    await send_log(embed)


@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User):
    await discord.utils.sleep_until(
        discord.utils.utcnow() + datetime.timedelta(seconds=1)
    )
    reason = "No reason provided"
    moderator = "Unknown"
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
        if entry.target.id == user.id:
            reason    = entry.reason or "No reason provided"
            moderator = str(entry.user) if entry.user else "Unknown"
            break

    embed = discord.Embed(title="Member Unbanned", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Unbanned User", value=f"{user} (`{user.id}`)", inline=False)
    embed.add_field(name="Moderator",     value=moderator,               inline=False)
    embed.add_field(name="Reason",        value=reason,                  inline=False)
    embed.set_footer(text="ViraBot Audit Log")
    await send_log(embed)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    timed_out_before = before.timed_out_until
    timed_out_after  = after.timed_out_until

    if timed_out_after and (not timed_out_before or timed_out_after > discord.utils.utcnow()):
        await discord.utils.sleep_until(
            discord.utils.utcnow() + datetime.timedelta(seconds=1)
        )
        moderator = "Unknown"
        reason    = "No reason provided"
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
            if entry.target.id == after.id:
                moderator = str(entry.user) if entry.user else "Unknown"
                reason    = entry.reason or "No reason provided"
                break

        embed = discord.Embed(title="Member Timed Out", color=discord.Color.yellow(), timestamp=discord.utils.utcnow())
        embed.add_field(name="User",      value=f"{after} (`{after.id}`)", inline=False)
        embed.add_field(name="Moderator", value=moderator,                 inline=False)
        embed.add_field(name="Until",     value=f"<t:{int(timed_out_after.timestamp())}:F>", inline=False)
        embed.add_field(name="Reason",    value=reason,                    inline=False)
        embed.set_footer(text="ViraBot Audit Log")
        await send_log(embed)

    elif timed_out_before and not timed_out_after:
        embed = discord.Embed(title="Timeout Removed", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.add_field(name="User", value=f"{after} (`{after.id}`)", inline=False)
        embed.set_footer(text="ViraBot Audit Log")
        await send_log(embed)


# ── Kick detection via audit log on member remove ──────────────────────────────
# (single handler kept; duplicate removed)
@bot.event
async def on_member_remove(member: discord.Member):
    embed_left = discord.Embed(
        title="Member Left",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed_left.set_thumbnail(url=member.display_avatar.url)
    embed_left.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
    embed_left.add_field(
        name="Joined",
        value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown",
        inline=False
    )
    embed_left.set_footer(text="ViraBot")
    await send_log(embed_left)

    await discord.utils.sleep_until(
        discord.utils.utcnow() + datetime.timedelta(seconds=1)
    )
    async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        if entry.target.id == member.id:
            embed_kick = discord.Embed(title="Member Kicked", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
            embed_kick.add_field(name="Kicked User", value=f"{member} (`{member.id}`)", inline=False)
            embed_kick.add_field(name="Moderator",   value=str(entry.user) if entry.user else "Unknown", inline=False)
            embed_kick.add_field(name="Reason",      value=entry.reason or "No reason provided", inline=False)
            embed_kick.set_footer(text="ViraBot Audit Log")
            await send_log(embed_kick)
            break


# ══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — SETUP
# ══════════════════════════════════════════════════════════════════════════════

@tree.command(name="setwelcomechannel", description="Set the channel where welcome messages are sent.")
@app_commands.describe(channel="The welcome channel")
@app_commands.checks.has_permissions(administrator=True)
async def setwelcomechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        config["welcome_channel"] = channel.id
        save_config()
        await interaction.edit_original_response(content=f"Welcome channel set to {channel.mention}.")
    except Exception as e:
        await interaction.edit_original_response(content=f"Error: {e}")

@setwelcomechannel.error
async def setwelcomechannel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except:
        pass


@tree.command(name="setlogchannel", description="Set the channel where audit logs are sent.")
@app_commands.describe(channel="The log channel")
@app_commands.checks.has_permissions(administrator=True)
async def setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        config["log_channel"] = channel.id
        save_config()
        await interaction.edit_original_response(content=f"Log channel set to {channel.mention}.")
    except Exception as e:
        await interaction.edit_original_response(content=f"Error: {e}")

@setlogchannel.error
async def setlogchannel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except:
        pass


@tree.command(name="setwelcome", description="Set the welcome message. Use {mention}, {user}, {guild}.")
@app_commands.describe(message="The welcome message template")
@app_commands.checks.has_permissions(administrator=True)
async def setwelcome(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        config["welcome_message"] = message
        save_config()
        preview = fmt_placeholder(message, interaction.user)  # type: ignore[arg-type]
        await interaction.edit_original_response(content=f"Welcome message updated!\n\nPreview:\n{preview}")
    except Exception as e:
        await interaction.edit_original_response(content=f"Error: {e}")

@setwelcome.error
async def setwelcome_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

@tree.command(name="settings", description="View current ViraBot configuration.")
@app_commands.checks.has_permissions(administrator=True)
async def settings(interaction: discord.Interaction):
    def fmt_channel(channel_id) -> str:
        if not channel_id:
            return "Not set"
        ch = interaction.guild.get_channel(int(channel_id))
        return ch.mention if ch else f"<#{channel_id}> (deleted?)"

    embed = discord.Embed(title="ViraBot Settings", color=discord.Color.blurple())
    embed.add_field(name="Welcome Channel", value=fmt_channel(config["welcome_channel"]), inline=True)
    embed.add_field(name="Log Channel",     value=fmt_channel(config["log_channel"]),     inline=True)
    embed.add_field(name="Welcome Message", value=config["welcome_message"],              inline=False)
    embed.set_footer(text="Use /setwelcomechannel /setlogchannel /setwelcome to update.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@settings.error
async def settings_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — SAY
# ══════════════════════════════════════════════════════════════════════════════

@tree.command(name="say", description="Send a message to any channel as ViraBot.")
@app_commands.describe(channel="The channel to send the message in", message="The message to send")
@app_commands.checks.has_permissions(administrator=True)
async def say(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await channel.send(message)
        await interaction.edit_original_response(content=f"Message sent to {channel.mention}.")
    except discord.Forbidden:
        await interaction.edit_original_response(content="I don't have permission to send messages in that channel.")
    except discord.HTTPException as e:
        await interaction.edit_original_response(content=f"Failed to send message: {e}")

@say.error
async def say_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — RULES
# ══════════════════════════════════════════════════════════════════════════════

@tree.command(name="rules", description="Post the server rules in a channel.")
@app_commands.describe(channel="The channel to post rules in", message="The rules text")
@app_commands.checks.has_permissions(administrator=True)
async def rules(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await channel.send(message)
        await interaction.edit_original_response(content=f"Rules posted in {channel.mention}.")
    except discord.Forbidden:
        await interaction.edit_original_response(content="I don't have permission to send messages in that channel.")
    except discord.HTTPException as e:
        await interaction.edit_original_response(content=f"Failed to post rules: {e}")

@rules.error
async def rules_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — TRANSLATE
# ══════════════════════════════════════════════════════════════════════════════

@tree.command(name="translate", description="Translate any text to English.")
@app_commands.describe(text="The text you want to translate")
async def translate(interaction: discord.Interaction, text: str):
    await interaction.response.defer()
    try:
        result     = translator.translate(text, dest="en")
        translated = result.text
        src_lang   = result.src

        if src_lang == "en":
            await interaction.followup.send(
                f"{interaction.user.display_name} said (already in English):\n{translated}"
            )
        else:
            await interaction.followup.send(
                f"{interaction.user.display_name} said ({src_lang.upper()} to EN):\n{translated}"
            )
    except Exception as e:
        await interaction.followup.send(f"Translation failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════════════════════════════

bot.run(os.getenv("TOKEN"))