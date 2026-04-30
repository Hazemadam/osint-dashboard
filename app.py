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

# Ensure dossier memory doesn't break on refresh
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
        
        # Column Normalization
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'lon': 'lng', 'latitude': 'lat'})
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. THE RISK BRAIN (Balanced)
# ================================
def get_risk_scores(poi, census):
    if poi.empty or census.empty: return poi
    
    # Map vulnerability by county
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    
    # Inherent weights for Northern Virginia sectors
    weights = {'stripclub': 15, 'massage': 12, 'nightclub': 10, 'motel': 10, 'spa': 6, 'bar': 4}
    
    scores, colors, levels = [], [], []
    for _, row in poi.iterrows():
        base = weights.get(str(row['type']).lower(), 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        final_score = base + (vuln * 10)
        scores.append(final_score)
        
        # BALANCED THRESHOLDS
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
    # Calculate everything first
    processed_df = get_risk_scores(poi_df, census_df)
    
    # LIVE FILTERS
    st.sidebar.subheader("Live Filters")
    available_types = sorted(processed_df['type'].unique())
    selected_types = st.sidebar.multiselect("Business Categories", available_types, default=['motel', 'massage', 'nightclub'])
    selected_risks = st.sidebar.multiselect("Risk Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    # APPLY FILTERS TO DATASET
    mask = (processed_df['type'].isin(selected_types)) & (processed_df['level'].isin(selected_risks))
    final_df = processed_df[mask]

    # SCANNER LOGIC
    st.sidebar.markdown("---")
    st.sidebar.subheader("🕵️ Deep Scan Target")
    
    # Select box only shows businesses that pass the filters
    if not final_df.empty:
        target = st.sidebar.selectbox("Target to Interrogate", sorted(final_df['name'].unique()))
        
        if st.sidebar.button("Run OSINT Review Scan"):
            with st.spinner(f"Analyzing {target}..."):
                # SerpApi Search
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": api_key})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id")
                
                if d_id:
                    rev_search = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key})
                    reviews = rev_search.get_dict().get("reviews", [])
                    
                    # MASTER FLAG LIST
                    flags = ['tired', 'confused', 'exhausted', 'scared', 'after hours', 'buzzer', 'locked', 
                             'police', 'raid', 'extra', 'special', 'cash only', 'no receipt', 'forced']
                    
                    found = [f for r in reviews for f in flags if f in r.get("snippet", "").lower()]
                    
                    if found:
                        st.session_state['last_scan_found'] = list(set(found))
                        st.session_state['last_scan_target'] = target
                        st.sidebar.error(f"🚩 {len(set(found))} RED FLAGS FOUND")
                        for f in set(found): st.sidebar.write(f"- {f}")
                    else:
                        st.sidebar.success("No red flag keywords found.")
                        st.session_state['last_scan_found'] = None
                else:
                    st.sidebar.warning("Could not locate place ID.")

# ================================
# 4. MAIN DISPLAY
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
col_map, col_metrics = st.columns([3, 1])

with col_map:
    # Base Map
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    
    # Plotting filtered results
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=8, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Type: {r.type}"
        ).add_to(m)
    
    st_folium(m, width=900, height=550, key="main_map")

    # Show Dossier if a scan was just performed
    if st.session_state['last_scan_found']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Dossier: {st.session_state['last_scan_target']}")
        st.info(f"**Indicators Detected:** {', '.join(st.session_state['last_scan_found'])}")
        st.write("*Analyst Note: Behavioral indicators found in user testimony suggest unlicensed operational patterns.*")

with col_metrics:
    st.metric("Filtered Targets", len(final_df))
    st.subheader("⚠️ Priority List")
    # Show top 10 highest risk items in the filtered view
    watchlist = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(10)
    for _, row in watchlist.iterrows():
        st.warning(f"**{row['name']}**")
        st.caption(f"Score: {round(row['raw_score'], 1)}")
