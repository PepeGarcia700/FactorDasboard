from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import logging
import time
from datetime import datetime

import webbrowser
import threading
import cache as cache_mgr
from tickers import fetch_sp500_tickers, get_cache_info
from factors import (
    fetch_prices, compute_benchmark_returns,
    compute_beta_2y, compute_price_vs_52w_low, compute_momentum, compute_low_volatility,
    compute_fundamentals, compute_fmp_factors,
    build_factor_result
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ── MODE TEST ──────────────────────────────────────────
# Passe à False pour utiliser les 500 tickers complets
TEST_MODE = False
TEST_TICKERS = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","JPM","V","XOM"]
# ──────────────────────────────────────────────────────


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/tickers")
def get_tickers():
    tickers = fetch_sp500_tickers()
    info = get_cache_info()
    return jsonify({"tickers": tickers, "info": info})


@app.route("/api/factors")
def get_factors():
    t0 = time.time()
    logger.info("=== Starting factor computation ===")

    # 1. Get dynamic ticker list
    if TEST_MODE:
        tickers = TEST_TICKERS
        ticker_info = {"source": "TEST MODE (10 tickers)", "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        logger.info("TEST MODE — using 10 tickers only")
    else:
        tickers = fetch_sp500_tickers()
        ticker_info = get_cache_info()
    logger.info(f"Universe: {len(tickers)} tickers from {ticker_info['source']}")

    # 2. Prices — use cache if fresh (< 20h)
    cached_prices_data = cache_mgr.get("prices")
    if cached_prices_data:
        logger.info("Cache HIT: prices — skipping download")
        import pandas as pd
        prices = pd.DataFrame(cached_prices_data["prices"])
        prices.index = pd.to_datetime(prices.index)
        available_tickers = cached_prices_data["available_tickers"]
        beta      = cached_prices_data["beta"]
        price_52w = cached_prices_data["price_52w"]
        momentum  = cached_prices_data["momentum"]
        low_vol   = cached_prices_data["low_vol"]
        bench_rets = cached_prices_data["bench_rets"]
    else:
        logger.info("Fetching price data...")
        prices = fetch_prices(tickers, period="2y")
        if prices is None:
            return jsonify({"error": "Failed to fetch price data"}), 500
        available_tickers = [t for t in tickers if t in prices.columns]
        logger.info(f"Price data: {len(available_tickers)}/{len(tickers)} tickers available")

        logger.info("Computing price-based factors...")
        beta      = compute_beta_2y(prices, available_tickers)
        price_52w = compute_price_vs_52w_low(prices, available_tickers)
        momentum  = compute_momentum(prices, available_tickers)
        low_vol   = compute_low_volatility(prices, available_tickers)
        bench_rets = compute_benchmark_returns(prices)

        cache_mgr.set("prices", {
            "prices": prices.to_dict(),
            "available_tickers": available_tickers,
            "beta": beta,
            "price_52w": price_52w,
            "momentum": momentum,
            "low_vol": low_vol,
            "bench_rets": bench_rets
        })

    # 3. Fundamentals — use cache if fresh (< 7 days)
    cached_fund = cache_mgr.get("fundamentals")
    if cached_fund:
        logger.info("Cache HIT: fundamentals — skipping download")
        nd_ebitda     = cached_fund["nd_ebitda"]
        accruals      = cached_fund["accruals"]
        short_interest = cached_fund["short_interest"]
        rd_sales      = cached_fund["rd_sales"]
    else:
        logger.info("Fetching fundamental data (this takes a few minutes)...")
        nd_ebitda, accruals, short_interest, rd_sales = compute_fundamentals(available_tickers)
        cache_mgr.set("fundamentals", {
            "nd_ebitda": nd_ebitda,
            "accruals": accruals,
            "short_interest": short_interest,
            "rd_sales": rd_sales
        })

    # 4. FMP analyst data — use cache if fresh (< 20h)
    cached_fmp = cache_mgr.get("fmp")
    if cached_fmp:
        logger.info("Cache HIT: fmp — skipping download")
        eps_revision  = cached_fmp["eps_revision"]
        target_price  = cached_fmp["target_price"]
        fwd_eps_growth = cached_fmp["fwd_eps_growth"]
    else:
        logger.info("Fetching FMP analyst data...")
        eps_revision, target_price, fwd_eps_growth = compute_fmp_factors(available_tickers)
        cache_mgr.set("fmp", {
            "eps_revision": eps_revision,
            "target_price": target_price,
            "fwd_eps_growth": fwd_eps_growth
        })

    # 5. Build all factors
    logger.info("Building factor results...")
    factors = {
        "beta_2y": build_factor_result(
            "2Y Beta", "Volatility", "top",
            "Covariance titre/S&P 500 sur 2 ans de données journalières",
            "Yahoo Finance", "J-1", beta, True, prices
        ),
        "price_vs_52w_low": build_factor_result(
            "Price vs 52W Low", "Technicals", "top",
            "(Prix actuel - Plus bas 52 semaines) / Plus bas 52 semaines",
            "Yahoo Finance", "J-1", price_52w, True, prices
        ),
        "momentum": build_factor_result(
            "Momentum", "Momentum", "top",
            "Retour total 12M excluant le dernier mois (convention Fama-French)",
            "Yahoo Finance", "J-1", momentum, True, prices
        ),
        "eps_revision_3m": build_factor_result(
            "3M EPS Revision %", "Revisions", "top",
            "Variation % du consensus EPS forward sur 3 mois",
            "FMP", "~J-1", eps_revision, True, prices
        ),
        "target_price_6m": build_factor_result(
            "6M Target Price Change %", "Revisions", "top",
            "Variation % du prix cible moyen des analystes sur 6 mois",
            "FMP", "~J-1", target_price, True, prices
        ),
        "fwd_eps_growth_2y": build_factor_result(
            "2Y Fwd EPS Growth", "Growth", "top",
            "Croissance % du consensus EPS forward sur 2 ans",
            "FMP", "~J-1", fwd_eps_growth, True, prices
        ),
        "rd_to_sales": build_factor_result(
            "R&D to Sales", "Investment", "top",
            "Dépenses R&D / Chiffre d'affaires (dernier trimestre publié)",
            "Yahoo Finance", "Trimestriel", rd_sales, True, prices
        ),
        "low_volatility": build_factor_result(
            "Low Volatility", "Volatility", "bottom",
            "Volatilité annualisée 252 jours — faible vol = score élevé",
            "Yahoo Finance", "J-1", low_vol, False, prices
        ),
        "net_debt_ebitda": build_factor_result(
            "Net Debt/EBITDA", "Leverage", "bottom",
            "(Dette totale - Cash) / EBITDA LTM",
            "Yahoo Finance", "Trimestriel", nd_ebitda, False, prices
        ),
        "short_interest": build_factor_result(
            "SI Days to Cover", "Short Interest", "bottom",
            "Short Interest / Volume moyen journalier",
            "Yahoo Finance", "2x/mois", short_interest, False, prices
        ),
        "accruals": build_factor_result(
            "Accrual to Assets", "Accruals", "bottom",
            "(Résultat net - Cash-flow opérationnel) / Total Actifs",
            "Yahoo Finance", "Trimestriel", accruals, False, prices
        ),
    }

    elapsed = round(time.time() - t0, 1)
    logger.info(f"=== Done in {elapsed}s ===")

    return jsonify({
        "factors": factors,
        "benchmark": bench_rets,
        "universe": {
            "requested": len(tickers),
            "with_price_data": len(available_tickers),
            "source": ticker_info["source"],
            "tickers_fetched_at": ticker_info["fetched_at"]
        },
        "cache_status": cache_mgr.get_cache_status(),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": elapsed
    })


@app.route("/api/cache/clear")
def clear_cache():
    cache_mgr.invalidate()
    return jsonify({"status": "cache cleared"})


@app.route("/api/cache/clear/<category>")
def clear_cache_category(category):
    cache_mgr.invalidate(category)
    return jsonify({"status": f"cache cleared for {category}"})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


if __name__ == "__main__":
    def open_browser():
        import time
        time.sleep(1)
        webbrowser.open("http://localhost:5000")
    threading.Thread(target=open_browser).start()
    app.run(debug=False, port=5000)
    #test
    print("test")
