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

@tasks.loop(seconds=30)
async def check_announcements():
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

@tree.command(name="announce", description="Schedule an announcement for your server")
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
            "❌ Invalid date or time format. Use: date `YYYY-MM-DD`, time `HH:MM`",
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


@tree.command(name="list", description="Show upcoming scheduled announcements")
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


@tree.command(name="cancel", description="Cancel a scheduled announcement by ID")
@app_commands.describe(id="Announcement ID (from /list)")
@app_commands.default_permissions(manage_messages=True)
async def cancel(interaction: discord.Interaction, id: int):
    if delete_announcement(id, interaction.guild_id):
        await interaction.response.send_message(f"🗑️ Announcement `#{id}` has been cancelled.", ephemeral=True)
    else:
        await interaction.response.send_message(
            f"❌ Announcement `#{id}` not found (or already sent).",
            ephemeral=True
        )

@client.event
async def on_ready():
    init_db()
    await tree.sync()
    check_announcements.start()
    print(f"Bot running as {client.user}")

client.run(TOKEN)
