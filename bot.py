import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
import os
from datetime import datetime, timezone
import asyncio

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Baza danych ---

def init_db():
    con = sqlite3.connect("ogloszenia.db")
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ogloszenia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            role_id INTEGER,
            tresc TEXT,
            czas TEXT,
            wyslane INTEGER DEFAULT 0
        )
    """)
    con.commit()
    con.close()

def zapisz_ogloszenie(guild_id, channel_id, role_id, tresc, czas):
    con = sqlite3.connect("ogloszenia.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO ogloszenia (guild_id, channel_id, role_id, tresc, czas) VALUES (?,?,?,?,?)",
        (guild_id, channel_id, role_id, tresc, czas)
    )
    oid = cur.lastrowid
    con.commit()
    con.close()
    return oid

def pobierz_oczekujace():
    con = sqlite3.connect("ogloszenia.db")
    cur = con.cursor()
    teraz = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    cur.execute(
        "SELECT id, channel_id, role_id, tresc FROM ogloszenia WHERE wyslane=0 AND czas<=?",
        (teraz,)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def oznacz_wyslane(oid):
    con = sqlite3.connect("ogloszenia.db")
    cur = con.cursor()
    cur.execute("UPDATE ogloszenia SET wyslane=1 WHERE id=?", (oid,))
    con.commit()
    con.close()

def lista_nadchodzacych(guild_id):
    con = sqlite3.connect("ogloszenia.db")
    cur = con.cursor()
    cur.execute(
        "SELECT id, channel_id, role_id, tresc, czas FROM ogloszenia WHERE guild_id=? AND wyslane=0 ORDER BY czas ASC LIMIT 10",
        (guild_id,)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def usun_ogloszenie(oid, guild_id):
    con = sqlite3.connect("ogloszenia.db")
    cur = con.cursor()
    cur.execute("DELETE FROM ogloszenia WHERE id=? AND guild_id=? AND wyslane=0", (oid, guild_id))
    zmienione = cur.rowcount
    con.commit()
    con.close()
    return zmienione > 0

# --- Scheduler ---

@tasks.loop(seconds=30)
async def sprawdz_ogloszenia():
    oczekujace = pobierz_oczekujace()
    for oid, channel_id, role_id, tresc in oczekujace:
        kanal = client.get_channel(channel_id)
        if kanal is None:
            continue
        if role_id:
            wiadomosc = f"<@&{role_id}>\n\n{tresc}"
        else:
            wiadomosc = tresc
        try:
            await kanal.send(wiadomosc)
            oznacz_wyslane(oid)
        except discord.Forbidden:
            pass

# --- Komendy ---

@tree.command(name="ogloszenie", description="Zaplanuj ogłoszenie na serwerze")
@app_commands.describe(
    kanal="Kanał gdzie wysłać ogłoszenie",
    data="Data w formacie RRRR-MM-DD (np. 2025-07-20)",
    godzina="Godzina w formacie HH:MM UTC (np. 18:00)",
    tresc="Treść ogłoszenia",
    rola="Rola do oznaczenia (opcjonalne)"
)
@app_commands.default_permissions(manage_messages=True)
async def ogloszenie(
    interaction: discord.Interaction,
    kanal: discord.TextChannel,
    data: str,
    godzina: str,
    tresc: str,
    rola: discord.Role = None
):
    try:
        czas_str = f"{data} {godzina}"
        datetime.strptime(czas_str, "%Y-%m-%d %H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Zły format daty lub godziny. Użyj: data `RRRR-MM-DD`, godzina `HH:MM`",
            ephemeral=True
        )
        return

    role_id = rola.id if rola else None
    oid = zapisz_ogloszenie(interaction.guild_id, kanal.id, role_id, tresc, czas_str)

    rola_info = f" · Rola: {rola.mention}" if rola else ""
    embed = discord.Embed(
        title="✅ Ogłoszenie zaplanowane",
        color=0x5865F2
    )
    embed.add_field(name="Kanał", value=kanal.mention, inline=True)
    embed.add_field(name="Czas (UTC)", value=f"`{czas_str}`", inline=True)
    embed.add_field(name="ID", value=f"`#{oid}`", inline=True)
    embed.add_field(name="Treść", value=tresc[:500], inline=False)
    if rola:
        embed.add_field(name="Rola", value=rola.mention, inline=True)
    embed.set_footer(text="Godzina w UTC. Polska: latem UTC+2, zimą UTC+1.")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="lista", description="Pokaż nadchodzące ogłoszenia")
@app_commands.default_permissions(manage_messages=True)
async def lista(interaction: discord.Interaction):
    ogloszenia = lista_nadchodzacych(interaction.guild_id)
    if not ogloszenia:
        await interaction.response.send_message("📭 Brak zaplanowanych ogłoszeń.", ephemeral=True)
        return

    embed = discord.Embed(title="📅 Nadchodzące ogłoszenia", color=0x5865F2)
    for oid, channel_id, role_id, tresc, czas in ogloszenia:
        kanal = client.get_channel(channel_id)
        kanal_nazwa = kanal.mention if kanal else f"#{channel_id}"
        rola_info = f" · <@&{role_id}>" if role_id else ""
        embed.add_field(
            name=f"#{oid} · {czas} UTC",
            value=f"{kanal_nazwa}{rola_info}\n{tresc[:100]}{'…' if len(tresc)>100 else ''}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="anuluj", description="Anuluj zaplanowane ogłoszenie po ID")
@app_commands.describe(id="ID ogłoszenia (z /lista)")
@app_commands.default_permissions(manage_messages=True)
async def anuluj(interaction: discord.Interaction, id: int):
    if usun_ogloszenie(id, interaction.guild_id):
        await interaction.response.send_message(f"🗑️ Ogłoszenie `#{id}` zostało anulowane.", ephemeral=True)
    else:
        await interaction.response.send_message(
            f"❌ Nie znaleziono ogłoszenia `#{id}` (lub już zostało wysłane).",
            ephemeral=True
        )

# --- Start ---

@client.event
async def on_ready():
    init_db()
    await tree.sync()
    sprawdz_ogloszenia.start()
    print(f"Bot działa jako {client.user}")

client.run(TOKEN)
