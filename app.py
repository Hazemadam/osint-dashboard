import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
from serpapi import GoogleSearch

# ================================
# 1. DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_and_process_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        return poi, census
    except: return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_and_process_data()

# ================================
# 2. INTELLIGENCE ENGINE (The Brain)
# ================================
def apply_global_risk(poi, census):
    if poi.empty or census.empty: return poi
    
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    # Boosted weights to ensure red dots appear for specific types
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6}
    
    scores = []
    for _, row in poi.iterrows():
        base = weights.get(str(row['type']).lower(), 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0)
        scores.append(base + (vuln * 10))
    
    poi['raw_score'] = scores
    
    # NEW SENSITIVITY MATH:
    # We force the top 15% of scores to be RED
    threshold_high = np.percentile(scores, 85)
    threshold_med = np.percentile(scores, 60)

    def get_color_logic(s):
        if s >= threshold_high: return 'red', 'HIGH'
        if s >= threshold_med: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_color_logic))
    return poi

# ================================
# 3. SIDEBAR & SCANNER
# ================================
st.sidebar.title("🛡️ NOVA OSINT Control")
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    scored_df = apply_global_risk(poi_df, census_df)
    
    st.sidebar.subheader("Map Filters")
    s_types = st.sidebar.multiselect("Categories", sorted(scored_df['type'].unique()), default=['motel', 'massage', 'nightclub', 'spa'])
    s_risks = st.sidebar.multiselect("Risk Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    final_df = scored_df[(scored_df['type'].isin(s_types)) & (scored_df['level'].isin(s_risks))]

    flags = ['tired', 'confused', 'exhausted', 'scared', 'after hours', 'buzzer', 'locked', 'police', 'raid', 'extra', 'special', 'cash only']

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Deep Scan")
    if not final_df.empty:
        target = st.sidebar.selectbox("Target", sorted(final_df['name'].unique()))
        if st.sidebar.button("Run OSINT Review Scan"):
            with st.spinner("Scanning..."):
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": api_key})
                d_id = search.get_dict().get("local_results", [{}])[0].get("data_id")
                if d_id:
                    revs = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key}).get_dict().get("reviews", [])
                    found = [f for r in revs for f in flags if f in r.get("snippet", "").lower()]
                    if found:
                        st.session_state['found'], st.session_state['target'] = list(set(found)), target
                        st.sidebar.error(f"🚩 {len(set(found))} FLAGS")
                        for f in set(found): st.sidebar.write(f"- {f}")
                    else: st.sidebar.success("Clear")

# ================================
# 4. MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker([r.lat, r.lng], radius=7, color='white', weight=0.5,
                            fill=True, fill_color=r.color, fill_opacity=0.8,
                            popup=f"{r.name} ({r.level})").add_to(m)
    st_folium(m, width=800, height=500)

    if st.session_state.get('target') == target and st.session_state.get('found'):
        st.markdown("---")
        st.subheader(f"📄 Intelligence Dossier: {target}")
        st.write(f"**Indicators:** {', '.join(st.session_state['found'])}")

with c2:
    st.metric("Analyzed Targets", len(final_df))
    st.subheader("⚠️ Priority Watchlist")
    for _, row in final_df[final_df['level'] == 'HIGH'].head(5).iterrows():
        st.warning(f"**{row['name']}**")
