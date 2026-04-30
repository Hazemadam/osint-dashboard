import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
from serpapi import GoogleSearch

# ================================
# 1. DATA LOADING (Same as before)
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'lon': 'lng', 'latitude': 'lat'})
        return poi, census
    except Exception as e:
        st.error(f"Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. THE SERPAPI "WITNESS" ENGINE
# ================================
def get_sketchy_intel(business_name, location_query, api_key):
    """
    Step 1: Find the Data ID
    Step 2: Pull Reviews
    Step 3: Scan for Keywords
    """
    try:
        # Search for the business to get the ID
        search = GoogleSearch({
            "engine": "google_maps",
            "q": f"{business_name} {location_query}",
            "api_key": api_key
        })
        results = search.get_dict()
        
        # Grab the first result's ID
        place = results.get("local_results", [{}])[0]
        data_id = place.get("data_id")
        
        if not data_id:
            return "No Digital ID found.", []

        # Now get the actual reviews
        review_search = GoogleSearch({
            "engine": "google_maps_reviews",
            "data_id": data_id,
            "api_key": api_key
        })
        rev_results = review_search.get_dict()
        reviews = rev_results.get("reviews", [])

        # The "Sketchy" Filter
        RED_FLAGS = ['scam', 'police', 'illegal', 'sketchy', 'trap', 'assault', 'dangerous', 'hidden fee']
        found_alerts = []
        
        for r in reviews:
            text = r.get("snippet", "").lower()
            for flag in RED_FLAGS:
                if flag in text:
                    found_alerts.append(f"Reviewer said: '...{flag}...'")
        
        return "Scan Complete", list(set(found_alerts))
    except Exception as e:
        return f"Scan Failed: {e}", []

# ================================
# 3. SIDEBAR & SCANNER UI
# ================================
st.sidebar.title("🔍 Intelligence Control")
# Using your key as a default for you, but masked in the UI
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    # (Existing scoring logic would go here)
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🕵️ Deep Scan Target")
    target = st.sidebar.selectbox("Select a Business to Interrogate", poi_df['name'].unique())
    
    if st.sidebar.button("Run OSINT Review Scan"):
        with st.spinner(f"Interrogating Google for {target}..."):
            status, alerts = get_sketchy_intel(target, "Northern Virginia", api_key)
            if alerts:
                st.sidebar.error(f"🚩 ALERT: {len(alerts)} RED FLAGS FOUND")
                for a in alerts:
                    st.sidebar.write(f"- {a}")
            else:
                st.sidebar.success("Clear: No red flag keywords found in recent reviews.")

# ================================
# 4. MAP DISPLAY (Simplified for focus)
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

for r in poi_df.head(100).itertuples():
    folium.CircleMarker(
        location=[r.lat, r.lng],
        radius=5, color="red" if r.type in ['motel', 'massage'] else "blue",
        fill=True, popup=r.name
    ).add_to(m)

st_folium(m, width=900, height=500)
