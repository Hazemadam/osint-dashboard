import pandas as pd
import requests
import time

def fetch_data():
    # The Overpass Query for NOVA
    query = """
    [out:json][timeout:60];
    (
      nwr["tourism"~"hotel|motel"](38.6,-77.6,39.1,-77.0);
      nwr["amenity"~"bar|nightclub|cafe|restaurant|spa"](38.6,-77.6,39.1,-77.0);
      nwr["shop"="massage"](38.6,-77.6,39.1,-77.0);
    );
    out center;
    """
    
    # MANDATORY HEADERS: Prevents the 406 Error
    headers = {
        'User-Agent': 'NOVA_OSINT_Research_Project_v1',
        'Accept': 'application/json',
        'Referer': 'https://github.com/Hazemadam/osint-dashboard'
    }

    # Reliable 2026 Overpass Instances
    urls = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.fr/api/interpreter"
    ]

    for url in urls:
        try:
            print(f"Connecting to {url}...")
            # We send the data as 'data=query' but include the new headers
            r = requests.post(url, data=query, headers=headers, timeout=50)
            
            if r.status_code == 406:
                print(f"Server {url} rejected request with 406. Checking headers...")
                continue
                
            r.raise_for_status()
            data = r.json()

            rows = []
            elements = data.get("elements", [])
            print(f"Received {len(elements)} elements from {url}")

            for el in elements:
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
                return df, "Success"

        except Exception as e:
            print(f"Error with {url}: {e}")
            continue

    return pd.DataFrame(), "All APIs failed"

def update_repo_data():
    print("Robot starting NOVA OSINT scrape...")
    try:
        df, status = fetch_data()
        
        if not df.empty:
            # Save to the cloud file Streamlit expects
            df.to_parquet("nova_data.parquet")
            print(f"Successfully saved {len(df)} locations to nova_data.parquet")
        else:
            print(f"Scrape completed but no data found: {status}")
            raise Exception("No data collected.")
            
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        raise e

if __name__ == "__main__":
    update_repo_data()
