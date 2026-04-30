import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# ==========================================
# 1. INITIAL SETUP & DIAGNOSTICS
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# Initialize variables
fbi_intel = None 
final_df = pd.DataFrame()

# 🔍 DIAGNOSTIC CHECK
st.sidebar.title("🛠️ System Diagnostics")
if "FBI_KEY" in st.secrets:
    key_found = st.secrets["FBI_KEY"]
    # Show only the first 4 characters to verify it's the right key without leaking it
    st.sidebar.info(f"Secret detected: {key_found[:4]}****")
else:
    st.sidebar.error("❌ NO SECRET FOUND: Check Streamlit Settings")
    st.stop()

FBI_KEY = st.secrets["FBI_KEY"]

# ==========================================
# 2. THE FBI HANDSHAKE (RE-ENGINEERED)
# ==========================================
@st.cache_data(ttl=60) # Short cache for testing
def get_fbi_status():
    # Use the simplest possible endpoint to test connectivity
    url = f"https://api.usa.gov/crime/fbi/sapi/api/participation/states/VA?api_key={FBI_KEY}"
    
    try:
        # Increase timeout to 15 seconds in case gov servers are slow
        r = requests.get(url, timeout=15)
        
        if r.status_code == 200:
            data = r.json().get('data', [])
            return f"Online (Year: {data[-1].get('year')})" if data else "Online (No Data)"
        elif r.status_code == 403:
            return "Error 403: Forbidden (Key Rejected)"
        elif r.status_code == 429:
            return "Error 429: Rate Limited (Too many tries)"
        else:
            return f"Offline (Status: {r.status_code})"
    except Exception as e:
        return f"Offline (Connection Error: {str(e)[:20]})"

# Run the check
fbi_status = get_fbi_status()

# ==========================================
# 3. SIDEBAR & DATA LOADING
# ==========================================
if "Online" in fbi_status:
    st.sidebar.success(f"✅ {fbi_status}")
else:
    st.sidebar.warning(f"⚠️ {fbi_status}")

@st.cache_data(ttl=3600)
def load_github_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base_url = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"
    try:
        poi = pd.read_parquet(f"{base_url}nova_data.parquet")
        census = pd.read_parquet(f"{base_url}vulnerability_data.parquet")
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        poi['type'] = poi['type'].astype(str).str.lower().str.strip()
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except Exception as e:
        st.error(f"⚠️ Data Load Failure: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_github_data()

# Logic to build the map (Keeping it simple for the fix)
if not poi_df.empty:
    all_cats = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Categories", all_cats, default=all_cats[:3])
    final_df = poi_df[poi_df['type'].isin(selected_types)]

# ==========================================
# 4. VISUALS
# ==========================================
st.title("🛡️ NOVA Intelligence")
c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    if not final_df.empty:
        for r in final_df.itertuples():
            folium.CircleMarker(location=[r.lat, r.lng], radius=6, color='red', fill=True).add_to(m)
    st_folium(m, width=800, height=500, key="fixed_map")

with c2:
    st.metric("Total Points", len(final_df))
