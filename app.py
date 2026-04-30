import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# ==========================================
# 1. INITIAL SETUP & "SAFETY NET" DEFAULTS
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# Pre-define all variables globally to prevent NameErrors
fbi_status = "Initializing..."
final_df = pd.DataFrame()
poi_df = pd.DataFrame()
census_df = pd.DataFrame()

# Securely grab keys from Streamlit Secrets
try:
    FBI_KEY = st.secrets["FBI_KEY"]
    SERP_KEY = st.secrets["SERP_KEY"]
except Exception:
    st.error("🔑 Secrets missing! Add FBI_KEY and SERP_KEY to Streamlit Settings.")
    st.stop()

# ==========================================
# 2. FBI CONNECTION (STABILIZED ENDPOINT)
# ==========================================
@st.cache_data(ttl=600)
def get_fbi_status(api_key):
    """Hits a stable endpoint for a connection heartbeat."""
    url = f"https://api.usa.gov/crime/fbi/sapi/api/participation/national?api_key={api_key}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return "Online (FBI Data Link Active)"
        return f"Offline (Status: {r.status_code})"
    except Exception:
        return "Offline (Connection Error)"

# Execute the connection check
fbi_status = get_fbi_status(FBI_KEY)

# ==========================================
# 3. DATA LOADING (PUBLIC GITHUB)
# ==========================================
@st.cache_data(ttl=3600)
def load_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base_url = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"
    try:
        poi = pd.read_parquet(f"{base_url}nova_data.parquet")
        census = pd.read_parquet(f"{base_url}vulnerability_data.parquet")
        
        # Clean POI data
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        poi['type'] = poi['type'].astype(str).str.lower().str.strip()
        
        # Clean Census data
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except Exception as e:
        st.error(f"⚠️ GitHub Data Load Failure: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ==========================================
# 4. SIDEBAR & RISK LOGIC
# ==========================================
st.sidebar.title("🛡️ Intelligence Control")
st.sidebar.info(f"Key identified: {FBI_KEY[:4]}****")

if "Online" in fbi_status:
    st.sidebar.success(f"✅ FBI API: {fbi_status}")
else:
    st.sidebar.warning(f"⚠️ FBI API: {fbi_status}")

if not poi_df.empty:
    # 1. Risk Mapping
    county_risk = census_df.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6}
    
    scores, colors, levels = [], [], []
    for _, row in poi_df.iterrows():
        base = weights.get(row['type'], 2)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        fs = base + (vuln * 10)
        scores.append(fs)
        
        if fs >= 17: colors.append('red'); levels.append('HIGH')
        elif fs >= 11: colors.append('orange'); levels.append('MEDIUM')
        else: colors.append('blue'); levels.append('LOW')
    
    poi_df['raw_score'], poi_df['color'], poi_df['level'] = scores, colors, levels

    # 2. Filter Controls
    all_cats = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Categories", all_cats, default=all_cats[:3])
    selected_risks = st.sidebar.multiselect("Risk Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    # FIX: Corrected syntax for filtering
    type_mask = poi_df['type'].isin(selected_types)
    risk_mask = poi_df['level'].isin(selected_risks)
    final_df = poi_df[type_mask & risk_mask]

# ==========================================
# 5. DASHBOARD VISUALS
# ==========================================
st.title("🛡️ NOVA Strategic Intelligence")
st.markdown("---")

c1, col2 = st.columns([3, 1])

with c1:
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
                popup=f"<b>{r.name}</b><br>Score: {round(r.raw_score, 1)}"
            ).add_to(m)
    st_folium(m, width=800, height=500, key="nova_map_final_v2")

with col2:
    st.metric("Pins Tracked", len(final_df))
    if not final_df.empty:
        st.subheader("⚠️ Watchlist")
        watchlist = final_df.sort_values('raw_score', ascending=False).head(5)
        for _, row in watchlist.iterrows():
            st.warning(f"**{row['name']}**")
            st.caption(f"Score: {round(row['raw_score'], 1)} | {row['type']}")
