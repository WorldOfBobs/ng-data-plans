# Nigeria Daily Tools — Living Notes
> Suite of Telegram bots for Nigerian/African daily utility needs.
> Update this file when significant changes are made.

**Repo:** `~/dev/nigeria-daily-tools/`
**Discord:** Degens category (site-edits channel)
**Manage:** `bash manage.sh [start|stop|status|logs] [name|all]`
**Install as services:** `./install-services.sh`

---

## Live Bots

| Bot | Handle | Token env | Country | Status |
|-----|--------|-----------|---------|--------|
| Nigeria FX | `@NigeriaFXBob` | in `fx-tracker/.env` | NG | ✅ Live |
| Global FX | `@FXbob_bot` | in `instances/global/.env` | ALL | ✅ Live |

**Architecture:** Single codebase `fx-tracker/`, instances in `instances/<country>/`. One Python process per instance.
**Last updated:** 3/27/26 08:55

---

## FX Tracker Bot

**Sources (5):** Bybit P2P, Wise, open.er-api, Remitly, Binance P2P (geo-locked)
**Commands:** `/rate`, `/compare`, `/history`, `/help`
**DB:** `fx-tracker/fx_rates.db` (SQLite)
**Wise referral:** personal referral link wired (kevink5144)

### Affiliates
- **Wise:** Partnerize at `wise.com/gb/affiliate-program/` (£10/conversion). `WISE_AFFILIATE_URL` in .env = personal referral only (no cash from Wise program yet)
- **Remitly:** Impact.com publisher account (Gravy) — pending approval

---

## ParallelRate (`parallelrate.com`)

**Repo:** `/tmp/parallelrate/` (also `WorldOfBobs/parallelrate` on GitHub)
**Deploy:** GitHub Pages, custom domain, CNAME in repo
**What it is:** Landing page for `@FXbob_bot` — live parallel rate tracker for NG/GH/KE/ZA
**Affiliate slots:** Wise + Remitly (wired but blank until signed up)
**AdSense:** Not yet added

---

## Countries Live / Planned

| Handle | Country | Status |
|--------|---------|--------|
| `@NigeriaFXBob` | Nigeria (NG) | ✅ Live |
| `@GhanaFXBot` | Ghana (GH) | ✅ Live |
| `@KenyaFXBot` | Kenya (KE) | ✅ Live |
| `@SouthAfricaFXBot` | South Africa (ZA) | ✅ Live |
| `@FXbob_bot` | Global (ALL) | ✅ Live |
| `@EgyptFXBot` | Egypt | 📋 Pending |
| `@EthiopiaFXBot` | Ethiopia | 📋 Pending |
| `@TanzaniaFXBot` | Tanzania | 📋 Pending |
| `@UgandaFXBot` | Uganda | 📋 Pending |

**Naming rule:** Telegram requires "bot" suffix → `{Country}FXBot` pattern

---

## Other Tools (Built, Not Running)

- **NEPA bot** — code written, no token yet
- **Fuel Map** — code written, no token yet

---

## Pending

- [ ] Remitly affiliate approved (Impact.com — pending ~2 biz days from 2026-03-21)
- [ ] Add Egypt/Ethiopia/Tanzania/Uganda bots (need BotFather tokens)
- [ ] AdSense on parallelrate.com (apply after jollofdata approved first)
- [ ] launchd plist for auto-restart on crash/reboot
- [ ] NEPA bot + Fuel Map tokens from BotFather
