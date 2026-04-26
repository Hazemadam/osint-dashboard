import pandas as pd
import requests
import time

def fetch_data():
    # The instructions for the OpenStreetMap scraper
    query = """
    [out:json][timeout:30];
    (
      nwr["tourism"~"hotel|motel"](38.6,-77.6,39.1,-77.0);
      nwr["amenity"~"bar|nightclub|cafe|restaurant|spa"](38.6,-77.6,39.1,-77.0);
      nwr["shop"="massage"](38.6,-77.6,39.1,-77.0);
    );
    out center;
    """

    urls = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    for url in urls:
        try:
            r = requests.post(url, data=query, timeout=25)
            r.raise_for_status()
            data = r.json()

            rows = []
            for el in data.get("elements", []):
                tags = el.get("tags", {})
                lat = el.get("lat") or el.get("center", {}).get("lat")
                lng = el.get("lon") or el.get("center", {}).get("lon")

                if lat is None or lng is None:
                    continue

                category = tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown"

                rows.append({
                    "name": tags.get("name", "Unnamed"),
                    "lat": lat,
                    "lng": lng,
                    "type": category,
                    "city": tags.get("addr:city", "Unknown"),
                    "street": tags.get("addr:street", "Unknown"),
                    "source": "OpenStreetMap",
                })

            df = pd.DataFrame(rows)
            if not df.empty:
                return df, f"Success from {url}"

        except Exception as e:
            print(f"Failed to fetch from {url}: {e}")
            continue

    return pd.DataFrame(), "All APIs failed"

def update_repo_data():
    print("Starting data fetch...")
    df, status = fetch_data()
    
    if not df.empty:
        # This creates the file the robot will save back to GitHub
        df.to_parquet("nova_data.parquet")
        print(f"Data updated successfully: {len(df)} points found.")
    else:
        print(f"Update failed: {status}")
        # We raise an error so the GitHub Action knows it failed
        raise Exception("No data collected.")

if __name__ == "__main__":
    update_repo_data()
