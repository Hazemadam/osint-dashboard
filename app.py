import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
from serpapi import GoogleSearch

# ================================
# 1. DATA LOADING & CLEANING
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_and_process_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # Standardize Columns
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'lon': 'lng', 'latitude': 'lat'})
        census.columns = [c.lower().strip() for c in census.columns]
        
        return poi, census
    except Exception as e:
        st.error(f"Data Loading Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_and_process_data()

# ================================
# 2. INTELLIGENCE ENGINE (The "Brain")
# ================================
def apply_global_risk(poi, census):
    if poi.empty or census.empty:
        return poi
    
    # Map vulnerability by county
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 2}
    
    scores = []
    for _, row in poi.iterrows():
        base = weights.get(str(row['type']).lower(), 1)
        # Fuzzy match county
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vulnerability = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0)
        scores.append(base + (vulnerability * 10))
    
    poi['raw_score'] = scores
    avg, std = poi['raw_score'].mean(), poi['raw_score'].std()
    
    def get_color(s):
        if s > (avg + (std or 1)): return 'red', 'HIGH'
        if s > avg: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_color))
    return poi

# ================================
# 3. SIDEBAR & DEEP SCANNER
# ================================
st.sidebar.title("🕵️ OSINT Control Panel")
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    # Score everything once
    scored_df = apply_global_risk(poi_df, census_df)
    
    # Filters
    selected_types = st.sidebar.multiselect("Business Category", sorted(scored_df['type'].unique()), default=['motel', 'massage', 'nightclub'])
    final_df = scored_df[scored_df['type'].isin(selected_types)]
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Deep Scan Intelligence")
    target_name = st.sidebar.selectbox("Select Target", sorted(final_df['name'].unique()))
    
    if st.sidebar.button("Run Review Interrogation"):
        search = GoogleSearch({"engine": "google_maps", "q": f"{target_name} Northern Virginia", "api_key": api_key})
        res = search.get_dict()
        d_id = res.get("local_results", [{}])[0].get("data_id")
        
        if d_id:
            rev_search = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key})
            reviews = rev_search.get_dict().get("reviews", [])
            flags = ['scam', 'police', 'illegal', 'sketchy', 'trap', 'assault', 'dangerous', 'drugs']
            found = [f"Found: '{f}'" for r in reviews for f in flags if f in r.get("snippet", "").lower()]
            
            if found:
                st.sidebar.error(f"🚩 RED FLAGS: {len(set(found))}")
                for f in set(found): st.sidebar.write(f"- {f}")
            else:
                st.sidebar.success("No immediate sketchy keywords found.")
        else:
            st.sidebar.warning("Could not locate digital ID for this target.")

# ================================
# 4. MAIN DASHBOARD DISPLAY
# ================================
st.title("🛡️ NOVA Strategic Risk Analysis")
col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=6, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Type: {r.type}"
        ).add_to(m)
    st_folium(m, width=850, height=600, key="nova_map")

with col2:
    st.metric("Analyzed Targets", len(final_df))
    st.subheader("⚠️ High Priority")
    high_risk = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(5)
    for _, row in high_risk.iterrows():
        st.warning(f"**{row['name']}**")
