# NOVA Risk Profile Explorer

A Streamlit dashboard that maps Northern Virginia venues and scores how closely each one
fits the location profile seen in FBI human trafficking data.

> **Profile match, not evidence.** Most businesses that fit the profile are legitimate.
> Scores are for prioritizing further research, never on their own grounds for accusations,
> reports or action against a business.

## Score (0–10)

| Part | Points | Source |
|---|---|---|
| Venue type | up to 6 | OpenStreetMap category (lodging, spa and massage highest) |
| Area vulnerability | up to 3 | Census ACS 5-year tract data: median income, renters without a vehicle, poverty rate |
| Statewide trend | up to 1 | FBI Crime Data Explorer, Virginia trafficking offenses |

## Data refresh

`.github/workflows/scrape.yml` runs `update_data.py` nightly (or on demand from the Actions tab)
and commits `nova_data.parquet`, `vulnerability_data.parquet` and `tracts.geojson`.
Set `CENSUS_API_KEY` under **Settings → Secrets and variables → Actions**.

The FBI CSVs are exported by hand from the FBI Crime Data Explorer.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The optional review keyword check needs a SerpAPI key in `.streamlit/secrets.toml`:

```toml
SERP_KEY = "..."
```
