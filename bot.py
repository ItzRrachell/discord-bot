import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
import os
from datetime import datetime, timezone
import calendar

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
    cur.execute("SELECT id, channel_id, role_id, content FROM announcements WHERE sent=0 AND send_at<=?", (now,))
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

# --- Logic ---

WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
}

def get_weekdays_in_month(year, month, weekday):
    cal = calendar.monthcalendar(year, month)
    days = []
    for week in cal:
        d = week[weekday]
        if d != 0:
            days.append(d)
    return days

def should_send(frequency, time_str, last_sent):
    now = datetime.now(timezone.utc)
    now_time = now.strftime("%H:%M")
    now_date = now.strftime("%Y-%m-%d")

    if now_time != time_str:
        return False
    if last_sent and last_sent == now_date:
        return False

    # frequency format: "every_N_months|weekday|occurrence"
    # occurrence: 1st, 2nd, 3rd, 4th, last

    if not frequency.startswith("every_"):
        return False

    parts = frequency.split("|")
    if len(parts) != 3:
        return False

    period = parts[0]       # "every_N_months"
    day_name = parts[1]     # "monday" etc
    occurrence = parts[2]   # "1st", "2nd", "3rd", "4th", "last"

    try:
        interval = int(period.split("_")[1])
    except (IndexError, ValueError):
        return False

    # Check month interval
    if last_sent:
        last_dt = datetime.strptime(last_sent, "%Y-%m-%d")
        months_diff = (now.year - last_dt.year) * 12 + (now.month - last_dt.month)
        if months_diff < interval:
            return False

    weekday = WEEKDAY_MAP.get(day_name)
    if weekday is None:
        return False

    days = get_weekdays_in_month(now.year, now.month, weekday)
    if not days:
        return False

    occ_map = {
        "1st": 0,
        "2nd": 1,
        "3rd": 2,
        "4th": 3,
    }

    if occurrence == "last":
        target = days[-1]
    elif occurrence in occ_map:
        idx = occ_map[occurrence]
        if idx >= len(days):
            return False
        target = days[idx]
    else:
        return False

    return now.day == target

# --- Scheduler ---

@tasks.loop(seconds=60)
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

# --- Choices ---

interval_choices = [
    app_commands.Choice(name="Every 1 month", value=1),
    app_commands.Choice(name="Every 2 months", value=2),
    app_commands.Choice(name="Every 3 months", value=3),
    app_commands.Choice(name="Every 4 months", value=4),
    app_commands.Choice(name="Every 6 months", value=6),
    app_commands.Choice(name="Every 12 months (yearly)", value=12),
]

occurrence_choices = [
    app_commands.Choice(name="1st (first in month)", value="1st"),
    app_commands.Choice(name="2nd (second in month)", value="2nd"),
    app_commands.Choice(name="3rd (third in month)", value="3rd"),
    app_commands.Choice(name="4th (fourth in month)", value="4th"),
    app_commands.Choice(name="Last (last in month)", value="last"),
]

day_choices = [
    app_commands.Choice(name="Monday", value="monday"),
    app_commands.Choice(name="Tuesday", value="tuesday"),
    app_commands.Choice(name="Wednesday", value="wednesday"),
    app_commands.Choice(name="Thursday", value="thursday"),
    app_commands.Choice(name="Friday", value="friday"),
    app_commands.Choice(name="Saturday", value="saturday"),
    app_commands.Choice(name="Sunday", value="sunday"),
]

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
        await interaction.response.send_message("❌ Invalid format. Use: date `YYYY-MM-DD`, time `HH:MM`", ephemeral=True)
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


@tree.command(name="repeat", description="Create a repeating announcement")
@app_commands.describe(
    channel="Channel to send the announcement in",
    every="How often (every N months)",
    occurrence="Which occurrence of the day in that month",
    day="Day of the week",
    time="Time in HH:MM UTC format (e.g. 18:00)",
    content="The announcement text",
    role="Role to mention (optional)"
)
@app_commands.choices(every=interval_choices, occurrence=occurrence_choices, day=day_choices)
@app_commands.default_permissions(manage_messages=True)
async def repeat(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    every: app_commands.Choice[int],
    occurrence: app_commands.Choice[str],
    day: app_commands.Choice[str],
    time: str,
    content: str,
    role: discord.Role = None
):
    try:
        datetime.strptime(time, "%H:%M")
    except ValueError:
        await interaction.response.send_message("❌ Invalid time format. Use `HH:MM` (e.g. `18:00`)", ephemeral=True)
        return

    role_id = role.id if role else None
    frequency = f"every_{every.value}_months|{day.value}|{occurrence.value}"
    rid = save_repeating(interaction.guild_id, channel.id, role_id, content, frequency, time)

    embed = discord.Embed(title="🔁 Repeating announcement created", color=0x57F287)
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(name="Every", value=every.name, inline=True)
    embed.add_field(name="When", value=f"{occurrence.name} {day.name}", inline=True)
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
        parts = frequency.split("|")
        if len(parts) == 3:
            interval = parts[0].replace("every_", "every ").replace("_months", " months")
            freq_display = f"{interval} · {parts[2]} {parts[1]}"
        else:
            freq_display = frequency
        embed.add_field(
            name=f"#{rid} · {freq_display} at {time_str} UTC",
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
