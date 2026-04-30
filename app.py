import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
from serpapi import GoogleSearch

# ================================
# 1. INITIAL CONFIG & STATE
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

# Session state for persistent data
if 'last_scan_found' not in st.session_state:
    st.session_state['last_scan_found'] = None
if 'last_scan_target' not in st.session_state:
    st.session_state['last_scan_target'] = None

@st.cache_data(ttl=3600)
def load_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # COLUMN NORMALIZATION
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'lon': 'lng', 'latitude': 'lat'})
        
        # Force all categories to title case for the UI, but keep logic robust
        if 'type' in poi.columns:
            poi['type'] = poi['type'].astype(str).str.strip().str.lower()
        
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except Exception as e:
        st.error(f"Data Connection Failed: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. THE RISK BRAIN
# ================================
def get_risk_scores(poi, census):
    if poi.empty or census.empty: return poi
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6, 'bar': 4}
    
    scores, colors, levels = [], [], []
    for _, row in poi.iterrows():
        b_type = str(row['type']).lower()
        base = weights.get(b_type, 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        final_score = base + (vuln * 10)
        scores.append(final_score)
        
        if final_score >= 17:
            colors.append('red'); levels.append('HIGH')
        elif final_score >= 11:
            colors.append('orange'); levels.append('MEDIUM')
        else:
            colors.append('blue'); levels.append('LOW')
            
    poi['raw_score'] = scores
    poi['color'] = colors
    poi['level'] = levels
    return poi

# ================================
# 3. SIDEBAR CONTROLS
# ================================
st.sidebar.title("🔍 Intelligence Control")
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    processed_df = get_risk_scores(poi_df, census_df)
    
    st.sidebar.subheader("Live Filters")
    
    # DYNAMIC CATEGORY FIX
    all_categories = sorted(processed_df['type'].unique())
    # We set a smart default: only show high-risk types initially
    smart_defaults = [t for t in ['motel', 'massage', 'nightclub'] if t in all_categories]
    
    selected_types = st.sidebar.multiselect(
        "Business Categories", 
        options=all_categories, 
        default=smart_defaults
    )
    
    selected_risks = st.sidebar.multiselect(
        "Risk Tiers", 
        options=['HIGH', 'MEDIUM', 'LOW'], 
        default=['HIGH', 'MEDIUM']
    )
    
    # APPLY FILTERS
    final_df = processed_df[
        (processed_df['type'].isin(selected_types)) & 
        (processed_df['level'].isin(selected_risks))
    ]

    st.sidebar.markdown("---")
    st.sidebar.subheader("🕵️ Deep Scan Engine")
    
    if not final_df.empty:
        target = st.sidebar.selectbox("Select Target", sorted(final_df['name'].unique()))
        if st.sidebar.button("Run OSINT Review Scan"):
            with st.spinner(f"Interrogating {target}..."):
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": api_key})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id") if "local_results" in res and len(res["local_results"]) > 0 else None
                
                if d_id:
                    rev_search = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key})
                    reviews = rev_search.get_dict().get("reviews", [])
                    flags = ['tired', 'confused', 'exhausted', 'scared', 'after hours', 'buzzer', 'locked', 'police', 'raid', 'extra', 'special', 'cash only', 'forced']
                    found = [f for r in reviews for f in flags if f in str(r.get("snippet", "")).lower()]
                    
                    if found:
                        st.session_state['last_scan_found'] = list(set(found))
                        st.session_state['last_scan_target'] = target
                        st.sidebar.error(f"🚩 {len(set(found))} RED FLAGS FOUND")
                    else:
                        st.sidebar.success("No indicators found.")
                        st.session_state['last_scan_found'] = None

    if st.sidebar.button("🔄 Reset Map & Filters"):
        st.cache_data.clear()
        st.rerun()

# ================================
# 4. MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
col_map, col_metrics = st.columns([3, 1])

with col_map:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng], radius=8, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Type: {r.type}"
        ).add_to(m)
    st_folium(m, width=900, height=550, key="main_map")

    if st.session_state['last_scan_found']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Dossier: {st.session_state['last_scan_target']}")
        st.info(f"**Detected Signals:** {', '.join(st.session_state['last_scan_found'])}")

with col_metrics:
    st.metric("Visible Targets", len(final_df))
    st.subheader("⚠️ Watchlist")
    watchlist = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(10)
    for _, row in watchlist.iterrows():
        st.warning(f"**{row['name']}**")
        st.caption(f"{row['type']} | Score: {round(row['raw_score'], 1)}")
