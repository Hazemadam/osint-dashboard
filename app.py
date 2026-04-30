import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# ==========================================
# 1. SETUP & DEFAULTS
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# We set the default status to something else so we know if it's working
fbi_status = "Attempting Connection..." 

try:
    FBI_KEY = st.secrets["FBI_KEY"]
    SERP_KEY = st.secrets["SERP_KEY"]
except Exception:
    st.error("🔑 Secrets missing in Streamlit Cloud Settings!")
    st.stop()

# ==========================================
# 2. THE FBI CHECK (NO CACHE - FAST TIMEOUT)
# ==========================================
def check_fbi_api(api_key):
    # We use a very simple endpoint with a strict 3-second timeout
    url = f"https://api.usa.gov/crime/fbi/sapi/api/participation/national?api_key={api_key}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            return "Online"
        else:
            return f"Offline (Status {response.status_code})"
    except Exception:
        return "Offline (Timeout)"

# Run it immediately without caching
fbi_status = check_fbi_api(FBI_KEY)

# ==========================================
# 3. DATA LOADING
# ==========================================
@st.cache_data(ttl=3600)
def load_github_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    url = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet"
    try:
        df = pd.read_parquet(url)
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        return df
    except:
        return pd.DataFrame()

poi_df = load_github_data()

# ==========================================
# 4. SIDEBAR & UI
# ==========================================
st.sidebar.title("🛡️ Intelligence Control")
st.sidebar.info(f"Key: {FBI_KEY[:4]}****")

# This will now display either "Online" or "Offline", NOT "Initializing"
if "Online" in fbi_status:
    st.sidebar.success(f"✅ FBI API: {fbi_status}")
else:
    st.sidebar.warning(f"⚠️ FBI API: {fbi_status}")

# ==========================================
# 5. MAP DISPLAY
# ==========================================
st.title("🛡️ NOVA Strategic Intelligence")

if not poi_df.empty:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in poi_df.head(50).itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng], 
            radius=6, 
            color='red', 
            fill=True,
            popup=getattr(r, 'name', 'Target')
        ).add_to(m)
    st_folium(m, width=900, height=500)
else:
    st.error("Could not load map data from GitHub.")
