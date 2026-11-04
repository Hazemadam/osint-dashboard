"""Refresh the dashboard's data files.

Writes three files to the repo root:
  nova_data.parquet           named venues from OpenStreetMap, each tagged with
                              its census tract, county and tract vulnerability
  vulnerability_data.parquet  ACS 5-year indicators per Northern Virginia tract
  tracts.geojson              simplified tract outlines for the map overlay

Runs nightly in .github/workflows/scrape.yml. Set CENSUS_API_KEY in the
environment (GitHub Secrets); the Census API also works without a key at low volume.
"""
import os
import sys
import time

import geopandas as gpd
import pandas as pd
import requests

CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
ACS_YEAR = int(os.environ.get("ACS_YEAR", "2023"))
STATE_FIPS = "51"  # Virginia

# Northern Virginia counties and independent cities (FIPS -> name)
NOVA_COUNTIES = {
    "013": "Arlington",
    "059": "Fairfax",
    "107": "Loudoun",
    "153": "Prince William",
    "510": "Alexandria",
    "600": "Fairfax City",
    "610": "Falls Church",
    "683": "Manassas",
    "685": "Manassas Park",
}

# ACS variables
ACS_VARS = {
    "B19013_001E": "median_income",       # median household income
    "B25044_009E": "renters_total",       # renter-occupied households
    "B25044_010E": "renters_no_vehicle",  # renter-occupied, no vehicle
    "B17001_001E": "poverty_universe",    # population with poverty status determined
    "B17001_002E": "below_poverty",       # income below poverty level
}

TRACT_SHAPES_URL = (
    f"https://www2.census.gov/geo/tiger/GENZ{ACS_YEAR}/shp/cb_{ACS_YEAR}_{STATE_FIPS}_tract_500k.zip"
)

BBOX = "38.6,-77.6,39.1,-77.0"  # south, west, north, east
OVERPASS_QUERY = f"""
[out:json][timeout:120];
(
  nwr["tourism"~"^(hotel|motel|guest_house)$"]["name"]({BBOX});
  nwr["amenity"~"^(bar|nightclub|cafe|restaurant|spa)$"]["name"]({BBOX});
  nwr["shop"="massage"]["name"]({BBOX});
  nwr["leisure"="spa"]["name"]({BBOX});
);
out center;
"""
# Public Overpass servers are often overloaded; try each with retries.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "nova-osint-dashboard (github.com/Hazemadam/osint-dashboard)"


def fetch_census_vulnerability() -> pd.DataFrame:
    """ACS indicators for every NoVA tract, plus a 0-1 vulnerability index."""
    print("Fetching Census ACS data...")
    frames = []
    for fips in NOVA_COUNTIES:
        params = {
            "get": ",".join(["NAME", *ACS_VARS]),
            "for": "tract:*",
            "in": f"state:{STATE_FIPS} county:{fips}",
        }
        if CENSUS_API_KEY:
            params["key"] = CENSUS_API_KEY
        r = requests.get(
            f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5", params=params, timeout=60
        )
        r.raise_for_status()
        rows = r.json()
        frames.append(pd.DataFrame(rows[1:], columns=rows[0]))

    df = pd.concat(frames, ignore_index=True).rename(columns=ACS_VARS)
    for col in ACS_VARS.values():
        df[col] = pd.to_numeric(df[col], errors="coerce")
        # The Census API marks missing estimates with large negative sentinels.
        df.loc[df[col] < 0, col] = pd.NA

    df["geoid"] = df["state"] + df["county"] + df["tract"]
    df["county_name"] = df["county"].map(NOVA_COUNTIES)

    df["no_vehicle_renter_share"] = df["renters_no_vehicle"] / df["renters_total"].where(
        df["renters_total"] > 0
    )
    df["poverty_rate"] = df["below_poverty"] / df["poverty_universe"].where(
        df["poverty_universe"] > 0
    )

    # Percentile ranks keep any single outlier tract from dominating and put
    # every indicator on the same 0-1 scale. Lower income = more vulnerable.
    parts = pd.DataFrame(
        {
            "income": 1 - df["median_income"].rank(pct=True),
            "no_vehicle": df["no_vehicle_renter_share"].rank(pct=True),
            "poverty": df["poverty_rate"].rank(pct=True),
        }
    )
    # Tracts missing an indicator get the median for it rather than being dropped.
    parts = parts.fillna(0.5)
    df["vulnerability"] = parts.mean(axis=1).round(3)

    print(f"  {len(df)} tracts")
    return df[
        [
            "geoid", "NAME", "county", "county_name", "median_income",
            "renters_total", "renters_no_vehicle", "no_vehicle_renter_share",
            "poverty_rate", "vulnerability",
        ]
    ]


def fetch_tract_shapes() -> gpd.GeoDataFrame:
    print("Fetching tract boundaries...")
    gdf = gpd.read_file(TRACT_SHAPES_URL)
    gdf = gdf[gdf["COUNTYFP"].isin(NOVA_COUNTIES.keys())]
    gdf = gdf[["GEOID", "geometry"]].rename(columns={"GEOID": "geoid"}).to_crs(4326)
    print(f"  {len(gdf)} tract shapes")
    return gdf


def fetch_osm_data() -> pd.DataFrame:
    print("Fetching OpenStreetMap venues...")
    elements, last_error = None, None
    for attempt in range(3):
        for url in OVERPASS_URLS:
            try:
                r = requests.post(
                    url,
                    data={"data": OVERPASS_QUERY},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=180,
                )
                r.raise_for_status()
                elements = r.json().get("elements", [])
                print(f"  got {len(elements)} elements from {url}")
                break
            except (requests.RequestException, ValueError) as e:
                last_error = e
                print(f"  {url} failed: {e}")
        if elements is not None:
            break
        time.sleep(30 * (attempt + 1))
    if elements is None:
        raise RuntimeError(f"All Overpass servers failed: {last_error}")

    rows = []
    for el in elements:
        tags = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lng is None or not tags.get("name"):
            continue
        rows.append(
            {
                "name": tags["name"].strip(),
                "lat": lat,
                "lng": lng,
                # Prefer the tag the query matched on; a restaurant may also carry shop=bakery.
                "type": tags.get("tourism")
                or ("massage" if tags.get("shop") == "massage" else None)
                or tags.get("amenity")
                or tags.get("leisure"),
                "address": " ".join(
                    filter(None, [tags.get("addr:housenumber"), tags.get("addr:street"),
                                  tags.get("addr:city")])
                ),
                "osm_id": f"{el['type']}/{el['id']}",
            }
        )
    df = pd.DataFrame(rows)
    # The same venue is often mapped as both a node and a building outline.
    df = df.assign(_lat=df["lat"].round(4), _lng=df["lng"].round(4))
    df = df.drop_duplicates(["name", "_lat", "_lng"]).drop(columns=["_lat", "_lng"])
    print(f"  {len(df)} named venues")
    return df.reset_index(drop=True)


def attach_tracts(poi: pd.DataFrame, tracts: gpd.GeoDataFrame, census: pd.DataFrame) -> pd.DataFrame:
    """Tag each venue with the tract it sits in; drop venues outside NoVA."""
    pts = gpd.GeoDataFrame(poi, geometry=gpd.points_from_xy(poi["lng"], poi["lat"]), crs=4326)
    joined = gpd.sjoin(pts, tracts, how="inner", predicate="within").drop(
        columns=["geometry", "index_right"]
    )
    joined = joined.merge(census[["geoid", "county_name", "vulnerability"]], on="geoid", how="left")
    print(f"  {len(joined)} venues inside Northern Virginia tracts")
    return pd.DataFrame(joined).reset_index(drop=True)


def write_tract_geojson(tracts: gpd.GeoDataFrame, census: pd.DataFrame, path: str) -> None:
    out = tracts.merge(
        census[["geoid", "NAME", "county_name", "vulnerability", "median_income", "poverty_rate"]],
        on="geoid",
        how="left",
    )
    out["geometry"] = out.geometry.simplify(0.0005, preserve_topology=True)
    out.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=5)


def update_repo_data() -> None:
    census = fetch_census_vulnerability()
    tracts = fetch_tract_shapes()
    poi = attach_tracts(fetch_osm_data(), tracts, census)

    if poi.empty or census.empty:
        sys.exit("Refusing to overwrite data files with empty results.")

    poi.to_parquet("nova_data.parquet", index=False)
    census.to_parquet("vulnerability_data.parquet", index=False)
    write_tract_geojson(tracts, census, "tracts.geojson")
    print("Data files updated.")


if __name__ == "__main__":
    update_repo_data()
