# Demand forecasting and anomaly detection: method and honest evaluation

Both engines are plain Python (`backend/app/ai/forecasting`, `backend/app/ai/anomaly`) with no
database access, so they can be unit-tested and evaluated on their own. The worker runs them
on a schedule: forecasts nightly, the anomaly scan every 3 hours. Staff can also start either
one from the app. Everything runs on a laptop CPU in seconds.

## 1. Demand forecasting

### Data

The inputs are daily units sold per product, using store-local days (Africa/Nairobi) and up to
365 days of history, with zero-filled days. This is demand **as recorded**: on a day the shelf
was empty, the lost sales are invisible. That is a known limit of every sales-based forecast,
and it is discussed in the results below.

### Models compared for every product

| Model | Why it is there |
|---|---|
| Naive (yesterday repeated) | Baseline |
| Seasonal naive (same weekday last week) | Baseline. Other models are judged against it (MASE/RMSSE < 1 = better). |
| 28-day moving average | Simple and robust |
| Holt-Winters, additive weekly seasonality (statsmodels) | The standard statistical model for weekly retail patterns |
| Croston / SBA | For intermittent demand (slow sellers with many zero days) |
| Gradient boosting, one global model across all products (scikit-learn `HistGradientBoostingRegressor`, Poisson loss) | The machine-learning model. It forecasts each future day *directly* from what is known on the day of the forecast: horizon, weekday, day of month, **month-end payday flag**, Kenyan public holidays (`holidays` package), recent levels, spread, share of zero days, and the same weekday's recent average. |

### Choosing a model: rolling-origin backtest

For each product, the backtest pretends it is a past day *t*, forecasts the next 28 days
using only data before *t*, and scores the result against what actually sold. It does this
for 8 weekly origins. The model with the lowest mean **RMSSE** wins for that product.

Products with under 8 weeks of history only use the simple models and are marked *low
confidence*.

**Why RMSSE and not MASE (a change from the plan).** On products with many zero days,
absolute error is minimised by forecasting zero. In a smoke test, MASE picked "naive" for a
product selling 0.3 a day, which then forecast 1 a day (the last value). A squared-error
measure is minimised by the *average*, which is what stock planning needs. RMSSE is the scaled
squared error used in the M5 forecasting competition. MASE, MAE, RMSE, MAPE and sMAPE are
still all reported.

### Intervals, stock-out date and reorder advice

- **80% interval:** the 10th and 90th percentile of the chosen model's own backtest errors.
  The interval is as wide as the model has actually been wrong, not a theoretical assumption.
- **Stock-out date:** the first day the cumulative forecast exceeds stock on hand.
- **Reorder point:** forecast demand over the supplier lead time, plus safety stock. Safety
  stock is 1.65 × the daily forecast error × √lead time, aiming for a 95% service level.
- **Order now** when stock on hand plus open purchase orders is at or below the reorder point.
  Order up to the maximum stock level; if none is set, cover the lead time plus one review week.
- **Pack sizes** are not modelled yet: quantities are rounded up to whole units.
- **Also computed per product:**
  - demand pattern (Syntetos–Boylan: smooth, erratic, intermittent or lumpy)
  - ABC class by 90-day revenue
  - weekday profile
  - month-end payday effect

## 2. Anomaly detection

### Inputs

Daily figures for every product (units sold, adjusted out and in, number of adjustments,
damaged write-offs, returns) and every member of staff (refunds taken and their value,
number and value of adjustments).

Each figure is compared with that product's or person's **own past 90 days**: the median,
and a robust spread based on the median absolute deviation. The spread is floored so that
moving from 0 to 1 unit never looks extreme. Only the past is used, so each day is judged as
it would have been that night.

### Two detectors

- **Rules.** Each rule is explainable and states its reason in the alert:
  - unexplained stock loss: 4 or more units adjusted out, at least 4 robust z above normal, and worth KES 500 or more
  - 4 or more adjustments on one product in a day
  - damaged write-offs or returns far above normal
  - sales at least 6 robust z and 3 times above normal
  - refunds by one person far above their normal
  - 5 or more adjustments by one person in a day, or adjustment value far above their normal
- **Isolation Forest** (scikit-learn, `contamination` = 1%). It looks at all the z-scores
  together, so it can catch unusual combinations that no single rule describes. Its alert
  names the figures that were furthest from normal.

The two are merged per entity-day; `detector` records RULE, ISOLATION_FOREST or BOTH.

### Severity, wording and review

- **Severity** comes from the value at stake: HIGH at KES 5,000 or more (or KES 2,000+ when
  both detectors agree), MEDIUM at KES 1,000 or more, or when both agree.
- **Grouping:** consecutive days of the same irregularity become one alert covering the
  period.
- **Wording:** alerts are *irregularities to investigate* and never say "theft".
- **Who sees what:**
  - Alerts about a member of staff are visible only to Store Managers and Super Admins.
  - Nobody can review an alert about their own activity.
  - Resolving an alert needs a note.
- **Feedback:** the review outcomes (*issue found* / *no issue*) give the real-world precision
  shown on the Irregularities page.

## 3. Evaluation protocol

All data is **synthetic** (`scripts/demo_history.py`), simulated through the real services:
checkout, goods received, returns, adjustments and write-offs.

- **Demand pattern:** a base rate per product, weekends +25%, month-end payday +35%, Poisson
  noise, and lost sales when out of stock.
- **Everyday noise:** routine one- or two-unit count corrections (about 1 day in 10), the odd
  breakage, and customer returns.
- **Injected irregularities:**
  - shrinkage bursts: 6 to 12 units adjusted out a day for 3 days
  - adjustment bursts: 6 to 9 one-unit corrections in a day
  - damage spikes: 10 to 18 units
  - refund spikes: 6 to 9 refunds by one cashier in a day
- **Ground truth:** the injected irregularities are written to a separate file the detector
  never reads.

To avoid grading on the data used for design decisions, two independent simulated years are
used:

| Set | Seed | Used for |
|---|---|---|
| Tuning | 42 | Developing and checking the engines. One change was made after looking at its results: the Isolation Forest stopped using *units sold*, because 8 of its 11 false alarms were ordinary busy sales days (paydays and the end of December). Sales spikes still have their own rule. |
| **Final test** | **2027** | Run once after all changes. These are the numbers below. |

The forecasting test additionally holds out the **last 28 days**. Fitting, backtesting and
model selection only see the data before them.

Reproduce:

```bash
cd backend
python -m scripts.seed_demo_catalog --history-days 365 --seed 2027   # into an empty database
python -m scripts.evaluate_forecasts --report ../docs/ai/forecast-evaluation.md
python -m scripts.evaluate_anomalies --labels storage/demo/anomaly-ground-truth.json \
    --report ../docs/ai/anomaly-evaluation.md
```

## 4. Results (final test set)

Full generated tables: [forecast-evaluation.md](forecast-evaluation.md) and
[anomaly-evaluation.md](anomaly-evaluation.md).

### Forecasting (10 products, 28 held-out days)

| | MAE (units/day) | MASE | RMSSE |
|---|---|---|---|
| Automatic choice per product | 5.61 | **0.753** | 0.761 |
| Gradient boosting (alone, for every product) | 5.51 | 0.733 | 0.753 |
| Holt-Winters | 5.77 | 0.770 | 0.775 |
| Seasonal naive (baseline) | 6.81 | 0.937 | 0.944 |

- The chosen models were about **25% more accurate than the seasonal-naive baseline**.
  Selecting per product came out marginally behind using gradient boosting everywhere, a
  difference well within the noise of 10 products over 4 weeks.
- **The 80% interval held the actual figure on 72.5% of test days, not 80%.** It is too
  narrow: the errors in this 4-week window were larger than in the backtest windows the
  interval was calibrated on. I did not widen it after seeing this, because that would mean
  tuning on the test set. Wider intervals (for example the 5th to 95th percentile) are a
  simple remedy to verify on the next data.
- **Forecasts were slightly low** (bias −0.44 units/day). Lost sales on out-of-stock days
  (914 in the simulated year) pull recorded demand below true demand.
- **Every demo product has smooth demand**, so the intermittent-demand path (Croston/SBA and
  RMSSE selection on zero-heavy series) is exercised by the unit tests, not by this
  evaluation.
- In the tuning year, MASE was 0.645 and interval coverage 81.8%. The difference from the
  final year shows how much a single 4-week test window varies.

### Anomaly detection (344 scored days: 3,440 product-days and 1,032 staff-days; 27 injected)

| Detector | Precision | Recall | F1 |
|---|---|---|---|
| Rules only | 100% | 100% | 100% |
| Isolation Forest only | 89.5% | 63.0% | 73.9% |
| **Combined** | **93.1%** | **100%** | **96.4%** |

Precision@10 was 100%. The two false alarms were a cashier's 3 refunds in one day, and 3
returns of milk in one day. Both were genuinely unusual for this simulated shop, and a
reviewer would close them as *no issue*.

**How to read these numbers:**

- The rules and the injected irregularities were designed by the same person, and the
  injections are clear-cut (for example 9 one-unit adjustments in a day against a normal
  of zero). **Perfect rule scores here say the rules do what they were written to do; they
  are not evidence of 100% detection in a real shop.**
- Real irregularities are often small and spread out (one unit a day for weeks), and real
  noise is messier. This is exactly where the Isolation Forest's lower recall matters, and
  it is the case this evaluation does not cover.
- In live use, the honest measure is the review outcome. The Irregularities page shows
  *issue found / (issue found + no issue)* once alerts have been reviewed.
