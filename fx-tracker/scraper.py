"""
Rate fetching logic.
Sources:
- Binance P2P for USD/NGN parallel market rate
- exchangerate.host for CBN-ish official rates (USD, GBP, EUR)
"""
import aiohttp
import logging

logger = logging.getLogger(__name__)

BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
EXCHANGERATE_URL = "https://api.exchangerate.host/latest?base={base}&symbols=NGN"

SUPPORTED_CURRENCIES = {"USD", "GBP", "EUR"}

async def fetch_official_rate(currency="USD") -> float | None:
    """Fetch official NGN rate for a given currency from exchangerate.host."""
    try:
        url = EXCHANGERATE_URL.format(base=currency)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(url) as r:
                if r.status == 200:
                    data = await r.json()
                    rate = data.get("rates", {}).get("NGN")
                    if rate:
                        logger.info(f"Official {currency}/NGN: {rate}")
                        return float(rate)
    except Exception as e:
        logger.warning(f"Official rate fetch failed ({currency}): {e}")
    return None

async def fetch_parallel_rate_usd() -> tuple[float | None, str]:
    """Fetch parallel market rate via Binance P2P USDT/NGN."""
    try:
        payload = {
            "fiat": "NGN", "page": 1, "rows": 5,
            "tradeType": "SELL", "asset": "USDT",
            "countries": [], "proMerchantAds": False,
            "publisherType": None, "payTypes": [],
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.post(BINANCE_P2P_URL, json=payload,
                              headers={"Content-Type": "application/json"}) as r:
                if r.status == 200:
                    data = await r.json()
                    ads = data.get("data", [])
                    if ads:
                        prices = [float(a["adv"]["price"]) for a in ads[:3]]
                        avg = sum(prices) / len(prices)
                        logger.info(f"Binance P2P USD/NGN parallel: {avg:.2f}")
                        return avg, "Binance P2P"
    except Exception as e:
        logger.warning(f"Binance P2P fetch failed: {e}")
    return None, "mock"

async def get_rates(currency="USD") -> dict:
    """
    Returns dict with cbn_rate, parallel_rate, source for given currency.
    Parallel rate only available for USD (via Binance P2P).
    For GBP/EUR, parallel is estimated from USD parallel spread.
    """
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        currency = "USD"

    official_usd = await fetch_official_rate("USD")
    official = await fetch_official_rate(currency) if currency != "USD" else official_usd
    parallel_usd, par_source = await fetch_parallel_rate_usd()

    # Fallbacks
    fallbacks = {"USD": 1580.0, "GBP": 2000.0, "EUR": 1720.0}
    if not official_usd:
        official_usd = fallbacks["USD"]
    if not official:
        official = fallbacks.get(currency, 1580.0)
    if not parallel_usd:
        parallel_usd = 1620.0
        par_source = "mock"

    # Estimate parallel for non-USD by applying same spread ratio
    if currency == "USD":
        parallel = parallel_usd
    else:
        spread_ratio = parallel_usd / official_usd
        parallel = official * spread_ratio

    return {
        "currency": currency,
        "cbn_rate": round(official, 2),
        "parallel_rate": round(parallel, 2),
        "source": f"CBN:exchangerate.host, Parallel:{par_source}",
    }
