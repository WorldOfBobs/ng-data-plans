# 🇳🇬 Nigeria Daily Tools

Four practical tools for everyday life in Nigeria.

---

## 1. 💸 FX Rate Tracker (`fx-tracker/`)
Telegram bot tracking USD/NGN parallel market vs CBN official rate.
- Polls Binance P2P for real parallel market rate
- Alerts subscribers on >2% rate moves
- 24h chart via `/chart`

**Setup:**
```bash
cd fx-tracker
cp .env.example .env  # add your BOT_TOKEN
pip install -r requirements.txt
python bot.py
```
Get a token: message @BotFather on Telegram → `/newbot`

---

## 2. 📱 Data Plan Comparator (`data-plans/`)
Static website comparing MTN / Airtel / Glo / 9mobile data plans by value.
- Filter by size, price, network
- Sorted by MB-per-₦100
- Tap any card to dial the USSD code

**Deploy (GitHub Pages):**
```bash
cd data-plans
# push to GitHub, enable Pages on main branch / root
```
Or just open `index.html` in a browser — no server needed.

---

## 3. ⚡ NEPA Alert Bot (`nepa-bot/`)
Crowdsourced Telegram bot for power outage reports.
- Set your area with `/area`
- `/out` and `/back` to report, notifies neighbours automatically

**Setup:**
```bash
cd nepa-bot
cp .env.example .env  # add your BOT_TOKEN
pip install -r requirements.txt
python bot.py
```

---

## 4. ⛽ Fuel Queue Map (`fuel-map/`)
Interactive web map for reporting petrol station availability and queue length.
- Crowdsourced reports with auto-expiry (6h)
- Color-coded markers (green/yellow/red)
- Rate-limited (1 report per station per 30 min per IP)
- Pre-seeded with stations in Lagos, Abuja, PH, Kano

**Setup:**
```bash
cd fuel-map
pip install -r requirements.txt
python main.py
# Open http://localhost:8000
```

---

## Quick start (all four):
```bash
cd fx-tracker   && pip install -r requirements.txt
cd ../nepa-bot  && pip install -r requirements.txt
cd ../fuel-map  && pip install -r requirements.txt
# data-plans needs no install
```
