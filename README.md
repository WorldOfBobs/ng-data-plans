# Nigeria Daily Tools

A suite of Nigerian daily-utility tools. All run locally on the Mac mini.

---

## 🤖 FX Bob — Multi-Country FX Rate Tracker

Two Telegram bot instances, one codebase:

| Bot | Handle | Folder | `DEFAULT_COUNTRY` |
|-----|--------|--------|-------------------|
| Nigeria | `@NigeriaFXBob` | `fx-tracker/` | `NG` |
| Global  | `@FXbob`        | `fx-tracker-global/` | `ALL` |

### Quick Start

```bash
# Check status of both bots
./manage.sh status

# Start both
./manage.sh start

# Start just Nigeria bot
./manage.sh start nigeria

# Restart global bot
./manage.sh restart global

# Tail logs
./manage.sh logs
./manage.sh logs nigeria
```

### Install as macOS Services (auto-restart on crash + boot)

```bash
# Install both as launchd agents
./install-services.sh

# Or individual
./install-services.sh nigeria
./install-services.sh global

# Remove
./install-services.sh remove
```

### Adding a new country bot

1. `cp -r fx-tracker fx-tracker-kenya`
2. Edit `fx-tracker-kenya/.env`:
   ```
   BOT_TOKEN=<new bot token>
   DEFAULT_COUNTRY=KE
   ```
3. Create a launchd plist: copy `launchd/com.fxbob.nigeria.plist`, update paths + label
4. `./manage.sh start` or `./install-services.sh`

### Countries

| Code | Country | Currency | Status |
|------|---------|----------|--------|
| NG | Nigeria | NGN | ✅ Live |
| GH | Ghana | GHS | ✅ Live |
| KE | Kenya | KES | ✅ Live |
| ZA | South Africa | ZAR | 🚧 Soon |
| EG | Egypt | EGP | 🚧 Soon |
| PH | Philippines | PHP | 🚧 Soon |
| IN | India | INR | 🚧 Soon |

### Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Onboard + country picker (global) or direct welcome (country bot) |
| `/rate` | Current USD rate |
| `/rate GBP` | GBP rate |
| `/rate EUR` | EUR rate |
| `/history` | 7-day trend |
| `/chart` | 24h ASCII chart |
| `/settings` | View all settings |
| `/threshold 2` | Alert threshold % |
| `/direction up\|down\|both` | Alert direction |
| `/interval 1h` | Proactive rate push cadence |
| `/briefing 7` | Daily briefing hour (UTC) |
| `/country` | Change country (global bot only) |
| `/stop` | Pause alerts |
| `/subscribe` | Resume alerts |

---

## 🗺️ Fuel Queue Map

FastAPI backend + Leaflet.js frontend. Crowdsourced fuel station queue reports.

```bash
cd fuel-map
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python3 main.py
# Open http://localhost:8000
```

---

## 📱 Data Plans Comparator

Static site. Zero dependencies. GitHub Pages ready.

```bash
open data-plans/index.html
# Or deploy: push to GitHub → enable Pages on main branch
```

---

## 🔌 NEPA Power Outage Bot

Crowdsourced outage reporting for Nigerian neighborhoods.

```bash
# 1. Create bot via @BotFather → paste token into nepa-bot/.env
# 2. cd nepa-bot && python3 -m venv venv && venv/bin/pip install -r requirements.txt
# 3. venv/bin/python3 bot.py
```

---

## Repo Structure

```
nigeria-daily-tools/
├── fx-tracker/           — @NigeriaFXBob (DEFAULT_COUNTRY=NG)
├── fx-tracker-global/    — @FXbob (DEFAULT_COUNTRY=ALL)
├── fuel-map/             — Fuel queue map
├── data-plans/           — Data plan comparator (static)
├── nepa-bot/             — Power outage bot
├── manage.sh             — Start/stop/status all FX bots
├── install-services.sh   — Register as macOS launchd agents
└── launchd/              — plist templates
```
