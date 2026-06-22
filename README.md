# Bot ogłoszeniowy Discord

Slash commandy do planowania ogłoszeń na serwerze.

## Komendy

| Komenda | Opis |
|---------|------|
| `/ogloszenie` | Zaplanuj ogłoszenie (data, godzina, kanał, treść, rola) |
| `/lista` | Pokaż nadchodzące ogłoszenia |
| `/anuluj id:5` | Anuluj ogłoszenie po ID |

Komendy widoczne tylko dla osób z uprawnieniem **Manage Messages**.

---

## Krok 1 — Utwórz bota na Discord Developer Portal

1. Wejdź na https://discord.com/developers/applications
2. Kliknij **New Application** → podaj nazwę
3. Wejdź w zakładkę **Bot** → kliknij **Add Bot**
4. Kliknij **Reset Token** → skopiuj token (potrzebny za chwilę)
5. Zjdź niżej → włącz **Message Content Intent** (na wszelki wypadek)
6. Wejdź w **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Mention Everyone`
   - Skopiuj wygenerowany URL i wklej w przeglądarce → dodaj bota do serwera

---

## Krok 2 — Deploy na Railway (darmowy)

1. Wejdź na https://railway.app i zaloguj się przez GitHub
2. Kliknij **New Project → Deploy from GitHub repo**
3. Wgraj ten folder jako nowe repo na GitHub (lub użyj Railway CLI)
4. W Railway: kliknij projekt → **Variables** → dodaj:
   ```
   DISCORD_TOKEN = twój_token_z_kroku_1
   ```
5. Railway automatycznie uruchomi `python bot.py`

### Alternatywnie: Render.com

1. https://render.com → New → Web Service
2. Połącz z GitHub repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python bot.py`
5. Environment Variable: `DISCORD_TOKEN = ...`

---

## Uwagi

- Godziny są w **UTC**. Polska: latem +2h, zimą +1h.
  - Chcesz 18:00 polskiego czasu latem → wpisz `16:00`
- Bot sprawdza ogłoszenia co **30 sekund** — może się spóźnić max 30 sek.
- Baza danych (`ogloszenia.db`) tworzy się automatycznie przy pierwszym uruchomieniu.
- Na Railway darmowy plan może "uśpić" serwis po 30 dniach bez aktywności — wystarczy wejść na dashboard i zrestartować.
