import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
import numpy as np
from serpapi import GoogleSearch

# ================================
# 1. API CONFIG & DATABASE
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# YOUR KEYS - Safe now that repo is private
FBI_KEY = "sB9Qct1qwv7c5tKpEE8SUAzmOoRfCmKooX5txXSI"
SERP_KEY = "e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550"

@st.cache_data(ttl=3600)
def load_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    try:
        # Load your specific NOVA datasets
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        poi['type'] = poi['type'].astype(str).str.lower().str.strip()
        
        return poi, census
    except:
        return pd.DataFrame(), pd.DataFrame()

# ================================
# 2. FBI INTELLIGENCE LAYER
# ================================
@st.cache_data(ttl=86400) # Only check FBI once a day
def get_fbi_status():
    # Pulling Virginia participation data to verify reporting consistency
    url = f"https://api.usa.gov/crime/fbi/sapi/api/participation/states/VA?api_key={FBI_KEY}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            # We look for the most recent reporting year
            data = r.json()
            return data.get('data', [])[-1] # Return latest year stats
        return None
    except:
        return None

fbi_intel = get_fbi_status()
poi_df, census_df = load_data()

# ================================
# 3. SIDEBAR & LIVE FILTERS
# ================================
st.sidebar.title("🛡️ Intelligence Control")

# Status Indicators
if fbi_intel:
    st.sidebar.success(f"✅ FBI API: Connected (Active Data: {fbi_intel.get('year')})")
else:
    st.sidebar.error("❌ FBI API: Connection Failed")

if not poi_df.empty:
    # 1. RISK CALCULATION
    county_risk = census_df.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6, 'bar': 4}
    
    scores, colors, levels = [], [], []
    for _, row in poi_df.iterrows():
        base = weights.get(row['type'], 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        # We boost the score if the FBI indicates high agency participation in VA
        fbi_boost = 2 if fbi_intel and fbi_intel.get('participating_agencies', 0) > 300 else 0
        
        fs = base + (vuln * 10) + fbi_boost
        scores.append(fs)
        if fs >= 18: colors.append('red'); levels.append('HIGH')
        elif fs >= 12: colors.append('orange'); levels.append('MEDIUM')
        else: colors.append('blue'); levels.append('LOW')
    
    poi_df['raw_score'], poi_df['color'], poi_df['level'] = scores, colors, levels

    # 2. FILTER UI
    with st.sidebar.expander("📊 Data Discovery"):
        st.write(poi_df['type'].value_counts())

    all_cats = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Business Categories", options=all_cats, default=all_cats[:5], key="cat_v5")
    selected_risks = st.sidebar.multiselect("Risk Tiers", options=['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'], key="risk_v5")
    
    final_df = poi_df[(poi_df['type'].isin(selected_types)) & (poi_df['level'].isin(selected_risks))]

# ================================
# 4. MAP & DOSSIER
# ================================
st.title("🛡️ NOVA Strategic Intelligence Dashboard")

c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng], radius=8, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Risk: {r.level}"
        ).add_to(m)
    st_folium(m, width=900, height=500, key="nova_map_v5")

with c2:
    st.metric("Pins on Map", len(final_df))
    st.subheader("⚠️ Priority List")
    watchlist = final_df.sort_values('raw_score', ascending=False).head(10)
    for _, row in watchlist.iterrows():
        icon = "🔴" if row['level'] == 'HIGH' else "🟠" if row['level'] == 'MEDIUM' else "🔵"
        st.write(f"{icon} **{row['name']}**")
        st.caption(f"{row['type']} | Score: {round(row['raw_score'], 1)}")
