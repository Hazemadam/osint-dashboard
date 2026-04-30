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

# Persistent memory for scan results
if 'scan_results' not in st.session_state:
    st.session_state['scan_results'] = {}

@st.cache_data(ttl=3600)
def load_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        # Normalize category names
        poi['type'] = poi['type'].astype(str).str.lower().str.strip()
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except Exception as e:
        st.error(f"Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. RISK LOGIC
# ================================
def apply_risk(poi, census):
    if poi.empty or census.empty: return poi
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6, 'bar': 4}
    
    scores, colors, levels = [], [], []
    for _, row in poi.iterrows():
        b_type = row['type']
        base = weights.get(b_type, 1)
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
# 3. SIDEBAR & FILTERS
# ================================
st.sidebar.title("🔍 Control Panel")
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    df = apply_risk(poi_df, census_df)
    
    # --- FIXED MULTISELECT LOGIC ---
    st.sidebar.subheader("Live Filters")
    
    # We define the options explicitly so they never "disappear"
    master_categories = sorted(df['type'].unique().tolist())
    
    # The 'key' ensures Streamlit keeps the widget state stable
    selected_types = st.sidebar.multiselect(
        "Select Categories", 
        options=master_categories,
        default=[t for t in ['motel', 'massage', 'nightclub'] if t in master_categories],
        key="category_selector"
    )
    
    selected_risks = st.sidebar.multiselect(
        "Select Risk Levels",
        options=['HIGH', 'MEDIUM', 'LOW'],
        default=['HIGH', 'MEDIUM'],
        key="risk_selector"
    )
    
    # Filter the data based on selection
    final_df = df[(df['type'].isin(selected_types)) & (df['level'].isin(selected_risks))]

    st.sidebar.markdown("---")
    st.sidebar.subheader("🕵️ Deep Scan")
    
    if not final_df.empty:
        target = st.sidebar.selectbox("Interrogate Target", sorted(final_df['name'].unique()))
        if st.sidebar.button("Run OSINT Scan"):
            with st.spinner("Scanning..."):
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": api_key})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id") if "local_results" in res else None
                
                if d_id:
                    revs = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key}).get_dict().get("reviews", [])
                    flags = ['tired', 'scared', 'after hours', 'buzzer', 'locked', 'police', 'extra', 'special', 'cash only']
                    found = [f for r in revs for f in flags if f in str(r.get("snippet", "")).lower()]
                    st.session_state['scan_results'][target] = list(set(found)) if found else ["CLEAR"]
                else:
                    st.sidebar.warning("Target ID not found.")

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
            popup=f"{r.name} ({r.type})"
        ).add_to(m)
    st_folium(m, width=900, height=500, key="nova_map")

    # Show Scan Results if they exist
    if 'target' in locals() and target in st.session_state['scan_results']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Report: {target}")
        st.info(f"**Flags Detected:** {', '.join(st.session_state['scan_results'][target])}")

with c2:
    st.metric("Pins on Map", len(final_df))
    st.subheader("⚠️ Priority List")
    watchlist = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(8)
    for _, row in watchlist.iterrows():
        st.warning(f"**{row['name']}**")
        st.caption(f"{row['type']} | Score: {round(row['raw_score'], 1)}")
