import pandas as pd
import requests
from census import Census
from us import states

# --- CONFIGURATION ---
CENSUS_API_KEY = "e0c2b4346b6025d078a88f07a724f4038018707d"
c = Census(CENSUS_API_KEY)

# Northern Virginia Counties FIPS Codes
NOVA_COUNTIES = {
    "059": "Fairfax",
    "107": "Loudoun",
    "013": "Arlington",
    "510": "Alexandria"
}

def fetch_census_vulnerability():
    print("Fetching Census Vulnerability Data...")
    all_tracts = []
    
    for county_fips in NOVA_COUNTIES.keys():
        # B19013_001E: Median Household Income
        # B25044_003E: Tenure by Vehicles (Renter, No Vehicle)
        # B25003_003E: Total Renter Occupied Units
        data = c.acs5.state_county_tract(
            ('NAME', 'B19013_001E', 'B25044_003E', 'B25003_003E'),
            states.VA.fips,
            county_fips,
            Census.ALL
        )
        all_tracts.extend(data)
    
    census_df = pd.DataFrame(all_tracts)
    census_df.columns = ['Name', 'Median_Income', 'No_Vehicle_Renters', 'Renters_Total', 'state', 'county', 'tract']
    
    # Clean data: Replace negative values (Census "No Data" flags) with 0
    census_df['Median_Income'] = census_df['Median_Income'].apply(lambda x: x if x > 0 else 50000)
    
    # Calculate a simple Vulnerability Score (0 to 10)
    # Lower income + higher no-vehicle percentage = higher score
    max_inc = census_df['Median_Income'].max()
    census_df['vulnerability_score'] = (1 - (census_df['Median_Income'] / max_inc)) * 5
    census_df['vulnerability_score'] += (census_df['No_Vehicle_Renters'] / census_df['Renters_Total'].replace(0,1)) * 5
    
    return census_df

def fetch_osm_data():
    # Your existing OSM scraper logic
    query = """
    [out:json][timeout:60];
    (
      nwr["tourism"~"hotel|motel"](38.6,-77.6,39.1,-77.0);
      nwr["amenity"~"bar|nightclub|cafe|restaurant|spa"](38.6,-77.6,39.1,-77.0);
      nwr["shop"="massage"](38.6,-77.6,39.1,-77.0);
    );
    out center;
    """
    headers = {'User-Agent': 'NOVA_Vulnerability_Project', 'Accept': 'application/json'}
    url = "https://overpass-api.de/api/interpreter"
    
    r = requests.post(url, data=query, headers=headers, timeout=50)
    data = r.json()
    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        rows.append({
            "name": tags.get("name", "Unnamed"),
            "lat": el.get("lat") or el.get("center", {}).get("lat"),
            "lng": el.get("lon") or el.get("center", {}).get("lon"),
            "type": tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown"
        })
    return pd.DataFrame(rows)

def update_repo_data():
    # 1. Get POIs
    poi_df = fetch_osm_data()
    
    # 2. Get Census Data
    census_df = fetch_census_vulnerability()
    
    # 3. Save both to one Parquet file (using different sheets/tables logic or separate files)
    # For simplicity, we will save them as two separate files in your repo
    poi_df.to_parquet("nova_data.parquet")
    census_df.to_parquet("vulnerability_data.parquet")
    print("Both data files updated successfully!")

if __name__ == "__main__":
    update_repo_data()
