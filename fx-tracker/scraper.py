"""
Multi-source USD/NGN rate fetcher.
Sources (all fetched in parallel):
  1. Binance P2P (USDT/NGN) — best parallel market proxy
  2. abokiFX         — Lagos street parallel market
  3. Wise (TransferWise) — remittance rate (close to parallel)
  4. exchangerate.host   — official/CBN-ish rate

Reliability check: if any source deviates >OUTLIER_THRESHOLD from the median,
it's flagged as unreliable.
"""
import asyncio
import aiohttp
import re
import logging

logger = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = {"USD", "GBP", "EUR"}
OUTLIER_THRESHOLD = 0.08   # 8% deviation from median = flagged as unreliable
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)

# ──────────────────────────────────────────────
# Individual source fetchers
# ──────────────────────────────────────────────

async def _fetch_binance_p2p() -> float | None:
    """Binance P2P: average of top 3 USDT→NGN sell ads."""
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    payload = {
        "fiat": "NGN", "page": 1, "rows": 5, "tradeType": "SELL",
        "asset": "USDT", "countries": [], "proMerchantAds": False,
        "publisherType": None, "payTypes": [],
    }
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.post(url, json=payload,
                              headers={"Content-Type": "application/json"}) as r:
                if r.status == 200:
                    data = await r.json()
                    ads = data.get("data", [])
                    if ads:
                        prices = [float(a["adv"]["price"]) for a in ads[:3]]
                        return sum(prices) / len(prices)
    except Exception as e:
        logger.warning(f"Binance P2P failed: {e}")
    return None

async def _fetch_abokifx() -> float | None:
    """Scrape abokiFX for Lagos parallel market USD/NGN."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get("https://abokifx.com", headers=headers) as r:
                if r.status == 200:
                    html = await r.text()
                    # abokiFX shows rates in a table; look for USD row
                    # Pattern: USD followed by numbers like 1,620 or 1620
                    match = re.search(
                        r'USD.*?(\d{1,4}[,.]?\d{3})',
                        html, re.DOTALL | re.IGNORECASE
                    )
                    if match:
                        rate_str = match.group(1).replace(",", "")
                        rate = float(rate_str)
                        if 500 < rate < 5000:  # sanity check
                            return rate
    except Exception as e:
        logger.warning(f"abokiFX scrape failed: {e}")
    return None

async def _fetch_wise(currency="USD") -> float | None:
    """Wise (TransferWise) public rate API."""
    try:
        url = f"https://wise.com/gb/currency-converter/{currency.lower()}-to-ngn-rate"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        # Use Wise's internal rate API
        api_url = f"https://wise.com/rates/history+live?source={currency}&target=NGN&length=1&resolution=hourly&unit=day"
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get(api_url, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    # Response is a list of {value, time} objects
                    if isinstance(data, list) and data:
                        rate = float(data[-1]["value"])
                        if 500 < rate < 5000:
                            return rate
    except Exception as e:
        logger.warning(f"Wise fetch failed: {e}")
    return None

async def _fetch_exchangerate_host(currency="USD") -> float | None:
    """exchangerate.host — tracks CBN-ish official rate."""
    try:
        url = f"https://api.exchangerate.host/latest?base={currency}&symbols=NGN"
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as s:
            async with s.get(url) as r:
                if r.status == 200:
                    data = await r.json()
                    rate = data.get("rates", {}).get("NGN")
                    if rate and 500 < rate < 5000:
                        return float(rate)
    except Exception as e:
        logger.warning(f"exchangerate.host failed: {e}")
    return None

# ──────────────────────────────────────────────
# Aggregator
# ──────────────────────────────────────────────

def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)

async def get_all_sources(currency="USD") -> dict:
    """
    Fetch from all sources in parallel.
    Returns:
      sources: list of {name, rate, reliable}
      consensus_rate: median of reliable sources (None if all failed)
      cbn_rate: from exchangerate.host
      parallel_rate: consensus of parallel sources
      all_reliable: bool — True if all sources within OUTLIER_THRESHOLD of each other
    """
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        currency = "USD"

    # Fetch all in parallel
    binance, aboki, wise, official = await asyncio.gather(
        _fetch_binance_p2p() if currency == "USD" else asyncio.sleep(0, result=None),
        _fetch_abokifx()     if currency == "USD" else asyncio.sleep(0, result=None),
        _fetch_wise(currency),
        _fetch_exchangerate_host(currency),
    )

    raw_sources = {
        "Binance P2P": binance,
        "abokiFX":     aboki,
        "Wise":        wise,
        "CBN (official)": official,
    }

    # Filter out None
    live = {k: v for k, v in raw_sources.items() if v is not None}
    logger.info(f"Live sources for {currency}: {live}")

    if not live:
        # Full fallback
        fallbacks = {"USD": (1580.0, 1640.0), "GBP": (2000.0, 2070.0), "EUR": (1700.0, 1760.0)}
        cbn_fb, par_fb = fallbacks.get(currency, (1580.0, 1640.0))
        return {
            "currency": currency,
            "sources": [{"name": "Fallback (mock)", "rate": par_fb, "reliable": None, "is_official": False}],
            "consensus_rate": par_fb,
            "cbn_rate": cbn_fb,
            "parallel_rate": par_fb,
            "all_reliable": False,
            "is_mock": True,
        }

    # Compute median across all live sources
    all_rates = list(live.values())
    med = _median(all_rates)

    # Tag sources with reliability
    sources = []
    for name, rate in raw_sources.items():
        if rate is None:
            sources.append({"name": name, "rate": None, "reliable": None, "is_official": name == "CBN (official)"})
            continue
        deviation = abs(rate - med) / med
        sources.append({
            "name": name,
            "rate": rate,
            "reliable": deviation <= OUTLIER_THRESHOLD,
            "deviation_pct": round(deviation * 100, 1),
            "is_official": name == "CBN (official)",
        })

    reliable_rates = [s["rate"] for s in sources if s["reliable"] is True]
    unreliable = [s for s in sources if s["reliable"] is False]

    # Consensus = median of reliable rates; fallback to all
    consensus = _median(reliable_rates) if reliable_rates else med

    # Separate CBN from parallel
    cbn = official or (consensus * 0.97)  # estimate if CBN not available
    parallel_sources = [s["rate"] for s in sources
                        if s["rate"] and s["reliable"] is not False and not s["is_official"]]
    parallel = _median(parallel_sources) if parallel_sources else consensus

    spread = parallel - cbn
    spread_pct = (spread / cbn * 100) if cbn else 0

    return {
        "currency": currency,
        "sources": sources,
        "consensus_rate": round(consensus, 2),
        "cbn_rate": round(cbn, 2),
        "parallel_rate": round(parallel, 2),
        "spread": round(spread, 2),
        "spread_pct": round(spread_pct, 1),
        "all_reliable": len(unreliable) == 0 and len(reliable_rates) >= 2,
        "unreliable_sources": [s["name"] for s in unreliable],
        "is_mock": False,
    }

async def get_rates(currency="USD") -> dict:
    """Backwards-compatible wrapper — returns same shape as before + extra source info."""
    result = await get_all_sources(currency)
    result["source"] = ", ".join(
        s["name"] for s in result["sources"] if s["rate"] is not None
    )
    return result
