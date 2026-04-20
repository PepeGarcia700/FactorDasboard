import yfinance as yf
import pandas as pd
import numpy as np
import requests
import logging
from datetime import datetime, timedelta
from config import FMP_API_KEY

logger = logging.getLogger(__name__)
BENCHMARK = "^GSPC"


# ─────────────────────────────────────────────
# PRICE DATA
# ─────────────────────────────────────────────

def fetch_prices(tickers, period="2y"):
    """Download adjusted close prices for all tickers + benchmark in batches."""
    all_tickers = list(set(tickers + [BENCHMARK]))
    batch_size = 100
    frames = []

    for i in range(0, len(all_tickers), batch_size):
        batch = all_tickers[i:i + batch_size]
        try:
            data = yf.download(batch, period=period, auto_adjust=True,
                               progress=False, threads=True)
            if "Close" in data.columns:
                frames.append(data["Close"])
            elif isinstance(data.columns, pd.MultiIndex):
                frames.append(data["Close"])
            else:
                frames.append(data)
        except Exception as e:
            logger.warning(f"Batch {i//batch_size} failed: {e}")

    if not frames:
        return None

    prices = pd.concat(frames, axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]
    return prices


# ─────────────────────────────────────────────
# PRICE-BASED FACTORS
# ─────────────────────────────────────────────

def compute_beta_2y(prices, tickers):
    results = {}
    if BENCHMARK not in prices.columns:
        return results
    bench_ret = prices[BENCHMARK].pct_change().dropna()
    bench_var = bench_ret.var()
    if bench_var == 0:
        return results

    for t in tickers:
        if t not in prices.columns:
            continue
        try:
            stock_ret = prices[t].pct_change().dropna()
            aligned = pd.concat([stock_ret, bench_ret], axis=1).dropna()
            if len(aligned) < 50:
                continue
            cov = aligned.cov().iloc[0, 1]
            var = aligned.iloc[:, 1].var()
            results[t] = cov / var if var != 0 else np.nan
        except:
            pass
    return results


def compute_price_vs_52w_low(prices, tickers):
    results = {}
    window = prices.tail(252)
    for t in tickers:
        if t not in prices.columns:
            continue
        try:
            low = window[t].min()
            current = prices[t].dropna().iloc[-1]
            if low and low != 0:
                results[t] = (current - low) / low
        except:
            pass
    return results


def compute_momentum(prices, tickers):
    """12M return excluding last month (Fama-French)"""
    results = {}
    for t in tickers:
        if t not in prices.columns:
            continue
        try:
            series = prices[t].dropna()
            if len(series) < 252:
                continue
            p_1m = series.iloc[-21]
            p_12m = series.iloc[-252]
            if p_12m != 0:
                results[t] = (p_1m - p_12m) / p_12m
        except:
            pass
    return results


def compute_low_volatility(prices, tickers):
    """Annualized realized volatility over 252 days"""
    results = {}
    for t in tickers:
        if t not in prices.columns:
            continue
        try:
            ret = prices[t].pct_change().dropna().tail(252)
            if len(ret) < 50:
                continue
            results[t] = float(ret.std() * np.sqrt(252))
        except:
            pass
    return results


# ─────────────────────────────────────────────
# FUNDAMENTAL FACTORS (yfinance)
# ─────────────────────────────────────────────

def compute_fundamentals(tickers):
    nd_ebitda = {}
    accruals = {}
    short_interest = {}
    rd_sales = {}

    for t in tickers:
        try:
            info = yf.Ticker(t).info

            # Net Debt / EBITDA
            debt = info.get("totalDebt") or 0
            cash = info.get("totalCash") or 0
            ebitda = info.get("ebitda")
            if ebitda and ebitda != 0:
                nd_ebitda[t] = (debt - cash) / ebitda

            # SI Days to Cover
            si = info.get("sharesShort")
            avg_vol = info.get("averageVolume")
            if si and avg_vol and avg_vol != 0:
                short_interest[t] = si / avg_vol

            # R&D to Sales
            rd = info.get("researchAndDevelopment") or 0
            rev = info.get("totalRevenue")
            if rev and rev != 0:
                rd_sales[t] = rd / rev

            # Accruals to Assets: (net income - op CF) / total assets
            ni = info.get("netIncomeToCommon") or 0
            op_cf = info.get("operatingCashflow") or 0
            assets = info.get("totalAssets")
            if assets and assets != 0:
                accruals[t] = (ni - op_cf) / assets

        except Exception as e:
            logger.debug(f"Fundamental error {t}: {e}")

    return nd_ebitda, accruals, short_interest, rd_sales


# ─────────────────────────────────────────────
# FMP ANALYST FACTORS
# ─────────────────────────────────────────────

def compute_fmp_factors(tickers):
    eps_revision_3m = {}
    target_price_6m = {}
    fwd_eps_growth_2y = {}

    base = "https://financialmodelingprep.com/api/v3"
    date_3m = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    date_6m = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    date_2y = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

    for t in tickers:
        # EPS estimates
        try:
            r = requests.get(f"{base}/analyst-estimates/{t}?apikey={FMP_API_KEY}&limit=12", timeout=8)
            data = r.json()
            if isinstance(data, list) and len(data) >= 1:
                current_eps = data[0].get("estimatedEpsAvg")
                eps_3m = next((e.get("estimatedEpsAvg") for e in data if e.get("date","") <= date_3m), None)
                eps_2y = next((e.get("estimatedEpsAvg") for e in data if e.get("date","") <= date_2y), None)

                if current_eps and eps_3m and eps_3m != 0:
                    eps_revision_3m[t] = (current_eps - eps_3m) / abs(eps_3m)
                if current_eps and eps_2y and eps_2y != 0:
                    fwd_eps_growth_2y[t] = (current_eps - eps_2y) / abs(eps_2y)
        except Exception as e:
            logger.debug(f"FMP EPS error {t}: {e}")

        # Price targets
        try:
            r = requests.get(f"{base}/price-target/{t}?apikey={FMP_API_KEY}&limit=20", timeout=8)
            data = r.json()
            if isinstance(data, list) and len(data) >= 1:
                current_tp = data[0].get("priceTarget")
                tp_6m = next((e.get("priceTarget") for e in data
                              if e.get("publishedDate","")[:10] <= date_6m), None)
                if current_tp and tp_6m and tp_6m != 0:
                    target_price_6m[t] = (current_tp - tp_6m) / abs(tp_6m)
        except Exception as e:
            logger.debug(f"FMP target error {t}: {e}")

    return eps_revision_3m, target_price_6m, fwd_eps_growth_2y


# ─────────────────────────────────────────────
# L/S SPREAD + PERFORMANCE
# ─────────────────────────────────────────────

def quintile_split(scores, higher_is_better=True):
    """Return top quintile (long) and bottom quintile (short) tickers."""
    valid = [(k, v) for k, v in scores.items() if v is not None and not np.isnan(v)]
    if len(valid) < 10:
        return [], []
    valid.sort(key=lambda x: x[1], reverse=higher_is_better)
    n = max(1, len(valid) // 5)
    long_tickers = [k for k, _ in valid[:n]]
    short_tickers = [k for k, _ in valid[-n:]]
    return long_tickers, short_tickers


def compute_performance_series(prices, long_tickers, short_tickers, days=504):
    """
    Compute cumulative return series for:
    - Long quintile
    - Short quintile
    - L/S spread (Long - Short)
    - S&P 500 benchmark
    - -S&P 500 (for short comparison)
    """
    price_slice = prices.tail(days)
    bench = price_slice[BENCHMARK] if BENCHMARK in price_slice.columns else None

    def cum_ret(tickers_list):
        valid = [t for t in tickers_list if t in price_slice.columns]
        if not valid:
            return pd.Series(dtype=float)
        ret = price_slice[valid].pct_change()
        eq_ret = ret.mean(axis=1)
        return (1 + eq_ret).cumprod() - 1

    long_cum = cum_ret(long_tickers)
    short_cum = cum_ret(short_tickers)

    if len(long_cum) > 0 and len(short_cum) > 0:
        ls_ret = long_cum - short_cum
    else:
        ls_ret = pd.Series(dtype=float)

    bench_cum = (1 + bench.pct_change()).cumprod() - 1 if bench is not None else pd.Series(dtype=float)
    neg_bench_cum = -bench_cum
    # Short position = inverse of Q1 return (as if actually shorting)
    short_position = -short_cum

    def to_list(series):
        return [{"date": d.strftime("%Y-%m-%d"), "value": round(float(v) * 100, 3)}
                for d, v in series.dropna().items()]

    return {
        "long": to_list(long_cum),
        "short": to_list(short_position),
        "ls_spread": to_list(ls_ret),
        "benchmark": to_list(bench_cum),
        "neg_benchmark": to_list(neg_bench_cum)
    }


def compute_period_returns(prices, tickers_list, days):
    """Compute return over N days for a list of tickers."""
    valid = [t for t in tickers_list if t in prices.columns]
    if not valid or len(prices) < days:
        return None
    slice_ = prices[valid].tail(days)
    start = slice_.iloc[0]
    end = slice_.iloc[-1]
    ret = ((end - start) / start).mean()
    return round(float(ret) * 100, 2)


def compute_benchmark_returns(prices):
    if BENCHMARK not in prices.columns:
        return {}
    bench = prices[BENCHMARK].dropna()
    n = len(bench)

    def pct(days):
        if n < days:
            return None
        return round(float((bench.iloc[-1] / bench.iloc[-days] - 1) * 100), 2)

    # YTD
    current_year = bench.index[-1].year
    ytd_prices = bench[bench.index.year == current_year]
    ytd = round(float((bench.iloc[-1] / ytd_prices.iloc[0] - 1) * 100), 2) if len(ytd_prices) > 1 else None

    return {
        "1d": pct(2),
        "ytd": ytd,
        "1y": pct(252),
        "3y": pct(756)
    }


def build_factor_result(name, style, category, description, source, latency,
                        scores, higher_is_better, prices, days=504):
    long_t, short_t = quintile_split(scores, higher_is_better)
    n_valid = len([v for v in scores.values() if v is not None and not np.isnan(v)])

    perf = compute_performance_series(prices, long_t, short_t, days)

    # Period returns for long side vs benchmark
    bench_rets = compute_benchmark_returns(prices)
    long_1d = compute_period_returns(prices, long_t, 2)
    long_ytd_prices = prices[long_t] if long_t else None
    long_1y = compute_period_returns(prices, long_t, 252)
    long_3y = compute_period_returns(prices, long_t, 756)

    short_1y_raw = compute_period_returns(prices, short_t, 252)
    short_3y_raw = compute_period_returns(prices, short_t, 756)
    # Negate: short position profit = -return of the shorted basket
    short_1y = round(-short_1y_raw, 2) if short_1y_raw is not None else None
    short_3y = round(-short_3y_raw, 2) if short_3y_raw is not None else None

    def alpha(long_val, bench_val):
        if long_val is None or bench_val is None:
            return None
        return round(long_val - bench_val, 2)

    def short_alpha(short_val, bench_val):
        if short_val is None or bench_val is None:
            return None
        # Short alpha = (-bench) - short_return
        return round(-bench_val - short_val, 2)

    clean_scores = {k: (round(float(v), 4) if v is not None and not np.isnan(v) else None)
                    for k, v in scores.items()}

    return {
        "name": name,
        "style": style,
        "category": category,
        "description": description,
        "source": source,
        "latency": latency,
        "n_valid": n_valid,
        "higher_is_better": higher_is_better,
        "long_tickers": long_t[:20],
        "short_tickers": short_t[:20],
        "scores": clean_scores,
        "performance": perf,
        "returns": {
            "long": {"1y": long_1y, "3y": long_3y},
            "short": {"1y": short_1y, "3y": short_3y},
            "benchmark": bench_rets,
            "alpha_long": {
                "1y": alpha(long_1y, bench_rets.get("1y")),
                "3y": alpha(long_3y, bench_rets.get("3y"))
            },
            "alpha_short": {
                "1y": short_alpha(short_1y, bench_rets.get("1y")),
                "3y": short_alpha(short_3y, bench_rets.get("3y"))
            }
        }
    }
