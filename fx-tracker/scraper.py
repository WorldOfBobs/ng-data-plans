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

async def _fetch_open_er() -> float | None:
    """open.er-api.com — free, no API key, tracks official/market USD/NGN rate."""
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                if r.status == 200:
                    data = await r.json()
                    rate = data.get("rates", {}).get("NGN")
                    if rate and 500 < rate < 5000:
                        return float(rate)
    except Exception as e:
        logger.debug(f"open.er-api: {e}")
    return None

async def _fetch_remitly(currency: str = "USD") -> float | None:
    """
    Remitly send-to-Nigeria rate — shows what the diaspora actually pays.
    Typically 2-4% above the interbank rate.
    """
    try:
        url = (
            f"https://www.remitly.com/us/en/nigeria/currency-converter"
            f"?amount=1&destinationCurrency=NGN"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get(url, headers=headers) as r:
                if r.status == 200:
                    html = await r.text()
                    m = re.search(r'1\s*USD\s*=\s*([\d,]+\.?\d*)\s*NGN', html, re.I)
                    if m:
                        rate = float(m.group(1).replace(",", ""))
                        if 500 < rate < 5000:
                            return rate
    except Exception as e:
        logger.debug(f"Remitly: {e}")
    return None

# ──────────────────────────────────────────────
# Source registry — (name, fetcher, kind)
# kind: "parallel" | "official" | "remittance"
# ──────────────────────────────────────────────

USD_SOURCES = [
    ("Bybit P2P",   _fetch_bybit_p2p,             "parallel",   None),
    ("Wise",        lambda: _fetch_wise("USD"),    "parallel",   None),
    ("open.er-api", _fetch_open_er,                "official",   None),
    ("Remitly",     lambda: _fetch_remitly("USD"), "remittance", None),
    ("Binance P2P", _fetch_binance_p2p,            "parallel",   "geo-restricted (Nigerian IPs only)"),
]

GBP_SOURCES = [
    ("Wise (GBP)",  lambda: _fetch_wise("GBP"),   "parallel", None),
    ("open.er-api", _fetch_open_er,                "official", None),
]

EUR_SOURCES = [
    ("Wise (EUR)",  lambda: _fetch_wise("EUR"),   "parallel", None),
    ("open.er-api", _fetch_open_er,                "official", None),
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
    - Uses 'official' sources for CBN rate
    - Uses 'parallel' sources for parallel market rate
    - Shows 'remittance' as context
    - Returns top 4 to display (reliable → outlier → unavailable)
    """
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        currency = "USD"

    source_list = CURRENCY_SOURCES.get(currency, USD_SOURCES)

    # Fetch all in parallel
    results = await asyncio.gather(*[fn() for _, fn, _, _ in source_list], return_exceptions=True)

    raw = {}
    for (name, _, kind, err_reason), result in zip(source_list, results):
        raw[name] = {
            "rate": result if isinstance(result, float) else None,
            "kind": kind,
            "err_reason": err_reason,  # known reason for failure, if any
        }

    live_rates = [v["rate"] for v in raw.values() if v["rate"] is not None]
    logger.info(f"Live sources [{currency}]: { {k: round(v['rate'],2) for k,v in raw.items() if v['rate']} }")

    if not live_rates:
        fallbacks = {"USD": (1580.0, 1640.0), "GBP": (2000.0, 2070.0), "EUR": (1700.0, 1760.0)}
        cbn_fb, par_fb = fallbacks[currency]
        return {
            "currency": currency,
            "display_sources": [{"name": "All sources unavailable", "rate": None, "status": "unavailable", "kind": "parallel"}],
            "cbn_rate": cbn_fb, "parallel_rate": par_fb,
            "spread": par_fb - cbn_fb,
            "spread_pct": round((par_fb - cbn_fb) / cbn_fb * 100, 1),
            "all_reliable": False, "is_mock": True,
        }

    # Compute median across all live sources (used for outlier detection)
    med = _median(live_rates)

    # Tag each source
    tagged = []
    for name, info in raw.items():
        rate, kind, err_reason = info["rate"], info["kind"], info["err_reason"]
        if rate is None:
            tagged.append({
                "name": name, "rate": None, "status": "unavailable",
                "deviation_pct": None, "kind": kind,
                "err_reason": err_reason,  # None = transient failure, str = known reason
            })
        else:
            dev = abs(rate - med) / med
            tagged.append({
                "name": name, "rate": rate, "kind": kind,
                "status": "reliable" if dev <= OUTLIER_THRESHOLD else "outlier",
                "deviation_pct": round(dev * 100, 1),
                "err_reason": None,
            })

    # Sort: reliable first, outlier second, unavailable last
    order = {"reliable": 0, "outlier": 1, "unavailable": 2}
    tagged.sort(key=lambda s: (order[s["status"]], s["name"]))

    # CBN rate: prefer official sources; fall back to estimating from parallel
    official_rates = [s["rate"] for s in tagged if s["kind"] == "official" and s["rate"] and s["status"] != "outlier"]
    cbn = round(_median(official_rates), 2) if official_rates else None

    # Parallel rate: P2P + market sources (exclude official and remittance)
    parallel_rates = [s["rate"] for s in tagged if s["kind"] == "parallel" and s["rate"] and s["status"] != "outlier"]
    # If no pure parallel, include remittance sources too
    if not parallel_rates:
        parallel_rates = [s["rate"] for s in tagged if s["rate"] and s["status"] != "outlier"]
    parallel = round(_median(parallel_rates), 2) if parallel_rates else round(med, 2)

    # If CBN not available, estimate from parallel
    if not cbn:
        cbn = round(parallel * 0.965, 2)

    spread = round(parallel - cbn, 2)
    spread_pct = round(spread / cbn * 100, 1) if cbn else 0

    return {
        "currency": currency,
        "display_sources": tagged,   # all sources, sorted
        "all_sources": tagged,
        "cbn_rate": cbn,
        "parallel_rate": parallel,
        "spread": spread,
        "spread_pct": spread_pct,
        "all_reliable": all(s["status"] == "reliable" for s in tagged if s["rate"] is not None),
        "is_mock": False,
        "source": ", ".join(s["name"] for s in tagged if s["rate"] is not None),
    }

async def get_rates(currency: str = "USD") -> dict:
    """Backwards-compatible wrapper."""
    return await get_all_sources(currency)
