import json
import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_FILE = "cache.json"

# TTL par catégorie
TTL = {
    "prices":       timedelta(hours=20),   # J-1 : recalcul chaque jour ouvré
    "fundamentals": timedelta(days=7),     # Données trimestrielles
    "fmp":          timedelta(hours=20),   # Consensus analystes ~quotidien
    "tickers":      timedelta(hours=24),   # Liste S&P 500
}


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Cache read error: {e}")
        return {}


def _save_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Cache write error: {e}")


def is_fresh(category):
    """Return True if cache entry exists and is within TTL."""
    cache = _load_cache()
    entry = cache.get(category)
    if not entry or "saved_at" not in entry:
        return False
    saved_at = datetime.fromisoformat(entry["saved_at"])
    age = datetime.now() - saved_at
    fresh = age < TTL[category]
    if fresh:
        logger.info(f"Cache HIT [{category}] — age: {age}, TTL: {TTL[category]}")
    else:
        logger.info(f"Cache MISS [{category}] — age: {age}, TTL: {TTL[category]}")
    return fresh


def get(category):
    """Return cached data for category, or None if missing/stale."""
    if not is_fresh(category):
        return None
    cache = _load_cache()
    return cache.get(category, {}).get("data")


def set(category, data):
    """Save data to cache with current timestamp."""
    cache = _load_cache()
    cache[category] = {
        "saved_at": datetime.now().isoformat(),
        "data": data
    }
    _save_cache(cache)
    logger.info(f"Cache SET [{category}]")


def get_cache_status():
    """Return a summary of cache state for the API response."""
    cache = _load_cache()
    status = {}
    for category in TTL:
        entry = cache.get(category)
        if entry and "saved_at" in entry:
            saved_at = datetime.fromisoformat(entry["saved_at"])
            age = datetime.now() - saved_at
            fresh = age < TTL[category]
            status[category] = {
                "saved_at": entry["saved_at"],
                "age_minutes": round(age.total_seconds() / 60, 1),
                "fresh": fresh,
                "ttl_hours": TTL[category].total_seconds() / 3600
            }
        else:
            status[category] = {"fresh": False, "saved_at": None}
    return status


def invalidate(category=None):
    """Force invalidate one or all cache entries."""
    if category:
        cache = _load_cache()
        cache.pop(category, None)
        _save_cache(cache)
        logger.info(f"Cache INVALIDATED [{category}]")
    else:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        logger.info("Cache CLEARED (all)")
