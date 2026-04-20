import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

_cache = {"tickers": [], "fetched_at": None}
CACHE_TTL_HOURS = 24  # Refresh ticker list once per day


def fetch_sp500_tickers():
    """
    Fetch current S&P 500 constituents from Wikipedia.
    Uses Wikipedia's REST API to get the HTML table, then parses it.
    Falls back to a hardcoded list of top 100 if Wikipedia is unavailable.
    """
    global _cache

    # Return cached if still fresh
    if _cache["tickers"] and _cache["fetched_at"]:
        age = datetime.now() - _cache["fetched_at"]
        if age < timedelta(hours=CACHE_TTL_HOURS):
            logger.info(f"Using cached tickers ({len(_cache['tickers'])} tickers, age: {age})")
            return _cache["tickers"]

    logger.info("Fetching S&P 500 constituents from Wikipedia...")

    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SP500Dashboard/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        # Parse the first table on the page
        tables = pd.read_html(StringIO(resp.text))
        df = tables[0]

        # The ticker column is "Symbol" on Wikipedia
        tickers = df["Symbol"].tolist()

        # Clean tickers: Wikipedia uses "." for BRK.B but Yahoo uses "-"
        tickers = [t.replace(".", "-") for t in tickers]
        tickers = [t.strip() for t in tickers if isinstance(t, str) and t.strip()]

        logger.info(f"Fetched {len(tickers)} tickers from Wikipedia")
        _cache["tickers"] = tickers
        _cache["fetched_at"] = datetime.now()
        return tickers

    except Exception as e:
        logger.warning(f"Wikipedia fetch failed: {e}. Using fallback list.")
        return _get_fallback_tickers()


def _get_fallback_tickers():
    """Fallback: top 100 S&P 500 tickers by market cap if Wikipedia is unavailable"""
    fallback = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
        "LLY","V","UNH","XOM","MA","COST","HD","PG","JNJ","ABBV",
        "BAC","NFLX","CRM","WMT","CVX","MRK","ORCL","KO","AMD","PEP",
        "ACN","TMO","MCD","ADBE","LIN","ABT","TXN","CSCO","DHR","NKE",
        "WFC","NEE","PM","AMGN","RTX","INTU","ISRG","SPGI","GE","BKNG",
        "HON","QCOM","LOW","CAT","IBM","GS","UNP","ELV","SYK","MS",
        "AMAT","AXP","DE","BLK","VRTX","GILD","ADI","MMC","PLD","CB",
        "MDLZ","TJX","CI","SO","MO","DUK","CL","SHW","CME","ZTS",
        "EOG","NOC","MCO","AON","ITW","BSX","ETN","PGR","REGN","HUM",
        "USB","TGT","MMM","APD","F","GM","PYPL","UBER","SNOW","PANW"
    ]
    _cache["tickers"] = fallback
    _cache["fetched_at"] = datetime.now()
    return fallback


def get_cache_info():
    return {
        "count": len(_cache["tickers"]),
        "fetched_at": _cache["fetched_at"].strftime("%Y-%m-%d %H:%M:%S") if _cache["fetched_at"] else None,
        "source": "Wikipedia" if len(_cache["tickers"]) > 100 else "Fallback (top 100)"
    }
