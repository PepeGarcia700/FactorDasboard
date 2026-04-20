# S&P 500 Factor Dashboard

Dashboard local de factor investing — univers S&P 500 dynamique (Wikipedia), comparaison Long vs S&P 500 et Short vs -S&P 500.

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Ouvre `config.py` et mets ta clé FMP :
```python
FMP_API_KEY = "ta_clé_ici"
```

## Lancement

```bash
python app.py
```

Puis ouvre `index.html` dans ton navigateur.

---

## Facteurs

### Top (Long Side) — comparés au S&P 500
| Facteur | Source | Latence |
|---|---|---|
| 2Y Beta | Yahoo Finance | J-1 |
| Price vs 52W Low | Yahoo Finance | J-1 |
| Momentum 12M-1M | Yahoo Finance | J-1 |
| 3M EPS Revision % | FMP | ~J-1 |
| 6M Target Price Change % | FMP | ~J-1 |
| 2Y Fwd EPS Growth | FMP | ~J-1 |
| R&D to Sales | Yahoo Finance | Trimestriel |

### Bottom (Short Side) — comparés au -S&P 500
| Facteur | Source | Latence |
|---|---|---|
| Low Volatility | Yahoo Finance | J-1 |
| Net Debt/EBITDA | Yahoo Finance | Trimestriel |
| SI Days to Cover | Yahoo Finance | 2x/mois |
| Accrual to Assets | Yahoo Finance | Trimestriel |

---

## Architecture

- `tickers.py` — récupère dynamiquement les 500 constituants depuis Wikipedia (cache 24h)
- `factors.py` — tous les calculs de facteurs + spreads L/S + comparaison benchmark
- `app.py` — serveur Flask (localhost:5000)
- `index.html` — dashboard frontend

## Temps de refresh

Le refresh complet prend **10 à 20 minutes** pour 500 titres (données fondamentales par titre). Les facteurs prix uniquement (Beta, Momentum, etc.) sont calculés en 2-3 minutes.
