"""
Multi-source FX Rate Fetcher — multi-country edition.

Supports local currencies: NGN, GHS, KES (and more via COUNTRY_CONFIG)
Foreign currencies (query side): USD, GBP, EUR

Source pool per local currency:
  - Bybit P2P    : USDT/<local> parallel market (generic — works for any Bybit-listed fiat)
  - Binance P2P  : USDT/<local> parallel market (geo-restricted for some countries)
  - Wise         : remittance rate
  - open.er-api  : official/interbank rate
  - Remitly      : diaspora corridor rate (USD→NGN only)

Reliability: flag any source deviating >OUTLIER_THRESHOLD from median as outlier.
"""
import asyncio
import aiohttp
import re
import logging

logger = logging.getLogger(__name__)

SUPPORTED_FOREIGN = {"USD", "GBP", "EUR"}   # query-side currencies
SUPPORTED_LOCAL   = {"NGN", "GHS", "KES"}   # target-side local currencies

# Backwards compat alias (used in cmd_rate)
SUPPORTED_CURRENCIES = SUPPORTED_FOREIGN

OUTLIER_THRESHOLD = 0.08   # 8% from median = outlier
REQUEST_TIMEOUT   = aiohttp.ClientTimeout(total=12)

# Sanity ranges per local currency (USD equivalent so we scale)
# Stored as (min, max) for the local rate per 1 USD
RATE_SANITY = {
    "NGN": (500, 5000),
    "GHS": (10, 80),
    "KES": (80, 250),
    "ZAR": (15, 35),
    "EGP": (30, 100),
}

# ──────────────────────────────────────────────
# Generic fetchers (take local currency as param)
# ──────────────────────────────────────────────

async def _fetch_bybit_p2p(local: str) -> float | None:
    """Bybit P2P: avg of top-3 USDT→{local} sell ads."""
    lo, hi = RATE_SANITY.get(local, (1, 1_000_000))
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.post(
                "https://api2.bybit.com/fiat/otc/item/online",
                json={
                    "userId": "", "tokenId": "USDT", "currencyId": local,
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
                        if lo < rate < hi:
                            return rate
    except Exception as e:
        logger.debug(f"Bybit P2P {local}: {e}")
    return None

async def _fetch_binance_p2p(local: str) -> float | None:
    """Binance P2P: avg of top-3 USDT→{local} sell ads (geo-restricted in some regions)."""
    lo, hi = RATE_SANITY.get(local, (1, 1_000_000))
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.post(
                "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                json={
                    "fiat": local, "page": 1, "rows": 5, "tradeType": "SELL",
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
                        if lo < rate < hi:
                            return rate
    except Exception as e:
        logger.debug(f"Binance P2P {local}: {e}")
    return None

async def _fetch_wise(foreign: str, local: str) -> float | None:
    """Wise live rate: {foreign}→{local}."""
    lo, hi = RATE_SANITY.get(local, (1, 1_000_000))
    try:
        url = (
            f"https://wise.com/rates/history+live"
            f"?source={foreign}&target={local}&length=1&resolution=hourly&unit=day"
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
                        if lo < rate < hi:
                            return rate
    except Exception as e:
        logger.debug(f"Wise {foreign}/{local}: {e}")
    return None

async def _fetch_open_er(foreign: str, local: str) -> float | None:
    """open.er-api.com — free, no API key — returns official/interbank rate."""
    lo, hi = RATE_SANITY.get(local, (1, 1_000_000))
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get(f"https://open.er-api.com/v6/latest/{foreign}") as r:
                if r.status == 200:
                    data = await r.json()
                    rate = data.get("rates", {}).get(local)
                    if rate and lo < rate < hi:
                        return float(rate)
    except Exception as e:
        logger.debug(f"open.er-api {foreign}/{local}: {e}")
    return None

async def _fetch_remitly(foreign: str, local: str) -> float | None:
    """
    Remitly send-to-country rate — what the diaspora actually gets.
    Typically 2-4% above the interbank rate. Currently supports USD→NGN only.
    """
    if foreign != "USD" or local != "NGN":
        return None
    lo, hi = RATE_SANITY.get(local, (1, 1_000_000))
    try:
        url = (
            "https://www.remitly.com/us/en/nigeria/currency-converter"
            "?amount=1&destinationCurrency=NGN"
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
                        if lo < rate < hi:
                            return rate
    except Exception as e:
        logger.debug(f"Remitly: {e}")
    return None

# ──────────────────────────────────────────────
# Source registry builder
# Each entry: (display_name, async_fn, kind, err_reason_or_None)
# kind: "parallel" | "official" | "remittance"
# ──────────────────────────────────────────────

def _build_sources(foreign: str, local: str) -> list:
    """Return the source list for a given foreign/local pair."""
    sources = []

    # P2P parallel sources
    sources.append((
        "Bybit P2P",
        lambda f=foreign, l=local: _fetch_bybit_p2p(l),
        "parallel", None
    ))

    # Binance P2P — geo-restricted for NGN
    binance_err = "geo-restricted (Nigerian IPs only)" if local == "NGN" else None
    sources.append((
        "Binance P2P",
        lambda f=foreign, l=local: _fetch_binance_p2p(l),
        "parallel", binance_err
    ))

    # Wise
    sources.append((
        "Wise",
        lambda f=foreign, l=local: _fetch_wise(f, l),
        "parallel" if local in ("NGN", "GHS", "KES") else "remittance",
        None
    ))

    # open.er-api (official)
    sources.append((
        "open.er-api",
        lambda f=foreign, l=local: _fetch_open_er(f, l),
        "official", None
    ))

    # Remitly — NGN only
    if local == "NGN" and foreign == "USD":
        sources.append((
            "Remitly",
            lambda: _fetch_remitly("USD", "NGN"),
            "remittance", None
        ))

    return sources

# ──────────────────────────────────────────────
# Aggregator
# ──────────────────────────────────────────────

def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

async def get_all_sources(foreign: str = "USD", local: str = "NGN") -> dict:
    """
    Fetch from all sources for the given foreign/local pair.
    Returns structured result with CBN/official rate, parallel rate, spread, source details.
    """
    foreign = foreign.upper()
    local   = local.upper()
    if foreign not in SUPPORTED_FOREIGN:
        foreign = "USD"
    if local not in SUPPORTED_LOCAL:
        local = "NGN"

    source_list = _build_sources(foreign, local)

    # Fetch all in parallel
    results = await asyncio.gather(*[fn() for _, fn, _, _ in source_list], return_exceptions=True)

    raw = {}
    for (name, _, kind, err_reason), result in zip(source_list, results):
        raw[name] = {
            "rate": result if isinstance(result, float) else None,
            "kind": kind,
            "err_reason": err_reason,
        }

    live_rates = [v["rate"] for v in raw.values() if v["rate"] is not None]
    logger.info(f"Live sources [{foreign}/{local}]: { {k: round(v['rate'],2) for k,v in raw.items() if v['rate']} }")

    if not live_rates:
        # Fallback estimates (rough mid-2025 values)
        fallbacks = {
            ("USD", "NGN"): (1580.0, 1640.0),
            ("GBP", "NGN"): (2000.0, 2070.0),
            ("EUR", "NGN"): (1700.0, 1760.0),
            ("USD", "GHS"): (14.5,   15.5),
            ("USD", "KES"): (128.0,  132.0),
        }
        cbn_fb, par_fb = fallbacks.get((foreign, local), (1.0, 1.1))
        return {
            "foreign": foreign, "local": local,
            "currency": f"{foreign}/{local}",
            "display_sources": [{"name": "All sources unavailable", "rate": None, "status": "unavailable", "kind": "parallel"}],
            "cbn_rate": cbn_fb, "parallel_rate": par_fb,
            "spread": par_fb - cbn_fb,
            "spread_pct": round((par_fb - cbn_fb) / cbn_fb * 100, 1),
            "all_reliable": False, "is_mock": True,
        }

    med = _median(live_rates)

    tagged = []
    for name, info in raw.items():
        rate, kind, err_reason = info["rate"], info["kind"], info["err_reason"]
        if rate is None:
            tagged.append({
                "name": name, "rate": None, "status": "unavailable",
                "deviation_pct": None, "kind": kind,
                "err_reason": err_reason,
            })
        else:
            dev = abs(rate - med) / med
            tagged.append({
                "name": name, "rate": rate, "kind": kind,
                "status": "reliable" if dev <= OUTLIER_THRESHOLD else "outlier",
                "deviation_pct": round(dev * 100, 1),
                "err_reason": None,
            })

    order = {"reliable": 0, "outlier": 1, "unavailable": 2}
    tagged.sort(key=lambda s: (order[s["status"]], s["name"]))

    official_rates = [s["rate"] for s in tagged if s["kind"] == "official" and s["rate"] and s["status"] != "outlier"]
    cbn = round(_median(official_rates), 2) if official_rates else None

    parallel_rates = [s["rate"] for s in tagged if s["kind"] == "parallel" and s["rate"] and s["status"] != "outlier"]
    if not parallel_rates:
        parallel_rates = [s["rate"] for s in tagged if s["rate"] and s["status"] != "outlier"]
    parallel = round(_median(parallel_rates), 2) if parallel_rates else round(med, 2)

    if not cbn:
        cbn = round(parallel * 0.965, 2)

    spread = round(parallel - cbn, 2)
    spread_pct = round(spread / cbn * 100, 1) if cbn else 0

    return {
        "foreign": foreign,
        "local": local,
        "currency": f"{foreign}/{local}",
        "display_sources": tagged,
        "all_sources": tagged,
        "cbn_rate": cbn,
        "parallel_rate": parallel,
        "spread": spread,
        "spread_pct": spread_pct,
        "all_reliable": all(s["status"] == "reliable" for s in tagged if s["rate"] is not None),
        "is_mock": False,
        "source": ", ".join(s["name"] for s in tagged if s["rate"] is not None),
    }

async def get_rates(foreign: str = "USD", local: str = "NGN") -> dict:
    """Backwards-compatible wrapper."""
    return await get_all_sources(foreign, local)
