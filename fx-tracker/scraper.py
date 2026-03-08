"""
Rate fetching logic.
Sources (tried in order):
1. exchangerate-host for official/CBN-ish USD/NGN
2. Binance P2P NGN/USDT as parallel market proxy (best free source)
3. Hardcoded mock for dev/testing
"""
import aiohttp
import logging

logger = logging.getLogger(__name__)

BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
EXCHANGERATE_HOST = "https://api.exchangerate.host/latest?base=USD&symbols=NGN"

async def fetch_official_rate() -> float | None:
    """Fetch USD/NGN from exchangerate.host (roughly tracks CBN)."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(EXCHANGERATE_HOST) as r:
                if r.status == 200:
                    data = await r.json()
                    rate = data.get("rates", {}).get("NGN")
                    if rate:
                        logger.info(f"Official rate fetched: {rate}")
                        return float(rate)
    except Exception as e:
        logger.warning(f"Official rate fetch failed: {e}")
    return None

async def fetch_parallel_rate() -> tuple[float | None, str]:
    """
    Fetch parallel market rate via Binance P2P NGN/USDT.
    Returns (rate, source_label).
    """
    try:
        payload = {
            "fiat": "NGN",
            "page": 1,
            "rows": 5,
            "tradeType": "SELL",  # sellers selling USDT for NGN = NGN/USDT rate
            "asset": "USDT",
            "countries": [],
            "proMerchantAds": False,
            "publisherType": None,
            "payTypes": [],
        }
        headers = {"Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.post(BINANCE_P2P_URL, json=payload, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    ads = data.get("data", [])
                    if ads:
                        prices = [float(a["adv"]["price"]) for a in ads[:3]]
                        avg = sum(prices) / len(prices)
                        logger.info(f"Binance P2P rate: {avg:.2f} (avg of {len(prices)} ads)")
                        return avg, "Binance P2P"
    except Exception as e:
        logger.warning(f"Binance P2P fetch failed: {e}")

    return None, "mock"

async def get_rates() -> dict:
    """
    Returns dict with cbn_rate, parallel_rate, source.
    Falls back gracefully.
    """
    official = await fetch_official_rate()
    parallel, par_source = await fetch_parallel_rate()

    # Fallback mock values if all sources fail
    if not official:
        official = 1580.0  # approximate CBN rate
    if not parallel:
        parallel = 1620.0  # approximate parallel rate
        par_source = "mock"

    return {
        "cbn_rate": official,
        "parallel_rate": parallel,
        "source": f"CBN:exchangerate.host, Parallel:{par_source}",
    }
