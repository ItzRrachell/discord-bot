import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
import os
from datetime import datetime, timezone

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Database ---

def init_db():
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            role_id INTEGER,
            content TEXT,
            send_at TEXT,
            sent INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS repeating (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            role_id INTEGER,
            content TEXT,
            frequency TEXT,
            time TEXT,
            active INTEGER DEFAULT 1,
            last_sent TEXT
        )
    """)
    con.commit()
    con.close()

def save_announcement(guild_id, channel_id, role_id, content, send_at):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO announcements (guild_id, channel_id, role_id, content, send_at) VALUES (?,?,?,?,?)",
        (guild_id, channel_id, role_id, content, send_at)
    )
    aid = cur.lastrowid
    con.commit()
    con.close()
    return aid

def get_pending():
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    cur.execute(
        "SELECT id, channel_id, role_id, content FROM announcements WHERE sent=0 AND send_at<=?",
        (now,)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def mark_sent(aid):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute("UPDATE announcements SET sent=1 WHERE id=?", (aid,))
    con.commit()
    con.close()

def get_upcoming(guild_id):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute(
        "SELECT id, channel_id, role_id, content, send_at FROM announcements WHERE guild_id=? AND sent=0 ORDER BY send_at ASC LIMIT 10",
        (guild_id,)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def delete_announcement(aid, guild_id):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute("DELETE FROM announcements WHERE id=? AND guild_id=? AND sent=0", (aid, guild_id))
    changed = cur.rowcount
    con.commit()
    con.close()
    return changed > 0

# --- Repeating ---

def save_repeating(guild_id, channel_id, role_id, content, frequency, time):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO repeating (guild_id, channel_id, role_id, content, frequency, time) VALUES (?,?,?,?,?,?)",
        (guild_id, channel_id, role_id, content, frequency, time)
    )
    rid = cur.lastrowid
    con.commit()
    con.close()
    return rid

def get_active_repeating():
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute("SELECT id, channel_id, role_id, content, frequency, time, last_sent FROM repeating WHERE active=1")
    rows = cur.fetchall()
    con.close()
    return rows

def update_last_sent(rid, when):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute("UPDATE repeating SET last_sent=? WHERE id=?", (when, rid))
    con.commit()
    con.close()

def get_repeating_list(guild_id):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute(
        "SELECT id, channel_id, role_id, content, frequency, time FROM repeating WHERE guild_id=? AND active=1",
        (guild_id,)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def stop_repeating(rid, guild_id):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute("UPDATE repeating SET active=0 WHERE id=? AND guild_id=?", (rid, guild_id))
    changed = cur.rowcount
    con.commit()
    con.close()
    return changed > 0

def edit_repeating(rid, guild_id, content):
    con = sqlite3.connect("announcements.db")
    cur = con.cursor()
    cur.execute("UPDATE repeating SET content=? WHERE id=? AND guild_id=? AND active=1", (content, rid, guild_id))
    changed = cur.rowcount
    con.commit()
    con.close()
    return changed > 0

def should_send(frequency, time_str, last_sent):
    now = datetime.now(timezone.utc)
    now_time = now.strftime("%H:%M")
    now_date = now.strftime("%Y-%m-%d")

    if now_time != time_str:
        return False

    if last_sent and last_sent == now_date:
        return False

    weekday = now.weekday()  # 0=Monday, 6=Sunday

    freq_map = {
        "every day": True,
        "every monday": weekday == 0,
        "every tuesday": weekday == 1,
        "every wednesday": weekday == 2,
        "every thursday": weekday == 3,
        "every friday": weekday == 4,
        "every saturday": weekday == 5,
        "every sunday": weekday == 6,
        "every week": weekday == 0,
        "every month": now.day == 1,
    }

    return freq_map.get(frequency, False)

# --- Scheduler ---

@tasks.loop(seconds=60)
async def check_announcements():
    # One-time
    pending = get_pending()
    for aid, channel_id, role_id, content in pending:
        channel = client.get_channel(channel_id)
        if channel is None:
            continue
        message = f"<@&{role_id}>\n\n{content}" if role_id else content
        try:
            await channel.send(message)
            mark_sent(aid)
        except discord.Forbidden:
            pass

    # Repeating
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for rid, channel_id, role_id, content, frequency, time_str, last_sent in get_active_repeating():
        if not should_send(frequency, time_str, last_sent):
            continue
        channel = client.get_channel(channel_id)
        if channel is None:
            continue
        message = f"<@&{role_id}>\n\n{content}" if role_id else content
        try:
            await channel.send(message)
            update_last_sent(rid, now_date)
        except discord.Forbidden:
            pass

# --- Commands ---

@tree.command(name="announce", description="Schedule a one-time announcement")
@app_commands.describe(
    channel="Channel to send the announcement in",
    date="Date in YYYY-MM-DD format (e.g. 2025-07-20)",
    time="Time in HH:MM UTC format (e.g. 18:00)",
    content="The announcement text",
    role="Role to mention (optional)"
)
@app_commands.default_permissions(manage_messages=True)
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    date: str,
    time: str,
    content: str,
    role: discord.Role = None
):
    try:
        send_at = f"{date} {time}"
        datetime.strptime(send_at, "%Y-%m-%d %H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid format. Use: date `YYYY-MM-DD`, time `HH:MM`",
            ephemeral=True
        )
        return

    role_id = role.id if role else None
    aid = save_announcement(interaction.guild_id, channel.id, role_id, content, send_at)

    embed = discord.Embed(title="✅ Announcement scheduled", color=0x5865F2)
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(name="Time (UTC)", value=f"`{send_at}`", inline=True)
    embed.add_field(name="ID", value=f"`#{aid}`", inline=True)
    embed.add_field(name="Content", value=content[:500], inline=False)
    if role:
        embed.add_field(name="Role", value=role.mention, inline=True)
    embed.set_footer(text="Time is in UTC. Adjust for your timezone accordingly.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


frequency_choices = [
    app_commands.Choice(name="Every day", value="every day"),
    app_commands.Choice(name="Every Monday", value="every monday"),
    app_commands.Choice(name="Every Tuesday", value="every tuesday"),
    app_commands.Choice(name="Every Wednesday", value="every wednesday"),
    app_commands.Choice(name="Every Thursday", value="every thursday"),
    app_commands.Choice(name="Every Friday", value="every friday"),
    app_commands.Choice(name="Every Saturday", value="every saturday"),
    app_commands.Choice(name="Every Sunday", value="every sunday"),
    app_commands.Choice(name="Every week (Monday)", value="every week"),
    app_commands.Choice(name="Every month (1st day)", value="every month"),
]

@tree.command(name="repeat", description="Create a repeating announcement")
@app_commands.describe(
    channel="Channel to send the announcement in",
    frequency="How often to send it",
    time="Time in HH:MM UTC format (e.g. 18:00)",
    content="The announcement text",
    role="Role to mention (optional)"
)
@app_commands.choices(frequency=frequency_choices)
@app_commands.default_permissions(manage_messages=True)
async def repeat(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    frequency: app_commands.Choice[str],
    time: str,
    content: str,
    role: discord.Role = None
):
    try:
        datetime.strptime(time, "%H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid time format. Use `HH:MM` (e.g. `18:00`)",
            ephemeral=True
        )
        return

    role_id = role.id if role else None
    rid = save_repeating(interaction.guild_id, channel.id, role_id, content, frequency.value, time)

    embed = discord.Embed(title="🔁 Repeating announcement created", color=0x57F287)
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(name="Frequency", value=frequency.name, inline=True)
    embed.add_field(name="Time (UTC)", value=f"`{time}`", inline=True)
    embed.add_field(name="ID", value=f"`#{rid}`", inline=True)
    embed.add_field(name="Content", value=content[:500], inline=False)
    if role:
        embed.add_field(name="Role", value=role.mention, inline=True)
    embed.set_footer(text="Time is in UTC. Use /stop-repeating to disable.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="list-repeating", description="Show all active repeating announcements")
@app_commands.default_permissions(manage_messages=True)
async def list_repeating(interaction: discord.Interaction):
    items = get_repeating_list(interaction.guild_id)
    if not items:
        await interaction.response.send_message("📭 No repeating announcements.", ephemeral=True)
        return

    embed = discord.Embed(title="🔁 Repeating announcements", color=0x57F287)
    for rid, channel_id, role_id, content, frequency, time_str in items:
        channel = client.get_channel(channel_id)
        channel_name = channel.mention if channel else f"#{channel_id}"
        role_info = f" · <@&{role_id}>" if role_id else ""
        embed.add_field(
            name=f"#{rid} · {frequency} at {time_str} UTC",
            value=f"{channel_name}{role_info}\n{content[:100]}{'…' if len(content)>100 else ''}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="stop-repeating", description="Stop a repeating announcement")
@app_commands.describe(id="ID of the repeating announcement (from /list-repeating)")
@app_commands.default_permissions(manage_messages=True)
async def stop_repeating_cmd(interaction: discord.Interaction, id: int):
    if stop_repeating(id, interaction.guild_id):
        await interaction.response.send_message(f"⏹️ Repeating announcement `#{id}` stopped.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ No active repeating announcement with ID `#{id}`.", ephemeral=True)


@tree.command(name="edit-repeating", description="Edit the content of a repeating announcement")
@app_commands.describe(
    id="ID of the repeating announcement (from /list-repeating)",
    content="New announcement text"
)
@app_commands.default_permissions(manage_messages=True)
async def edit_repeating_cmd(interaction: discord.Interaction, id: int, content: str):
    if edit_repeating(id, interaction.guild_id, content):
        await interaction.response.send_message(f"✏️ Repeating announcement `#{id}` updated.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ No active repeating announcement with ID `#{id}`.", ephemeral=True)


@tree.command(name="list", description="Show upcoming one-time announcements")
@app_commands.default_permissions(manage_messages=True)
async def list_announcements(interaction: discord.Interaction):
    announcements = get_upcoming(interaction.guild_id)
    if not announcements:
        await interaction.response.send_message("📭 No announcements scheduled.", ephemeral=True)
        return

    embed = discord.Embed(title="📅 Upcoming announcements", color=0x5865F2)
    for aid, channel_id, role_id, content, send_at in announcements:
        channel = client.get_channel(channel_id)
        channel_name = channel.mention if channel else f"#{channel_id}"
        role_info = f" · <@&{role_id}>" if role_id else ""
        embed.add_field(
            name=f"#{aid} · {send_at} UTC",
            value=f"{channel_name}{role_info}\n{content[:100]}{'…' if len(content)>100 else ''}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="cancel", description="Cancel a one-time announcement by ID")
@app_commands.describe(id="Announcement ID (from /list)")
@app_commands.default_permissions(manage_messages=True)
async def cancel(interaction: discord.Interaction, id: int):
    if delete_announcement(id, interaction.guild_id):
        await interaction.response.send_message(f"🗑️ Announcement `#{id}` cancelled.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Announcement `#{id}` not found (or already sent).", ephemeral=True)


@client.event
async def on_ready():
    init_db()
    await tree.sync()
    check_announcements.start()
    print(f"Bot running as {client.user}")

client.run(TOKEN)
