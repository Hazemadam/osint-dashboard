import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
import requests
from serpapi import GoogleSearch

# ================================
# 1. CONFIG & SECRETS
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# Securely grab keys from Streamlit Cloud Secrets
try:
    FBI_KEY = st.secrets["FBI_KEY"]
    SERP_KEY = st.secrets["SERP_KEY"]
except Exception:
    st.error("🔑 Secrets missing! Add FBI_KEY and SERP_KEY to Streamlit Cloud Settings.")
    st.stop()

@st.cache_data(ttl=3600)
def load_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        poi['type'] = poi['type'].astype(str).str.lower().str.strip()
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except: 
        return pd.DataFrame(), pd.DataFrame()

# FBI Connection Check (Heartbeat)
def get_fbi_heartbeat(api_key):
    url = f"https://api.usa.gov/crime/fbi/sapi/api/participation/national?api_key={api_key}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200: return "Online"
        return f"Offline ({r.status_code})"
    except: return "Connection Error"

poi_df, census_df = load_data()
fbi_status = get_fbi_heartbeat(FBI_KEY)

# ================================
# 2. THE BRAIN (Standardized Scoring)
# ================================
def apply_risk(poi, census):
    if poi.empty or census.empty: return poi
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6, 'bar': 4}
    
    scores, colors, levels = [], [], []
    for _, row in poi.iterrows():
        base = weights.get(row['type'], 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        fs = base + (vuln * 10)
        scores.append(fs)
        if fs >= 17: colors.append('red'); levels.append('HIGH')
        elif fs >= 11: colors.append('orange'); levels.append('MEDIUM')
        else: colors.append('blue'); levels.append('LOW')
            
    poi['raw_score'], poi['color'], poi['level'] = scores, colors, levels
    return poi

# ================================
# 3. SIDEBAR & LOGIC
# ================================
st.sidebar.title("🔍 Control Panel")

# Display Secret Status (Safe way)
st.sidebar.info(f"SerpApi: Active | FBI API: {fbi_status}")

if not poi_df.empty:
    df = apply_risk(poi_df, census_df)
    
    with st.sidebar.expander("📊 Data Discovery"):
        st.write(df['type'].value_counts())
    
    st.sidebar.subheader("Live Filters")
    all_cats = sorted(df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Business Categories", options=all_cats, default=all_cats[:3])
    selected_risks = st.sidebar.multiselect("Risk Tiers", options=['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    # Filter Logic
    final_df = df[(df['type'].isin(selected_types)) & (df['level'].isin(selected_risks))]

    st.sidebar.markdown("---")
    if not final_df.empty:
        target = st.sidebar.selectbox("Interrogate Target", sorted(final_df['name'].unique()))
        if st.sidebar.button("Run OSINT Scan"):
            with st.spinner("Analyzing Google Maps Intelligence..."):
                # Use SERP_KEY from Secrets
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": SERP_KEY})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id") if "local_results" in res else None
                if d_id:
                    revs = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": SERP_KEY}).get_dict().get("reviews", [])
                    flags = ['tired', 'scared', 'after hours', 'buzzer', 'locked', 'police', 'extra', 'special', 'cash only']
                    found = [f for r in revs for f in flags if f in str(r.get("snippet", "")).lower()]
                    st.session_state['scan_results'] = {target: list(set(found)) if found else ["CLEAR"]}

# ================================
# 4. MAIN MAP
# ================================
st.title("🛡️ NOVA Risk Intelligence")
c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng], radius=8, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Risk: {r.level}"
        ).add_to(m)
    st_folium(m, width=900, height=500, key="nova_map_final")

    if 'scan_results' in st.session_state and 'target' in locals() and target in st.session_state['scan_results']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Report: {target}")
        st.info(f"**Flags Detected:** {', '.join(st.session_state['scan_results'][target])}")

with c2:
    st.metric("Pins Showing", len(final_df))
    st.subheader("⚠️ Priority List")
    watchlist = final_df.sort_values('raw_score', ascending=False).head(10)
    for _, row in watchlist.iterrows():
        icon = "🔴" if row['level'] == 'HIGH' else "🟠" if row['level'] == 'MEDIUM' else "🔵"
        st.write(f"{icon} **{row['name']}**")
        st.caption(f"{row['type']} | Score: {round(row['raw_score'], 1)}")
