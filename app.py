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
# 2. INTELLIGENCE ENGINE (The Brain)
# ================================
def apply_global_risk(poi, census):
    if poi.empty or census.empty:
        return poi
    
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    # Strategic Weights: Higher numbers = Higher inherent risk
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4}
    
    scores = []
    for _, row in poi.iterrows():
        base = weights.get(str(row['type']).lower(), 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vulnerability = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0)
        # Final Score = Business Type + (Local Poverty/Stress * 10)
        scores.append(base + (vulnerability * 10))
    
    poi['raw_score'] = scores
    avg, std = poi['raw_score'].mean(), poi['raw_score'].std() or 1
    
    def get_risk_meta(s):
        if s > (avg + std): return 'red', 'HIGH'
        if s > avg: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_meta_logic))
    return poi

def get_meta_logic(s):
    # Helper to avoid scope issues
    return ('red', 'HIGH') if s > 15 else (('orange', 'MEDIUM') if s > 8 else ('blue', 'LOW'))

# ================================
# 3. SIDEBAR & SURGICAL FILTERS
# ================================
st.sidebar.title("🛡️ NOVA OSINT Control")

# API Key
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    scored_df = apply_global_risk(poi_df, census_df)
    
    # --- FILTERS ---
    st.sidebar.subheader("Map Filters")
    s_types = st.sidebar.multiselect("Business Categories", sorted(scored_df['type'].unique()), default=['motel', 'massage', 'nightclub'])
    s_risks = st.sidebar.multiselect("Risk Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    final_df = scored_df[(scored_df['type'].isin(s_types)) & (scored_df['level'].isin(s_risks))]

    # --- THE SURGICAL FLAG LIST ---
    flags = [
        'tired', 'confused', 'exhausted', 'sleeping', 'scared', 'nervous', 'dont know', 'living there',
        'after hours', 'private party', 'late night', 'buzzer', 'back door', 'locked', 'window covered',
        'police', 'raid', 'undercover', 'illegal', 'sketchy', 'trap', 'assault', 'dangerous', 'arrest',
        'cash only', 'no receipt', 'extra', 'special', 'full service', 'forced', 'security guard'
    ]

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Deep Scan Intelligence")
    if not final_df.empty:
        target = st.sidebar.selectbox("Select Target to Interrogate", sorted(final_df['name'].unique()))
        
        if st.sidebar.button("Run OSINT Review Scan"):
            with st.spinner(f"Interrogating Google for {target}..."):
                # Phase 1: ID Discovery
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": api_key})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id")
                
                if d_id:
                    # Phase 2: Review Extraction
                    rev_search = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key})
                    reviews = rev_search.get_dict().get("reviews", [])
                    found = [f for r in reviews for f in flags if f in r.get("snippet", "").lower()]
                    
                    if found:
                        st.session_state['last_scan_found'] = list(set(found))
                        st.session_state['last_scan_target'] = target
                        
                        st.sidebar.error(f"🚩 {len(set(found))} RED FLAGS DETECTED")
                        # High-Priority Critical Alert
                        critical = ['police', 'raid', 'scared', 'forced', 'arrest', 'locked']
                        if any(c in str(found) for c in critical):
                            st.sidebar.warning("🚨 CRITICAL INDICATOR FOUND")
                        for f in set(found): st.sidebar.write(f"- Found: '{f}'")
                    else:
                        st.sidebar.success("Clear: No indicators found in recent reviews.")
                        st.session_state['last_scan_found'] = None
                else:
                    st.sidebar.warning("Could not find a digital ID for this target.")

        # --- THE NEW DOSSIER GENERATOR ---
        if st.session_state.get('last_scan_found') and st.session_state.get('last_scan_target') == target:
            st.sidebar.markdown("---")
            if st.sidebar.button("📋 Create Target Dossier"):
                st.sidebar.info("Generating Dossier below map...")
                st.session_state['show_dossier'] = True

# ================================
# 4. MAIN DASHBOARD DISPLAY
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng], radius=7, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Type: {r.type}"
        ).add_to(m)
    st_folium(m, width=850, height=500, key="nova_map")

    # Display Dossier if generated
    if st.session_state.get('show_dossier'):
        st.markdown("---")
        st.subheader(f"📄 Intelligence Dossier: {st.session_state['last_scan_target']}")
        col_a, col_b = st.columns(2)
        with col_a:
            st.write(f"**Target Status:** {final_df[final_df['name']==st.session_state['last_scan_target']]['level'].values[0]} PRIORITY")
            st.write(f"**Detected Signals:** {', '.join(st.session_state['last_scan_found'])}")
        with col_b:
            st.write("**Recommended Action:** Field Observation Required")
            st.write("**Analyst Note:** Review language indicates high probability of unlicensed activity or worker duress.")
        if st.button("Close Dossier"):
            st.session_state['show_dossier'] = False

with c2:
    st.metric("Analyzed Targets", len(final_df))
    st.subheader("⚠️ Priority Watchlist")
    high_risk = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(5)
    for _, row in high_risk.iterrows():
        st.warning(f"**{row['name']}**")
        st.caption(f"Type: {row['type']} | Score: {round(row['raw_score'],1)}")
