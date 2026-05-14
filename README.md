# Car Bargain Finder

This project collects used car listings from arabam.com, trains baseline price prediction models, and uses the predictions to surface listings that may be underpriced.

The current goal is not to produce a production-grade valuation model yet. It is to build a reliable baseline, understand the signal in the scraped data, and record model results before adding more feature engineering.

## Project Structure

- `collect_urls.py` collects listing URLs by brand and writes them to `urls.txt`.
- `scrape_listings.py` visits the listing pages and writes structured listing data to `cars.csv`.
- `model.ipynb` cleans the data, trains baseline models, tunes selected models, and ranks potential bargains.
- `cars.csv` is the scraped dataset used by the notebook.
- `failed_urls.txt` and `unavailable_urls.txt` record URLs that could not be scraped successfully.

## Dataset

The dataset currently contains `42,267` CSV rows including the header. The main scraped fields are:

- Listing metadata: `url`, `seller_type`, `trade_in`
- Vehicle identity: `brand`, `series`, `model`, `year`
- Vehicle attributes: `mileage`, `transmission`, `fuel`, `body`, `color`, `engine`, `hp`, `drive`, `condition`
- Damage and condition signals: `heavy_damage`, `paint_changed`
- Target: `price`

The current model uses a small feature set:

- `brand_series_encoded`
- `year`
- `mileage`
- `heavy_damage_encoded`
X- `hp`

`hp` is parsed from strings like `"110 hp"` and bucketed ranges like `"101 - 125 HP"` (arabam.com's fixed 25-hp buckets). Exact values are converted directly; range values are replaced with the midpoint. Open-ended ranges and placeholder values such as `"50 HP'ye kadar"`, `"601 HP ve üzeri"`, and `"-"` cannot be parsed cleanly and become `NaN`, which is then dropped.

## Cleaning and Modeling Workflow

The notebook currently:

1. Drops rows with missing values in any of the model columns.
2. Drops duplicate listings by `url`.
3. Converts `price` from Turkish lira strings to numeric values.
4. Filters unrealistic prices.
5. Converts `mileage` from kilometer strings to numeric values.
6. Filters unrealistic years and mileages.
7. Fills missing `heavy_damage` values with `Belirtilmemiş`.
8. Parses `hp` strings into a single numeric value, taking the midpoint for bucketed ranges, and drops rows that cannot be parsed.
9. Combines `brand` and `series` into `brand_series`.
10. Label-encodes `brand_series` and `heavy_damage`.
11. Splits the data into train and test sets with `random_state=42`.
12. Trains baseline Decision Tree, XGBoost, and LightGBM regressors.
13. Runs `RandomizedSearchCV` over LightGBM hyperparameters.
14. Predicts expected prices and ranks listings by predicted discount.

## Current Test Results

The current metric is mean absolute error (MAE) in Turkish lira on the held-out test set. Lower is better.

| Model | Test MAE |
| --- | ---: |
| Decision Tree baseline | 169,626 TL |
| XGBoost baseline | 145,543 TL |
| Tuned XGBoost test result | 143,284 TL |
| LightGBM baseline | 135,583 TL |
| Tuned LightGBM test result | 134,991 TL |

LightGBM is currently the strongest model. The tuned LightGBM search selected:

```python
{
    "learning_rate": 0.0133,
    "max_depth": -1,
    "min_child_samples": 10,
    "n_estimators": 1453,
    "num_leaves": 67,
}
```

The LightGBM `RandomizedSearchCV` reported a best cross-validation MAE of `132,615 TL`, but the held-out test MAE is `134,991 TL`. For model-to-model comparison, the test-set result is the fairer number.

## Current Interpretation

The tuned LightGBM MAE of roughly `135k TL` is a useful first result given the model only uses brand/series, year, mileage, heavy damage status, and horsepower. Switching from grid search to `RandomizedSearchCV` and adding `hp` together moved the test MAE only a few hundred TL, which reinforces that the current feature set matters more than additional hyperparameter search at this stage. Notably, `min_child_samples` landed on the lower bound of the search range, which would normally suggest widening it, but the gains from further tuning are likely small.

However, this error is still large enough that the bargain finder should be treated as a candidate generator, not as proof that a listing is underpriced. A high predicted discount may indicate a real bargain, but it can also come from missing features, rare models, unusual mileage, data quality issues, or model uncertainty.

The current results suggest that more value may come from careful feature engineering than from heavier hyperparameter tuning. `paint_changed` is a likely next feature candidate, but it needs careful parsing because the strings mix changed panels, painted panels, local paint, fully original, fully painted, and unspecified values.

## Possible Next Steps

- Parse `paint_changed` into structured features such as changed panel count, painted panel count, local painted panel count, fully original, fully painted, and unspecified.
- Add confidence or uncertainty heuristics to the bargain ranking so very risky predictions are easier to spot.
- Consider adding selected categorical fields only when they are likely to add stable signal.

## Running the Project

Create and activate a Python environment, then install the main dependencies:

```bash
pip install pandas scikit-learn xgboost lightgbm jupyter beautifulsoup4 httpx playwright
playwright install chromium
```

Collect listing URLs:

```bash
python collect_urls.py
```

Scrape listing details:

```bash
python scrape_listings.py
```

Open the notebook:

```bash
jupyter notebook model.ipynb
```
