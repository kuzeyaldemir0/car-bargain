# Car Bargain Finder

This project collects used car listings from arabam.com, trains baseline price prediction models, and uses the predictions to surface listings that may be underpriced.

The current goal is not to produce a production-grade valuation model yet. It is to build a reliable baseline, understand the signal in the scraped data, and record model results before adding more feature engineering.

## Project Structure

- `collect_urls.py` collects listing URLs by brand and writes them to `urls.txt`.
- `scrape_listings.py` visits the listing pages and writes structured listing data to `cars.csv`.
- `model.ipynb` cleans the data, trains baseline models, tunes selected models, and ranks potential bargains.
- `cars.csv` is the scraped dataset used by the notebook. It is not tracked in this repository; recreate it locally by running the scrapers.
- `failed_urls.txt` and `unavailable_urls.txt` record URLs that could not be scraped successfully.

The scrapers respect rate limits and do not bypass authentication or paywalls. The scraped dataset is intentionally not redistributed in this repository; anyone wanting to reproduce the project can regenerate it by running the included scripts against the public listing pages.

## Dataset

The dataset currently contains `42,267` CSV rows including the header. The main scraped fields are:

- Listing metadata: `url`, `seller_type`, `trade_in`
- Vehicle identity: `brand`, `series`, `model`, `year`
- Vehicle attributes: `mileage`, `transmission`, `fuel`, `body`, `color`, `engine`, `hp`, `drive`, `condition`
- Damage and condition signals: `heavy_damage`, `paint_changed`
- Target: `price`

The current model uses the following feature set:

- `brand_series_encoded`
- `year`
- `mileage`
- `heavy_damage_encoded`
- `hp`
- `degisen` (number of replaced panels)
- `boyali` (number of painted panels)
- `lokal_boyali` (number of locally painted panels)
- `body_encoded`
- `fuel_encoded`
- `transmission_encoded`
- `drive_encoded`

`hp` is parsed from strings like `"110 hp"` and bucketed ranges like `"101 - 125 HP"` (arabam.com's fixed 25-hp buckets). Exact values are converted directly; range values are replaced with the midpoint. Open-ended ranges and placeholder values such as `"50 HP'ye kadar"`, `"601 HP ve üzeri"`, and `"-"` cannot be parsed cleanly and become `NaN`, which is then dropped.

`paint_changed` is parsed into the three numeric count columns above. Strings such as `"1 değişen, 2 boyalı"` or `"3 boyalı, 1 lokal boyalı"` are split with regex and the leading numbers extracted into the matching column. `"Tamamı orjinal"` (fully original) maps to `(0, 0, 0)`. `"Tamamı boyalı"` and `"Tamamı lokal boyalı"` are treated as 12 painted or 12 locally painted panels respectively, since 12 panels is roughly a full body and matches values seen elsewhere in the data. Rows with `NaN` or `"Belirtilmemiş"` (unspecified) are dropped because they carry no signal.

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
9. Parses `paint_changed` into `degisen`, `boyali`, and `lokal_boyali` count columns and drops rows with no information.
10. Combines `brand` and `series` into `brand_series`.
11. Label-encodes `brand_series` and `heavy_damage`.
12. Replaces `"-"` placeholder values with `NaN` in `body` and `drive`, drops rows missing any of `body`, `fuel`, `transmission`, or `drive`, then label-encodes all four.
13. Splits the data into train and test sets with `random_state=42`.
14. Trains baseline Decision Tree, XGBoost, and LightGBM regressors.
15. Runs `RandomizedSearchCV` over LightGBM hyperparameters.
16. Predicts expected prices and ranks listings by predicted discount in both absolute Turkish lira and as a percentage of the predicted price.

## Current Test Results

The current metric is mean absolute error (MAE) in Turkish lira on the held-out test set. Lower is better. The results below are with the full twelve-feature set described above.

| Model | Test MAE |
| --- | ---: |
| LightGBM baseline (4 features) | 135,583 TL |
| LightGBM baseline (8 features, adds `hp` and paint counts) | 93,334 TL |
| LightGBM baseline (12 features, adds `body`, `fuel`, `transmission`, `drive`) | 86,696 TL |

LightGBM has been the strongest model at every stage of feature growth. The progression above tells the story of the project: each round of careful feature engineering moved the metric far more than hyperparameter tuning ever did. A `RandomizedSearchCV` over LightGBM on the original four-feature set moved the MAE by only a few hundred TL, while parsing `hp`, `paint_changed`, and adding the four small categoricals together cut MAE roughly in half. The tuning has not been re-run on the current twelve-feature set.

## Current Interpretation

A LightGBM MAE of roughly `87k TL` is a meaningful improvement over the earlier `135k TL` result and reinforces a pattern that has held throughout the project: feature engineering moves the metric far more than hyperparameter tuning. Both tuning rounds on the smaller feature set produced sub-percent improvements, while parsing `hp`, parsing `paint_changed`, and adding the four small categoricals together cut MAE by roughly a third.

This error is still large enough that the bargain finder should be treated as a candidate generator, not as proof that a listing is underpriced. A high predicted discount may indicate a real bargain, but it can also come from missing features, rare models, unusual mileage, data quality issues, or model uncertainty. The bargain finder now ranks listings by `discount_pct` (the predicted discount as a fraction of the predicted price) rather than by absolute Turkish lira, which prevents expensive luxury cars and EVs from dominating the top of the list purely because they have larger absolute prediction errors.

## Limitations

A few characteristics of the model and the data are worth being explicit about, because they shape how the bargain finder output should be read.

- **Cheap-car bias from percentage ranking.** Mean absolute error is roughly constant in absolute Turkish lira, so the same prediction error becomes a much larger percentage on a `200k TL` car than on a `5M TL` car. As a result, the listings sorted to the top by `discount_pct` are systematically biased toward inexpensive cars. The fix is to either filter by a minimum predicted price, or to read both `discount` and `discount_pct` together rather than relying on the percentage alone.
- **Sparse data on rare and old cars.** The model performs noticeably worse on `brand_series` values with few training rows and on cars older than roughly the year 2000. In both cases, the model tends to over-predict the price, which can make a normal listing look like a deep bargain when it is actually just an unfamiliar segment for the model.
- **No trim awareness.** Within a `brand_series`, the model cannot distinguish between trim levels (for example a base versus a top-trim engine variant). This is the single largest remaining source of unmodeled variance in the dataset.
- **Sold listings redirect rather than 404.** Arabam.com redirects expired or sold listings to a category page rather than returning a not-found error. A bargain link that opens to a category or search page almost always means the car has already been sold.

## Future Work

- Parse the free-text `model` column for trim level. Within a `brand_series`, trim often determines a large fraction of price (for example a base versus a top-trim engine variant), so this is the largest remaining unmodeled source of variance.
- Add prediction intervals via quantile regression (training one LightGBM with `objective="quantile"` and `alpha=0.1` and another with `alpha=0.9`) so the bargain finder can prefer listings where the model is confident, rather than listings where the discount is large but the model is uncertain.
- Re-run `RandomizedSearchCV` on the current twelve-feature set to confirm the baseline LightGBM result cannot be improved much by tuning at this stage.

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
