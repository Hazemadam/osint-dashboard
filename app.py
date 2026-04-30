import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# ================================
# 1. INITIAL CONFIG & SECRETS
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# Fetching keys from Streamlit Cloud Secrets (Not hardcoded!)
try:
    FBI_KEY = st.secrets["FBI_KEY"]
    SERP_KEY = st.secrets["SERP_KEY"]
except:
    st.error("🔑 Secrets missing! Add FBI_KEY and SERP_KEY to Streamlit Cloud Settings.")
    st.stop()

@st.cache_data(ttl=3600)
def load_data():
    # Use your Public GitHub links
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

# ================================
# 2. FBI INTELLIGENCE CONNECTION
# ================================
@st.cache_data(ttl=86400)
def get_fbi_status():
    url = f"https://api.usa.gov/crime/fbi/sapi/api/participation/states/VA?api_key={FBI_KEY}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get('data', [])[-1]
        return None
    except:
        return None

poi_df, census_df = load_data()
fbi_intel = get_fbi_status()

# ================================
# 3. SIDEBAR & LOGIC
# ================================
st.sidebar.title("🛡️ Intelligence Control")

if fbi_intel:
    st.sidebar.success(f"✅ FBI API Connected ({fbi_intel.get('year')})")
else:
    st.sidebar.warning("❌ FBI API Offline")

if not poi_df.empty:
    # Build Risk Scores
    county_risk = census_df.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6, 'bar': 4}
    
    scores, colors, levels = [], [], []
    for _, row in poi_df.iterrows():
        base = weights.get(row['type'], 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        fs = base + (vuln * 10)
        scores.append(fs)
        if fs >= 17: colors.append('red'); levels.append('HIGH')
        elif fs >= 11: colors.append('orange'); levels.append('MEDIUM')
        else: colors.append('blue'); levels.append('LOW')
    
    poi_df['raw_score'], poi_df['color'], poi_df['level'] = scores, colors, levels

    # Filter UI
    all_cats = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Categories", all_cats, default=all_cats[:3])
    selected_risks = st.sidebar.multiselect("Risk Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    final_df = poi_df[(poi_df['type'].isin(selected_types)) & (poi_df['level'].isin(selected_risks))]
else:
    final_df = pd.DataFrame()

# ================================
# 4. MAP DISPLAY
# ================================
st.title("🛡️ NOVA Strategic Intelligence")

c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    
    if not final_df.empty:
        for r in final_df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=8, color='white', weight=0.5,
                fill=True, fill_color=r.color, fill_opacity=0.8,
                popup=f"<b>{r.name}</b><br>Type: {r.type}"
            ).add_to(m)
    
    st_folium(m, width=900, height=500, key="nova_map_final")

with c2:
    st.metric("Pins Tracked", len(final_df))
    if not final_df.empty:
        st.subheader("⚠️ Priority List")
        watchlist = final_df.sort_values('raw_score', ascending=False).head(10)
        for _, row in watchlist.iterrows():
            st.warning(f"**{row['name']}**")
            st.caption(f"{row['type']} | Score: {round(row['raw_score'], 1)}")
