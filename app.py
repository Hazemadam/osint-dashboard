
# -------------------------------
# 1. Write Streamlit app
# -------------------------------
app_code = """
import streamlit as st
import pandas as pd
import numpy as np
import requests
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
from sklearn.cluster import DBSCAN

st.set_page_config(page_title="OSINT Dashboard", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🗺️ OSINT Hotspot Dashboard (Fairfax County)")

# -------------------------------
# DATA (Overpass with fallback)
# -------------------------------
def fetch_data():
    query = '''
    [out:json];
    (
      node["tourism"="hotel"](38.6,-77.6,39.1,-77.0);
      node["tourism"="motel"](38.6,-77.6,39.1,-77.0);
      node["amenity"="spa"](38.6,-77.6,39.1,-77.0);
      node["shop"="massage"](38.6,-77.6,39.1,-77.0);
      node["amenity"="bar"](38.6,-77.6,39.1,-77.0);
      node["amenity"="nightclub"](38.6,-77.6,39.1,-77.0);
    );
    out;
    '''

    url = "https://overpass-api.de/api/interpreter"

    try:
        r = requests.post(url, data={"data": query}, timeout=30)
        data = r.json()
    except:
        return pd.DataFrame()

    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        rows.append({
            "name": tags.get("name", "unknown"),
            "lat": el.get("lat"),
            "lng": el.get("lon"),
            "type": list(tags.values())[0] if tags else "unknown"
        })

    return pd.DataFrame(rows)

df = fetch_data()

# -------------------------------
# fallback if API fails
# -------------------------------
if df.empty:
    st.warning("Using fallback dataset")
    df = pd.DataFrame({
        "name": [f"synthetic_{i}" for i in range(40)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 40),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 40),
        "type": np.random.choice(["hotel","spa","bar","motel"], 40)
    })

# -------------------------------
# scoring
# -------------------------------
def score(t):
    t = str(t).lower()
    if "hotel" in t or "motel" in t:
        return 2
    if "spa" in t or "massage" in t:
        return 3
    if "bar" in t or "nightclub" in t:
        return 1.5
    return 0

df["risk"] = df["type"].apply(score)

# -------------------------------
# filters
# -------------------------------
st.sidebar.header("Filters")
types = df["type"].unique().tolist()
selected = st.sidebar.multiselect("Types", types, default=types)
min_risk = st.sidebar.slider("Min Risk", 0.0, 5.0, 0.0)

df = df[(df["type"].isin(selected)) & (df["risk"] >= min_risk)]

st.write("Points:", len(df))

# -------------------------------
# clustering
# -------------------------------
if len(df) > 0:
    coords = df[["lat","lng"]].to_numpy()

    db = DBSCAN(
        eps=0.6/6371,
        min_samples=2,
        metric="haversine"
    ).fit(np.radians(coords))

    df["cluster"] = db.labels_

# -------------------------------
# map
# -------------------------------
m = folium.Map(location=[LAT, LNG], zoom_start=11)

if len(df) > 0:
    heat = [[r.lat, r.lng, r.risk] for r in df.itertuples()]
    HeatMap(heat, radius=18).add_to(m)

    for r in df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=4,
            popup=f"{r.name} | {r.type} | {r.risk}",
            fill=True
        ).add_to(m)

st_folium(m, width=1200, height=700)
"""

with open("app.py", "w") as f:
    f.write(app_code)

# -------------------------------
# 2. Run Streamlit
# -------------------------------
def run_streamlit():
    os.system("streamlit run app.py --server.port 8501 --server.address 0.0.0.0")

threading.Thread(target=run_streamlit).start()

# give server time to start
time.sleep(5)

# -------------------------------
# 3. Start LocalTunnel
# -------------------------------
print("Starting tunnel...")
