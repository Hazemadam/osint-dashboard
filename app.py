import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# ==========================================
# 1. INITIAL SETUP & DEFAULTS (The "Safety Net")
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# We define these globally so they ALWAYS exist
fbi_status = "Checking..." 
final_df = pd.DataFrame()
poi_df = pd.DataFrame()

# Securely grab keys
try:
    FBI_KEY = st.secrets["FBI_KEY"]
    SERP_KEY = st.secrets["SERP_KEY"]
except Exception as e:
    st.error("🔑 Secrets missing! Add FBI_KEY and SERP_KEY to Streamlit Settings.")
    st.stop()

# ==========================================
# 2. FBI CONNECTION LOGIC
# ==========================================
@st.cache_data(ttl=300)
def get_fbi_status(api_key):
    # Using the most reliable "byStateAbbreviation" endpoint
    url = f"https://api.usa.gov/crime/fbi/sapi/api/agencies/byStateAbbreviation/VA?api_key={api_key}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # The FBI returns a dictionary; the agencies are usually in a 'data' list or the root
            count = len(data) if isinstance(data, list) else "Connected"
            return f"Online ({count} Agencies)"
        return f"Offline (Status: {r.status_code})"
    except Exception as e:
        return f"Offline (Connection Error)"

# Assign the variable immediately
fbi_status = get_fbi_status(FBI_KEY)

# ==========================================
# 3. DATA LOADING
# ==========================================
@st.cache_data(ttl=3600)
def load_github_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base_url = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"
    try:
        poi = pd.read_parquet(f"{base_url}nova_data.parquet")
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        return poi
    except:
        return pd.DataFrame()

poi_df = load_github_data()

# ==========================================
# 4. SIDEBAR & UI
# ==========================================
st.sidebar.title("🛡️ Intelligence Control")

# Sanity check for the key (first 4 chars)
st.sidebar.info(f"Key detected: {FBI_KEY[:4]}****")

if "Online" in fbi_status:
    st.sidebar.success(f"✅ FBI API: {fbi_status}")
else:
    st.sidebar.warning(f"⚠️ FBI API: {fbi_status}")

if not poi_df.empty:
    all_cats = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Categories", all_cats, default=all_cats[:3])
    final_df = poi_df[poi_df['type'].isin(selected_types)]

# ==========================================
# 5. MAIN DASHBOARD
# ==========================================
st.title("🛡️ NOVA Strategic Intelligence")

c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    if not final_df.empty:
        for r in final_df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], 
                radius=7, 
                color='red', 
                fill=True,
                popup=r.name
            ).add_to(m)
    st_folium(m, width=800, height=500, key="nova_map_final")

with c2:
    st.metric("Total Targets", len(final_df))
