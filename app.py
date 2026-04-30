import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from serpapi import GoogleSearch

# ==========================================
# 1. INITIAL CONFIG & MULTI-SOURCE LOADING
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

try:
    SERP_KEY = st.secrets["SERP_KEY"]
except:
    st.error("🔑 SERP_KEY missing in Secrets!")
    st.stop()

@st.cache_data(ttl=3600)
def load_all_intel():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"
    try:
        # Core Map Data
        poi = pd.read_parquet(f"{base}nova_data.parquet")
        census = pd.read_parquet(f"{base}vulnerability_data.parquet")
        
        # FBI Intelligence Files
        f_serv = pd.read_csv(f"{base}fbi_servitude.csv")
        f_sex = pd.read_csv(f"{base}fbi_sex_acts.csv")
        l_sex = pd.read_csv(f"{base}fbi_loc_sex.csv")
        l_serv = pd.read_csv(f"{base}fbi_loc_serv.csv")

        # Basic Cleanup
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        census.columns = [c.lower().strip() for c in census.columns]
        
        return poi, census, f_serv, f_sex, l_sex, l_serv
    except Exception as e:
        st.error(f"⚠️ Intelligence Feed Failure: {e}")
        return [pd.DataFrame()]*6

poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv = load_all_intel()

# ==========================================
# 2. THE INTELLIGENCE ENGINE (FUSION LOGIC)
# ==========================================
def run_threat_assessment(poi, census, s_trend, x_trend, lsx, lsv):
    if poi.empty: return poi, pd.Series(), 1.0
    
    # A. TREND ANALYSIS (The "Multiplier")
    # Combine both crime types to find the regional pulse
    combined_trend = s_trend.iloc[0, 1:].astype(float) + x_trend.iloc[0, 1:].astype(float)
    recent_activity = combined_trend.tail(6).mean()
    # If more than 5 combined offenses/month, set high alert
    multiplier = 1.35 if recent_activity > 5 else 1.0
    
    # B. LOCATION RISK MAPPING (Data-Driven Weights)
    # Convert FBI location CSVs to dictionaries for fast lookup
    sex_loc_map = dict(zip(lsx['key'], lsx['value']))
    serv_loc_map = dict(zip(lsv['key'], lsv['value']))
    
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    scores, colors, levels = [], [], []

    for _, row in poi.iterrows():
        # Match POI type to the specific FBI location report counts
        if row['type'] in ['motel', 'hotel', 'spa', 'massage']:
            base_weight = sex_loc_map.get('Hotel/Motel/Etc.', 10) / 5
        elif row['type'] in ['apartment', 'residential']:
            base_weight = serv_loc_map.get('Residence/Home', 5) / 2
        else:
            base_weight = 5

        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        # CALCULATE FINAL THREAT SCORE
        # Formula: (FBI Venue Weight + (Census Vulnerability * 10)) * Regional Trend
        fs = (base_weight + (vuln * 10)) * multiplier
        scores.append(fs)
        
        if fs >= 22: colors.append('red'); levels.append('HIGH')
        elif fs >= 15: colors.append('orange'); levels.append('MEDIUM')
        else: colors.append('blue'); levels.append('LOW')
            
    poi['raw_score'], poi['color'], poi['level'] = scores, colors, levels
    return poi, combined_trend, multiplier

# ==========================================
# 3. SIDEBAR & INTERFACE
# ==========================================
st.sidebar.title("🛡️ NOVA Intel Command")

if not poi_df.empty:
    processed_df, master_trend, threat_multiplier = run_threat_assessment(
        poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv
    )
    
    st.sidebar.metric("Regional Multiplier", f"{round(threat_multiplier, 2)}x", delta="High Alert" if threat_multiplier > 1 else "Normal")

    with st.sidebar.expander("📈 Total Regional Trend (FBI)"):
        st.line_chart(master_trend.tail(18))
        st.caption("Aggregated monthly reports for VA (Involuntary Servitude + Commercial Sex Acts)")

    st.sidebar.subheader("Target Filters")
    all_types = sorted(processed_df['type'].unique())
    selected_types = st.sidebar.multiselect("Venue Categories", all_types, default=all_types[:3])
    final_df = processed_df[processed_df['type'].isin(selected_types)]

    st.sidebar.markdown("---")
    if not final_df.empty:
        target = st.sidebar.selectbox("Select Target for OSINT", sorted(final_df['name'].unique()))
        if st.sidebar.button("Run Deep Scan"):
            with st.spinner(f"Scanning Intelligence for {target}..."):
                # SERP API Logic
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": SERP_KEY})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id") if "local_results" in res else None
                if d_id:
                    revs = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": SERP_KEY}).get_dict().get("reviews", [])
                    flags = ['buzzer', 'locked', 'cash only', 'security', 'scared', 'after hours']
                    found = [f for r in revs for f in flags if f in str(r.get("snippet", "")).lower()]
                    st.session_state['scan_results'] = {target: list(set(found)) if found else ["CLEAR"]}

# ==========================================
# 4. MAIN DASHBOARD VISUALS
# ==========================================
st.title("🛡️ NOVA Risk Intelligence")
st.caption("Fusing FBI Crime Trends, Census Vulnerability, and OSINT Metadata")

c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng], radius=9, color='white', weight=0.7,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Risk Score: {round(r.raw_score, 1)}<br>Tier: {r.level}"
        ).add_to(m)
    st_folium(m, width=900, height=550, key="nova_master_map")

    if 'scan_results' in st.session_state and target in st.session_state['scan_results']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Report: {target}")
        res_list = st.session_state['scan_results'][target]
        if "CLEAR" in res_list:
            st.success("✅ No linguistic red-flags detected in public metadata.")
        else:
            st.error(f"🚩 **Linguistic Red-Flags Detected:** {', '.join(res_list)}")

with c2:
    st.metric("Total Priority Targets", len(final_df))
    
    st.subheader("⚠️ Top Risk Locations")
    # Show the venues that the FBI data says are the #1 threat
    if not loc_sex.empty:
        top_venue = loc_sex.iloc[0]['key']
        st.info(f"**Primary Vector:** {top_venue}")
    
    st.markdown("---")
    watchlist = final_df.sort_values('raw_score', ascending=False).head(8)
    for _, row in watchlist.iterrows():
        icon = "🔴" if row['level'] == 'HIGH' else "🟠"
        st.write(f"{icon} **{row['name']}**")
        st.caption(f"Score: {round(row['raw_score'], 1)} | {row['type']}")
