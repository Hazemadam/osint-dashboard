import streamlit as st
import pandas as pd
import requests
import time

# ================================
# SAFE + LIGHT OVERPASS QUERY
# ================================
def fetch_data():
    query = """
    [out:json][timeout:15];
    (
      nwr["tourism"="hotel"](38.6,-77.6,39.1,-77.0);
      nwr["tourism"="motel"](38.6,-77.6,39.1,-77.0);
      nwr["amenity"="bar"](38.6,-77.6,39.1,-77.0);
      nwr["amenity"="restaurant"](38.6,-77.6,39.1,-77.0);
    );
    out center;
    """

    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.ru/api/interpreter",
    ]

    errors = []

    for url in endpoints:
        try:
            st.write(f"🔄 Trying: {url}")

            r = requests.post(
                url,
                data=query,
                headers={"Content-Type": "text/plain"},
                timeout=(5, 15)  # hard fail if slow
            )

            if r.status_code != 200:
                errors.append(f"{url} → HTTP {r.status_code}")
                continue

            data = r.json()
            elements = data.get("elements", [])

            if not elements:
                errors.append(f"{url} → empty response")
                continue

            rows = []

            for el in elements:
                tags = el.get("tags", {})

                lat = el.get("lat") or el.get("center", {}).get("lat")
                lng = el.get("lon") or el.get("center", {}).get("lon")

                if lat is None or lng is None:
                    continue

                rows.append({
                    "name": tags.get("name", "Unnamed"),
                    "lat": lat,
                    "lng": lng,
                    "type": (
                        tags.get("amenity")
                        or tags.get("tourism")
                        or tags.get("shop")
                        or "unknown"
                    ),
                    "city": tags.get("addr:city", "Unknown"),
                    "street": tags.get("addr:street", "Unknown"),
                })

            df = pd.DataFrame(rows)

            if len(df) > 0:
                return df, f"✅ Live data loaded from {url}"

            errors.append(f"{url} → parsed but empty dataset")

        except requests.exceptions.Timeout:
            errors.append(f"{url} → TIMEOUT (too slow)")
        except Exception as e:
            errors.append(f"{url} → {str(e)}")

        time.sleep(1)  # small pause between retries

    # ================================
    # SAFE FALLBACK (NO HANG)
    # ================================
    st.warning("⚠️ Live data unavailable. Using fallback.")
    st.text("\n".join(errors))

    return pd.DataFrame(), "fallback"


# ================================
# NON-BLOCKING LOADING UI
# ================================
placeholder = st.empty()

placeholder.info("🔄 Loading OSINT dataset...")

df_raw, status = fetch_data()

placeholder.success(f"Data status: {status}")
