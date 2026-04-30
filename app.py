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
    
    # Weights for business types
    weights = {
        'stripclub': 12, 'massage': 10, 'nightclub': 9, 
        'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 2
    }
    
    scores = []
    for _, row in poi.iterrows():
        base = weights.get(str(row['type']).lower(), 1)
        # Fuzzy match county name
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vulnerability = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0)
        
        # Combined score: Business Type + Neighborhood Stress
        scores.append(base + (vulnerability * 10))
    
    poi['raw_score'] = scores
    
    # Calculate the "Curve" (Average and Standard Deviation)
    avg = poi['raw_score'].mean()
    std = poi['raw_score'].std() if poi['raw_score'].std() > 0 else 1
    
    def get_risk_meta(s):
        if s > (avg + std): return 'red', 'HIGH'
        if s > avg: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_risk_meta))
    return poi

# ================================
# 3. SIDEBAR & FILTERS
# ================================
st.sidebar.title("🕵️ OSINT Control Panel")

# API Key Input
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    # 1. Apply Risk Scoring to the WHOLE database first
    scored_df = apply_global_risk(poi_df, census_df)
    
    # 2. Category Filter
    all_types = sorted(scored_df['type'].unique())
    selected_types = st.sidebar.multiselect("Business Categories", all_types, default=['motel', 'massage', 'nightclub'])
    
    # 3. RISK LEVEL FILTER (What you requested)
    selected_risks = st.sidebar.multiselect("Risk Priority Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    # Apply both filters
    final_df = scored_df[
        (scored_df['type'].isin(selected_types)) & 
        (scored_df['level'].isin(selected_risks))
    ]
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Deep Scan Intelligence")
    
    if not final_df.empty:
        target_name = st.sidebar.selectbox("Select Target to Interrogate", sorted(final_df['name'].unique()))
        
        if st.sidebar.button("Run Review Interrogation"):
            with st.spinner(f"Analyzing {target_name}..."):
                search = GoogleSearch({"engine": "google_maps", "q": f"{target_name} Northern Virginia", "api_key": api_key})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id")
                
                if d_id:
                    rev_search = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key})
                    reviews = rev_search.get_dict().get("reviews", [])
                    
                    # Keywords to look for
                    flags = ['scam', 'police', 'illegal', 'sketchy', 'trap', 'assault', 'dangerous', 'drugs', 'bribe']
                    found = [f"Flag: '{f}'" for r in reviews for f in flags if f in r.get("snippet", "").lower()]
                    
                    if found:
                        st.sidebar.error(f"🚩 ALERTS DETECTED: {len(set(found))}")
                        for f in set(found): st.sidebar.write(f"- {f}")
                    else:
                        st.sidebar.success("No red flag keywords found in recent reviews.")
                else:
                    st.sidebar.warning("Could not find a digital ID for this target.")

# ================================
# 4. MAIN MAP & METRICS
# ================================
st.title("🛡️ NOVA Strategic Risk Analysis")
col1, col2 = st.columns([3, 1])

with col1:
    # Centered on Northern Virginia
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=7,
            color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Type: {r.type}"
        ).add_to(m)
        
    st_folium(m, width=850, height=600, key="nova_surgical_map")

with col2:
    st.metric("Filtered Targets", len(final_df))
    st.markdown("---")
    st.subheader("⚠️ High Priority List")
    
    # Show the top 10 highest scored targets in the sidebar
    top_targets = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(10)
    if not top_targets.empty:
        for _, row in top_targets.iterrows():
            st.error(f"**{row['name']}**\n(Score: {round(row['raw_score'],1)})")
    else:
        st.info("No 'HIGH' risk targets in the current filter.")
