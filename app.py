import os
import numpy as np
import pandas as pd
import streamlit as st
import folium
import requests
import time
from folium.plugins import HeatMap
from streamlit_folium import st_folium
from sklearn.cluster import DBSCAN

# =========================================================
# PAGE SETUP
# =========================================================
st.set_page_config(
    page_title="OSINT Intelligence Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Constants
LAT = 38.85
LNG = -77.30
CACHE_FILE = "osint_cache.csv"
# Added mirrors to handle the timeouts seen in your screenshot
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter"
]

st.markdown(
    """
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 2rem; }
        [data-testid="stMetricValue"] { font-size: 1.8rem; }
        .small-note { font-size: 0.86rem; opacity: 0.8; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧠 OSINT Intelligence Dashboard")

# =========================================================
# DATA HELPERS & API CALLS
# =========================================================
REQUIRED_COLS = ["name", "lat", "lng", "type", "city", "street", "source"]

CATEGORY_WEIGHTS = {
    "hotel": 2.0, "motel": 2.2, "bar": 1.3, "nightclub": 1.8,
    "restaurant": 0.8, "cafe": 0.6, "spa": 2.4, "massage": 2.6, "shop": 0.4,
}

def fetch_live_data(lat, lng, radius=5000):
    """
    Fetches real data from Overpass API. 
    Fixes the HTTP 406 error by adding a proper User-Agent.
    """
    # Overpass QL query targeting categories in your CATEGORY_WEIGHTS
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"~"bar|nightclub|restaurant|cafe|spa|massage_institute"](around:{radius},{lat},{lng});
      node["tourism"~"hotel|motel"](around:{radius},{lat},{lng});
      node["shop"~"massage"](around:{radius},{lat},{lng});
    );
    out body;
    """
    
    # Headers are CRITICAL to avoid HTTP 406
    headers = {
        'User-Agent': 'OSINT-Dashboard-App/1.0 (https://your-website-or-contact.com)',
        'Referer': 'https://openstreetmap.org'
    }

    for url in OVERPASS_MIRRORS:
        try:
            with st.spinner(f"Requesting live data from {url.split('/')[2]}..."):
                response = requests.post(url, data={'data': query}, headers=headers, timeout=20)
                if response.status_code == 200:
                    data = response.json()
                    elements = data.get('elements', [])
                    
                    rows = []
                    for e in elements:
                        tags = e.get('tags', {})
                        rows.append({
                            "name": tags.get('name', 'Unknown'),
                            "lat": e.get('lat'),
                            "lng": e.get('lon'),
                            "type": tags.get('amenity') or tags.get('tourism') or tags.get('shop') or 'unknown',
                            "city": tags.get('addr:city', 'Unknown'),
                            "street": tags.get('addr:street', 'Unknown'),
                            "source": f"Live OSM ({url.split('/')[2]})"
                        })
                    return pd.DataFrame(rows)
                elif response.status_code == 429:
                    st.warning(f"Mirror {url} is rate-limited. Trying next...")
                else:
                    st.error(f"Mirror {url} returned status {response.status_code}")
        except Exception as e:
            st.error(f"Connection to {url} failed: {e}")
            continue
            
    return None

def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = np.nan if col in {"lat", "lng"} else "Unknown"

    df["name"] = df["name"].fillna("Unnamed Location").astype(str)
    df["type"] = df["type"].fillna("unknown").astype(str).str.lower()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
    return df.dropna(subset=["lat", "lng"]).reset_index(drop=True)

def load_initial_data(uploaded_file, trigger_live=False) -> tuple[pd.DataFrame, str]:
    # 1. Manual Upload
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            return normalize_df(df), "uploaded CSV"
        except: pass

    # 2. Live Data Request (The Fix)
    if trigger_live:
        live_df = fetch_live_data(LAT, LNG)
        if live_df is not None and not live_df.empty:
            df = normalize_df(live_df)
            df.to_csv(CACHE_FILE, index=False)
            return df, "Live Overpass Data"

    # 3. Local Cache
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE)
            return normalize_df(df), "local cached dataset"
        except: pass

    # 4. Fallback
    return normalize_df(generate_demo_data()), "synthetic demo dataset"

def generate_demo_data(n: int = 120) -> pd.DataFrame:
    # (Existing demo function remains as emergency fallback)
    rng = np.random.default_rng(42)
    centers = [(LAT+0.02, LNG+0.01, ["hotel", "bar"]), (LAT-0.01, LNG-0.01, ["spa", "hotel"])]
    rows = []
    for i in range(n):
        c_lat, c_lng, kinds = centers[i % len(centers)]
        rows.append({
            "name": f"Demo {i}", "lat": c_lat + rng.normal(0, 0.005), 
            "lng": c_lng + rng.normal(0, 0.005), "type": rng.choice(kinds),
            "city": "Demo City", "street": "Demo St", "source": "Synthetic"
        })
    return pd.DataFrame(rows)

# ... (Insert build_cluster_labels, local_neighbor_counts, compute_risk_model, summarize_hotspots here)
# [Keeping your original logic for clustering and risk scoring below]

def build_cluster_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if len(df) < 3:
        df["cluster"] = -1
        return df
    coords = df[["lat", "lng"]].to_numpy()
    db = DBSCAN(eps=0.012, min_samples=3).fit(coords)
    df["cluster"] = db.labels_
    return df

def local_neighbor_counts(df: pd.DataFrame, radius: float = 0.015) -> list[int]:
    counts = []
    for row in df.itertuples():
        nearby = ((df["lat"] - row.lat).abs() < radius) & ((df["lng"] - row.lng).abs() < radius)
        counts.append(int(nearby.sum()))
    return counts

def compute_risk_model(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df = build_cluster_labels(df)
    local_counts = local_neighbor_counts(df)
    baseline_count = float(np.median(local_counts)) if local_counts else 0.0

    risks, signals, confidence = [], [], []
    for idx, row in df.iterrows():
        t = str(row["type"]).lower()
        base = CATEGORY_WEIGHTS.get(t, 0.3)
        nearby_mask = ((df["lat"] - row["lat"]).abs() < 0.015) & ((df["lng"] - row["lng"]).abs() < 0.015)
        nearby_types = set(df.loc[nearby_mask, "type"].str.lower())
        
        score = base + min(local_counts[idx]/10, 3.0)
        bits = []
        if {"hotel", "motel"} & nearby_types and {"bar", "nightclub"} & nearby_types:
            score += 2.0; bits.append("hotel+nightlife")
        
        risks.append(float(score))
        signals.append(", ".join(bits) if bits else "none")
        confidence.append(round(min(1.0, 0.35 + 0.1 * local_counts[idx]), 2))

    df["risk"], df["confidence"], df["signals"] = risks, confidence, signals
    df["topic"] = df["type"].apply(lambda x: "Lodging" if x in ["hotel", "motel"] else "Other")
    df["neighbor_count"] = local_counts
    return df

def summarize_hotspots(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return pd.DataFrame()
    clustered = df[df["cluster"] != -1].copy()
    res = []
    for cid, gp in clustered.groupby("cluster"):
        res.append({"cluster": cid, "count": len(gp), "avg_risk": round(gp["risk"].mean(), 2), 
                    "top_type": gp["type"].mode()[0], "lat": gp["lat"].mean(), "lng": gp["lng"].mean()})
    return pd.DataFrame(res).sort_values("avg_risk", ascending=False)

# =========================================================
# MAIN INTERFACE
# =========================================================
st.sidebar.header("🎛️ Controls")
trigger_live = st.sidebar.button("🌐 Fetch Live Data (Overpass API)")
uploaded = st.sidebar.file_uploader("Upload CSV", type=["csv"])

df_raw, data_source = load_initial_data(uploaded, trigger_live=trigger_live)
df = compute_risk_model(df_raw)

# ... (The rest of your filtering, metrics, and Tabs logic goes here)
# [Keep your existing Tab code to render the Folium map and charts]

# Quick metrics
c1, c2, c3 = st.columns(3)
c1.metric("Total Points", len(df))
c2.metric("Data Source", data_source)
c3.metric("Avg Risk", f"{df['risk'].mean():.2f}" if not df.empty else 0)

tab1, tab2 = st.tabs(["Map", "Data"])
with tab1:
    m = folium.Map(location=[LAT, LNG], zoom_start=12)
    heat_data = [[r.lat, r.lng, r.risk] for r in df.itertuples()]
    HeatMap(heat_data).add_to(m)
    st_folium(m, width=900, height=500)

with tab2:
    st.dataframe(df)
