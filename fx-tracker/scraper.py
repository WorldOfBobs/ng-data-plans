"""
Multi-source USD/NGN rate fetcher.

Source pool (5 total, show best 4):
  1. Binance P2P  — USDT/NGN parallel market
  2. Bybit P2P    — USDT/NGN parallel market (Binance backup)
  3. OKX P2P      — USDT/NGN parallel market (3rd P2P)
  4. Wise         — remittance rate (tracks parallel closely)
  5. abokiFX      — Lagos street rate scrape

Reliability: if any source deviates >OUTLIER_THRESHOLD from the median
of working sources, it's flagged as an outlier.

Always show top 4 working (non-outlier-first) sources.
"""
import asyncio
import aiohttp
import re
import logging

logger = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = {"USD", "GBP", "EUR"}
OUTLIER_THRESHOLD  = 0.08   # 8% from median = outlier
REQUEST_TIMEOUT    = aiohttp.ClientTimeout(total=12)

# ──────────────────────────────────────────────
# Individual fetchers
# ──────────────────────────────────────────────

async def _fetch_binance_p2p() -> float | None:
    """Binance P2P: avg of top-3 USDT→NGN sell ads."""
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.post(
                "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                json={
                    "fiat": "NGN", "page": 1, "rows": 5, "tradeType": "SELL",
                    "asset": "USDT", "countries": [], "proMerchantAds": False,
                    "publisherType": None, "payTypes": [],
                },
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    ads = data.get("data", [])
                    if ads:
                        prices = [float(a["adv"]["price"]) for a in ads[:3]]
                        rate = sum(prices) / len(prices)
                        if 500 < rate < 5000:
                            return rate
    except Exception as e:
        logger.debug(f"Binance P2P: {e}")
    return None

async def _fetch_bybit_p2p() -> float | None:
    """Bybit P2P: avg of top-3 USDT→NGN sell ads."""
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.post(
                "https://api2.bybit.com/fiat/otc/item/online",
                json={
                    "userId": "", "tokenId": "USDT", "currencyId": "NGN",
                    "payment": [], "side": "1", "size": "5", "page": "1",
                    "amount": "", "authMaker": False, "canTrade": False,
                },
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    items = data.get("result", {}).get("items", [])
                    if items:
                        prices = [float(i["price"]) for i in items[:3]]
                        rate = sum(prices) / len(prices)
                        if 500 < rate < 5000:
                            return rate
    except Exception as e:
        logger.debug(f"Bybit P2P: {e}")
    return None

async def _fetch_okx_p2p() -> float | None:
    """OKX P2P: avg of top-3 USDT→NGN sell ads."""
    try:
        url = (
            "https://www.okx.com/v3/c2c/tradingOrders/books"
            "?quoteCurrency=NGN&baseCurrency=USDT&side=sell&paymentMethod=all&userType=all&showTrade=false&showFollow=false&showAlreadyTraded=false&isAbleFilter=false"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get(url, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    items = data.get("data", {}).get("sell", [])
                    if items:
                        prices = [float(i["price"]) for i in items[:3]]
                        rate = sum(prices) / len(prices)
                        if 500 < rate < 5000:
                            return rate
    except Exception as e:
        logger.debug(f"OKX P2P: {e}")
    return None

async def _fetch_wise(currency: str = "USD") -> float | None:
    """Wise live rate API."""
    try:
        url = (
            f"https://wise.com/rates/history+live"
            f"?source={currency}&target=NGN&length=1&resolution=hourly&unit=day"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get(url, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    if isinstance(data, list) and data:
                        rate = float(data[-1]["value"])
                        if 500 < rate < 5000:
                            return rate
    except Exception as e:
        logger.debug(f"Wise: {e}")
    return None

async def _fetch_abokifx() -> float | None:
    """Scrape abokiFX for Lagos parallel market rate."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get("https://abokifx.com/", headers=headers) as r:
                if r.status == 200:
                    html = await r.text()
                    # Try multiple patterns to find USD parallel rate
                    patterns = [
                        r'USD[^<]*?(\d{1,2}[,.]?\d{3})',           # USD followed by 4-digit number
                        r'"usd"[^}]*?"rate"\s*:\s*"?([\d,.]+)"?',  # JSON-ish
                        r'dollar.*?(\d{1,2},\d{3})',                # dollar reference
                    ]
                    for pat in patterns:
                        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
                        if m:
                            rate_str = m.group(1).replace(",", "")
                            try:
                                rate = float(rate_str)
                                if 800 < rate < 5000:
                                    return rate
                            except ValueError:
                                continue
    except Exception as e:
        logger.debug(f"abokiFX: {e}")
    return None

# ──────────────────────────────────────────────
# Source registry — ordered by preference
# ──────────────────────────────────────────────

USD_SOURCES = [
    ("Binance P2P", _fetch_binance_p2p),
    ("Bybit P2P",   _fetch_bybit_p2p),
    ("OKX P2P",     _fetch_okx_p2p),
    ("Wise",        lambda: _fetch_wise("USD")),
    ("abokiFX",     _fetch_abokifx),
]

GBP_SOURCES = [
    ("Wise (GBP)", lambda: _fetch_wise("GBP")),
]

EUR_SOURCES = [
    ("Wise (EUR)", lambda: _fetch_wise("EUR")),
]

CURRENCY_SOURCES = {"USD": USD_SOURCES, "GBP": GBP_SOURCES, "EUR": EUR_SOURCES}

# ──────────────────────────────────────────────
# Aggregator
# ──────────────────────────────────────────────

def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

async def get_all_sources(currency: str = "USD") -> dict:
    """
    Fetch from all sources in parallel.
    Returns top 4 to display (reliable first, outliers last, unavailable hidden).
    """
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        currency = "USD"

    source_list = CURRENCY_SOURCES.get(currency, USD_SOURCES)

    # Fetch all in parallel
    results = await asyncio.gather(*[fn() for _, fn in source_list], return_exceptions=True)

    raw = {}
    for (name, _), result in zip(source_list, results):
        raw[name] = result if isinstance(result, float) else None

    live_rates = [v for v in raw.values() if v is not None]
    logger.info(f"Live sources [{currency}]: { {k:v for k,v in raw.items() if v} }")

    if not live_rates:
        # Full fallback to mock
        fallbacks = {"USD": (1580.0, 1640.0), "GBP": (2000.0, 2070.0), "EUR": (1700.0, 1760.0)}
        cbn_fb, par_fb = fallbacks[currency]
        return {
            "currency": currency,
            "display_sources": [{"name": "All sources unavailable", "rate": None, "status": "unavailable"}],
            "cbn_rate": cbn_fb,
            "parallel_rate": par_fb,
            "spread": par_fb - cbn_fb,
            "spread_pct": round((par_fb - cbn_fb) / cbn_fb * 100, 1),
            "all_reliable": False,
            "is_mock": True,
        }

    med = _median(live_rates)

    # Tag each source
    tagged = []
    for name, rate in raw.items():
        if rate is None:
            tagged.append({"name": name, "rate": None, "status": "unavailable", "deviation_pct": None})
        else:
            dev = abs(rate - med) / med
            tagged.append({
                "name": name,
                "rate": rate,
                "status": "reliable" if dev <= OUTLIER_THRESHOLD else "outlier",
                "deviation_pct": round(dev * 100, 1),
            })

    # Sort: reliable first, outlier second, unavailable last
    order = {"reliable": 0, "outlier": 1, "unavailable": 2}
    tagged.sort(key=lambda s: order[s["status"]])

    # Top 4 to display
    display = tagged[:4]

    # Consensus from reliable sources only
    reliable_rates = [s["rate"] for s in tagged if s["status"] == "reliable"]
    consensus = _median(reliable_rates) if reliable_rates else med

    # For USD: parallel = consensus of non-CBN sources. For GBP/EUR: use Wise directly.
    parallel = consensus
    # Estimate CBN as ~97% of parallel (spread is typically 3-5%)
    # Wise tracks close to parallel for USD; for GBP/EUR it's more official
    cbn = round(parallel * 0.965, 2) if currency == "USD" else round(parallel * 0.99, 2)
    spread = round(parallel - cbn, 2)
    spread_pct = round(spread / cbn * 100, 1)

    return {
        "currency": currency,
        "display_sources": display,
        "all_sources": tagged,
        "cbn_rate": cbn,
        "parallel_rate": round(parallel, 2),
        "spread": spread,
        "spread_pct": spread_pct,
        "all_reliable": all(s["status"] == "reliable" for s in tagged if s["rate"] is not None),
        "is_mock": False,
        "source": ", ".join(s["name"] for s in tagged if s["rate"] is not None),
    }

async def get_rates(currency: str = "USD") -> dict:
    """Backwards-compatible wrapper."""
    return await get_all_sources(currency)
