import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
from serpapi import GoogleSearch

# ================================
# 1. CONFIG & DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# Initialize session state for the Dossier
if 'show_dossier' not in st.session_state:
    st.session_state['show_dossier'] = False
if 'last_scan_found' not in st.session_state:
    st.session_state['last_scan_found'] = None

@st.cache_data(ttl=3600)
def load_and_process_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # Clean columns
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'lon': 'lng', 'latitude': 'lat'})
        census.columns = [c.lower().strip() for c in census.columns]
        
        return poi, census
    except Exception as e:
        st.error(f"Data Loading Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_and_process_data()

# ================================
# 2. INTELLIGENCE ENGINE (The Balanced Brain)
# ================================
def apply_global_risk(poi, census):
    if poi.empty or census.empty:
        return poi
    
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    
    # Surgical Weights for NOVA
    weights = {
        'stripclub': 15, 'massage': 12, 'nightclub': 10, 
        'motel': 10, 'spa': 6, 'bar': 4, 'hotel': 2
    }
    
    scores = []
    for _, row in poi.iterrows():
        base = weights.get(str(row['type']).lower(), 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vulnerability = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        # Score = Type Weight + (Neighborhood Stress * 10)
        scores.append(base + (vulnerability * 10))
    
    poi['raw_score'] = scores
    
    # FIXED THRESHOLDS: Prevents "Everything is Red"
    def get_risk_meta(s):
        if s >= 18: return 'red', 'HIGH'      # Combines high-risk type + high-stress area
        if s >= 12: return 'orange', 'MEDIUM' # Mid-range concerns
        return 'blue', 'LOW'                  # Baseline locations
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_risk_meta))
    return poi

# ================================
# 3. SIDEBAR & SURGICAL SCANNER
# ================================
st.sidebar.title("🛡️ Intelligence Control")

# API Key - Masked by default
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    scored_df = apply_global_risk(poi_df, census_df)
    
    st.sidebar.subheader("Map Controls")
    all_types = sorted(scored_df['type'].unique())
    s_types = st.sidebar.multiselect("Categories", all_types, default=['motel', 'massage', 'nightclub'])
    s_risks = st.sidebar.multiselect("Risk Tiers", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    final_df = scored_df[(scored_df['type'].isin(s_types)) & (scored_df['level'].isin(s_risks))]

    # MASTER OSINT FLAG LIST
    flags = [
        'tired', 'confused', 'exhausted', 'sleeping', 'scared', 'nervous', 'dont know', 'living there',
        'after hours', 'private party', 'late night', 'buzzer', 'back door', 'locked', 'window covered',
        'police', 'raid', 'undercover', 'illegal', 'sketchy', 'trap', 'assault', 'dangerous', 'arrest',
        'cash only', 'no receipt', 'extra', 'special', 'full service', 'forced', 'security guard'
    ]

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Deep Scan Engine")
    
    if not final_df.empty:
        target_name = st.sidebar.selectbox("Select Target to Interrogate", sorted(final_df['name'].unique()))
        
        if st.sidebar.button("Run OSINT Review Scan"):
            with st.spinner(f"Interrogating Google for {target_name}..."):
                # Phase 1: Search for Place ID
                search = GoogleSearch({"engine": "google_maps", "q": f"{target_name} Northern Virginia", "api_key": api_key})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id")
                
                if d_id:
                    # Phase 2: Pull and Filter Reviews
                    rev_search = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key})
                    reviews = rev_search.get_dict().get("reviews", [])
                    found = [f for r in reviews for f in flags if f in r.get("snippet", "").lower()]
                    
                    if found:
                        st.session_state['last_scan_found'] = list(set(found))
                        st.session_state['last_scan_target'] = target_name
                        
                        st.sidebar.error(f"🚩 {len(set(found))} RED FLAGS DETECTED")
                        # Priority Alert for Critical Indicators
                        critical = ['police', 'raid', 'scared', 'forced', 'arrest', 'locked']
                        if any(c in str(found) for c in critical):
                            st.sidebar.warning("🚨 CRITICAL: Human behavior or Law Enforcement flags found.")
                        
                        for f in set(found):
                            st.sidebar.write(f"- Found keyword: **'{f}'**")
                    else:
                        st.sidebar.success("Clear: No indicators found in recent reviews.")
                        st.session_state['last_scan_found'] = None
                else:
                    st.sidebar.warning("Could not find a digital ID for this target.")

        # Dossier Button - Appears only if flags are found
        if st.session_state.get('last_scan_found') and st.session_state.get('last_scan_target') == target_name:
            if st.sidebar.button("📋 Generate Intelligence Dossier"):
                st.session_state['show_dossier'] = True

# ================================
# 4. MAIN DASHBOARD & DOSSIER
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
col_map, col_list = st.columns([3, 1])

with col_map:
    # Centered on Northern Virginia (Fairfax/Centreville area)
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=7, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Type: {r.type}"
        ).add_to(m)
        
    st_folium(m, width=850, height=500, key="nova_map")

    # The Dossier Report Section
    if st.session_state['show_dossier']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Dossier: {st.session_state['last_scan_target']}")
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            st.write(f"**Target Priority:** {final_df[final_df['name']==st.session_state['last_scan_target']]['level'].values[0]}")
            st.write(f"**Keywords Detected:** {', '.join(st.session_state['last_scan_found'])}")
        with d_col2:
            st.write("**Operational Notes:** Reviews indicate suspicious behavioral patterns or unlicensed activity. Recommend further OSINT surveillance.")
            if st.button("Close Report"):
                st.session_state['show_dossier'] = False

with col_list:
    st.metric("Analyzed Targets", len(final_df))
    st.subheader("⚠️ Priority Watchlist")
    
    # Display the top 5 highest-scored locations
    high_risk = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(5)
    if not high_risk.empty:
        for _, row in high_risk.iterrows():
            st.warning(f"**{row['name']}**")
            st.caption(f"Category: {row['type']} | Score: {round(row['raw_score'],1)}")
    else:
        st.info("No High-Risk targets in current filter.")
