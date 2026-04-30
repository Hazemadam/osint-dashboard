import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# ==========================================
# 1. INITIAL SETUP & GLOBAL VARIABLES
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# Initialize these so the app never hits a "NameError"
fbi_intel = None 
final_df = pd.DataFrame()
poi_df = pd.DataFrame()
census_df = pd.DataFrame()

# Securely grab keys from Streamlit Secrets
try:
    FBI_KEY = st.secrets["FBI_KEY"]
    SERP_KEY = st.secrets["SERP_KEY"]
except Exception as e:
    st.error("🔑 Secrets missing! Add FBI_KEY and SERP_KEY to Streamlit Cloud Settings.")
    st.stop()

# ==========================================
# 2. DATA LOADING FUNCTIONS
# ==========================================
@st.cache_data(ttl=3600)
def load_github_data():
    """Loads Parquet files from your public GitHub repository."""
    USER, REPO = "Hazemadam", "osint-dashboard"
    base_url = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"
    
    try:
        poi = pd.read_parquet(f"{base_url}nova_data.parquet")
        census = pd.read_parquet(f"{base_url}vulnerability_data.parquet")
        
        # Standardize POI Data
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        poi['type'] = poi['type'].astype(str).str.lower().str.strip()
        
        # Standardize Census Data
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except Exception as e:
        st.error(f"⚠️ Data Load Failure: {e}")
        return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=3600)
def get_fbi_status():
    """Connects to the FBI Crime Data API with browser-imitation headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OSINT-Investigator-Tools"
    }
    url = f"https://api.usa.gov/crime/fbi/sapi/api/participation/states/VA?api_key={FBI_KEY}"
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json().get('data', [])
            return data[-1] if data else "Connected"
        else:
            return f"Status {r.status_code}"
    except Exception as e:
        return None

# Execute Loaders
poi_df, census_df = load_github_data()
fbi_intel = get_fbi_status()

# ==========================================
# 3. SIDEBAR & INTELLIGENCE LOGIC
# ==========================================
st.sidebar.title("🛡️ Intelligence Control")

# Display FBI API Status
if fbi_intel:
    if isinstance(fbi_intel, dict):
        st.sidebar.success(f"✅ FBI API Connected ({fbi_intel.get('year')})")
    else:
        st.sidebar.success(f"✅ FBI API: {fbi_intel}")
else:
    st.sidebar.warning("❌ FBI API Offline")

# Process Risk Scores if data loaded successfully
if not poi_df.empty:
    # Build Risk Dictionary from Census Data
    county_risk = census_df.groupby('county')['vulnerability_score'].mean().to_dict()
    
    # Risk Weights based on business type
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6, 'bar': 4}
    
    scores, colors, levels = [], [], []
    for _, row in poi_df.iterrows():
        base = weights.get(row['type'], 1)
        # Match county data
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        # Calculate Final Score
        fs = base + (vuln * 10)
        scores.append(fs)
        
        # Assign Tiers
        if fs >= 17: 
            colors.append('red'); levels.append('HIGH')
        elif fs >= 11: 
            colors.append('orange'); levels.append('MEDIUM')
        else: 
            colors.append('blue'); levels.append('LOW')
    
    poi_df['raw_score'], poi_df['color'], poi_df['level'] = scores, colors, levels

    # Filter UI
    all_cats = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Categories", all_cats, default=all_cats[:3])
    selected_risks = st.sidebar.multiselect("Risk Tiers", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    # Create Filtered View
    final_df = poi_df[(poi_df['type'].isin(selected_types)) & (poi_df['level'].isin(selected_risks))]

# ==========================================
# 4. DASHBOARD VISUALS
# ==========================================
st.title("🛡️ NOVA Strategic Intelligence")
st.caption("Monitoring Northern Virginia infrastructure and vulnerability indicators.")

col1, col2 = st.columns([3, 1])

with col1:
    # Center map on Northern Virginia
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    
    if not final_df.empty:
        for r in final_df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=8,
                color='white',
                weight=0.5,
                fill=True,
                fill_color=r.color,
                fill_opacity=0.8,
                popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Tier: {r.level}<br>Score: {round(r.raw_score, 1)}"
            ).add_to(m)
    
    st_folium(m, width=900, height=550, key="main_nova_map")

with col2:
    st.metric("Pins Tracked", len(final_df))
    
    if not final_df.empty:
        st.subheader("⚠️ Priority Watchlist")
        watchlist = final_df.sort_values('raw_score', ascending=False).head(10)
        for _, row in watchlist.iterrows():
            with st.expander(f"{row['level']} - {row['name']}"):
                st.write(f"**Category:** {row['type']}")
                st.write(f"**Risk Score:** {round(row['raw_score'], 1)}")
                st.button("Open OSINT Dossier", key=f"btn_{row.name}")
