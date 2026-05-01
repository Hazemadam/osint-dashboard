import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from serpapi import GoogleSearch

# ==========================================
# 1. INITIAL CONFIG & DEFAULTS
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

final_df = pd.DataFrame()
poi_df = pd.DataFrame()
census_df = pd.DataFrame()
serv_trend = pd.DataFrame()
sex_trend = pd.DataFrame()
loc_sex = pd.DataFrame()
loc_serv = pd.DataFrame()
trend_bonus_active = 0.0

try:
    SERP_KEY = st.secrets["SERP_KEY"]
except:
    st.error("🔑 SERP_KEY missing in Streamlit Secrets!")
    st.stop()

@st.cache_data(ttl=3600)
def load_all_intel():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"
    
    try:
        p = pd.read_parquet(f"{base}nova_data.parquet")
        c = pd.read_parquet(f"{base}vulnerability_data.parquet")
        f_serv = pd.read_csv(f"{base}fbi_servitude.csv")
        f_sex = pd.read_csv(f"{base}fbi_sex_acts.csv")
        l_sex = pd.read_csv(f"{base}fbi_locations_sex_acts.csv")
        l_serv = pd.read_csv(f"{base}fbi_locations_servitude.csv")

        p.columns = [col.lower().strip() for col in p.columns]
        if 'longitude' in p.columns: p = p.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        c.columns = [col.lower().strip() for col in c.columns]
        
        return p, c, f_serv, f_sex, l_sex, l_serv
    except Exception as e:
        st.sidebar.error(f"📡 Data Link Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv = load_all_intel()

# ==========================================
# 2. THE 1-10 RISK ENGINE
# ==========================================
def run_threat_assessment(poi, census, s_trend, x_trend):
    if poi.empty: return pd.DataFrame(), pd.Series(), 0.0
    
    # --- A. FBI Trend Bonus (Max 1.0 Point) ---
    if not s_trend.empty and not x_trend.empty:
        combined = s_trend.iloc[0, 1:].astype(float) + x_trend.iloc[0, 1:].astype(float)
        trend_bonus = 1.0 if combined.tail(6).mean() > 5 else 0.0
    else:
        combined, trend_bonus = pd.Series(), 0.0

    if not census.empty and 'vulnerability_score' in census.columns:
        county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    else:
        county_risk = {}

    scores, colors = [], []
    for _, row in poi.iterrows():
        v_type = str(row.get('type', '')).lower()
        
        # --- B. FBI Venue Weight (Max 6.0 Points) ---
        if any(x in v_type for x in ['motel', 'hotel', 'spa', 'massage']):
            venue_score = 6.0
        elif any(x in v_type for x in ['apartment', 'residential', 'home', 'studio']):
            venue_score = 4.0
        else:
            venue_score = 1.0

        # --- C. Census Vulnerability (Max 3.0 Points) ---
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln_raw = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        vuln_score = vuln_raw * 3.0 
        
        # --- D. Final Calculation (Max 10.0) ---
        final_score = round(venue_score + vuln_score + trend_bonus, 1)
        # Ensure it never mathematically exceeds 10
        final_score = min(final_score, 10.0)
        scores.append(final_score)
        
        # Assign colors for visual map readability
        if final_score >= 8.0: colors.append('red')
        elif final_score >= 5.0: colors.append('orange')
        else: colors.append('blue')
            
    poi['risk_score'] = scores
    poi['color'] = colors
    return poi, combined, trend_bonus

# ==========================================
# 3. SIDEBAR CONTROLS
# ==========================================
st.sidebar.title("🛡️ NOVA Intel Command")

if not poi_df.empty:
    processed_df, master_trend, trend_bonus_active = run_threat_assessment(
        poi_df, census_df, serv_trend, sex_trend
    )
    
    st.sidebar.metric("Regional FBI Alert Bonus", f"+{trend_bonus_active} pts")

    # NEW: Slider for Risk Filtering (1 to 10)
    st.sidebar.subheader("Filter by Risk Score")
    min_risk = st.sidebar.slider(
        "Minimum Risk Threshold", 
        min_value=1.0, 
        max_value=10.0, 
        value=5.0, 
        step=0.5,
        help="Filters out locations below this score."
    )

    all_types = sorted(processed_df['type'].unique())
    selected_types = st.sidebar.multiselect("Venue Categories", all_types, default=all_types[:5])
    
    # Apply Mathematical Filter
    final_df = processed_df[
        (processed_df['risk_score'] >= min_risk) & 
        (processed_df['type'].isin(selected_types))
    ]

    target = None
    if not final_df.empty:
        st.sidebar.markdown("---")
        target = st.sidebar.selectbox("Select Target for OSINT", sorted(final_df['name'].unique()))
        if st.sidebar.button("Run Deep Scan"):
            with st.spinner("Scanning Metadata..."):
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": SERP_KEY})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id") if "local_results" in res else None
                if d_id:
                    revs = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": SERP_KEY}).get_dict().get("reviews", [])
                    flags = ['buzzer', 'locked', 'cash only', 'scared', 'after hours', 'back door']
                    found = [f for r in revs for f in flags if f in str(r.get("snippet", "")).lower()]
                    st.session_state['scan_results'] = {target: list(set(found)) if found else ["CLEAR"]}
else:
    st.sidebar.warning("📡 Waiting for data connection...")

# ==========================================
# 4. MAIN INTERFACE
# ==========================================
st.title("🛡️ NOVA Risk Intelligence")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    if not final_df.empty:
        for r in final_df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=9, color='white', weight=0.7,
                fill=True, fill_color=r.color, fill_opacity=0.8,
                popup=f"<b>{r.name}</b><br>Risk Score: <b>{r.risk_score} / 10.0</b>"
            ).add_to(m)
    st_folium(m, width=900, height=550, key="nova_1to10")

    if 'scan_results' in st.session_state and target in st.session_state['scan_results']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Report: {target}")
        res_list = st.session_state['scan_results'][target]
        if "CLEAR" in res_list: st.success("✅ No linguistic red-flags detected in local metadata.")
        else: st.error(f"🚩 **Metadata Flags Detected:** {', '.join(res_list)}")

with col2:
    st.metric("Visible Targets", len(final_df))
    
    if not loc_sex.empty:
        st.info(f"**FBI Primary Vector:** {loc_sex.iloc[0]['key']}")
    
    if not final_df.empty:
        st.markdown("---")
        st.subheader("⚠️ Priority Watchlist")
        watchlist = final_df.sort_values('risk_score', ascending=False).head(10)
        for _, row in watchlist.iterrows():
            # Apply visual dot indicators based on score
            icon = "🔴" if row['risk_score'] >= 8.0 else ("🟠" if row['risk_score'] >= 5.0 else "🔵")
            st.write(f"{icon} **{row['name']}**")
            st.caption(f"Score: {row['risk_score']} / 10 | {row['type']}")
