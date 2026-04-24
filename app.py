import os
import numpy as np
import pandas as pd
import streamlit as st
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
from sklearn.cluster import DBSCAN

# =========================================================
# PAGE SETUP
# =========================================================
st.set_page_config(
    page_title="OSINT Intelligence Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

LAT = 38.85
LNG = -77.30
CACHE_FILE = "osint_cache.csv"

st.markdown(
    """
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 2rem; }
        [data-testid="stMetricValue"] { font-size: 1.8rem; }
        .small-note { font-size: 0.86rem; opacity: 0.8; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧠 OSINT Intelligence Dashboard")
st.caption("Instant-loading, offline-first analytics view with filters, clustering, hotspots, and map layers.")

# =========================================================
# DATA HELPERS
# =========================================================
REQUIRED_COLS = ["name", "lat", "lng", "type", "city", "street", "source"]

CATEGORY_WEIGHTS = {
    "hotel": 2.0,
    "motel": 2.2,
    "bar": 1.3,
    "nightclub": 1.8,
    "restaurant": 0.8,
    "cafe": 0.6,
    "spa": 2.4,
    "massage": 2.6,
    "shop": 0.4,
}

def generate_demo_data(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)

    clusters = [
        (LAT + 0.020, LNG + 0.010, ["hotel", "motel", "bar", "nightclub"]),
        (LAT - 0.015, LNG - 0.018, ["spa", "massage", "hotel"]),
        (LAT + 0.030, LNG - 0.020, ["restaurant", "cafe", "bar"]),
    ]

    rows = []
    for i in range(n):
        center_lat, center_lng, kinds = clusters[i % len(clusters)]
        kind = rng.choice(kinds + ["restaurant", "cafe", "hotel", "bar", "spa", "massage"])
        rows.append(
            {
                "name": f"Demo Location {i+1}",
                "lat": center_lat + rng.normal(0, 0.006),
                "lng": center_lng + rng.normal(0, 0.006),
                "type": kind,
                "city": "Demo Region",
                "street": "Demo Area",
                "source": "Synthetic Demo Dataset",
            }
        )

    df = pd.DataFrame(rows)
    return df

def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in REQUIRED_COLS:
        if col not in df.columns:
            if col in {"lat", "lng"}:
                df[col] = np.nan
            else:
                df[col] = "Unknown"

    df["name"] = df["name"].fillna("Unnamed Location").astype(str)
    df["type"] = df["type"].fillna("unknown").astype(str).str.lower()
    df["city"] = df["city"].fillna("Unknown").astype(str)
    df["street"] = df["street"].fillna("Unknown").astype(str)
    df["source"] = df["source"].fillna("Unknown").astype(str)

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
    df = df.dropna(subset=["lat", "lng"]).reset_index(drop=True)

    return df

def load_cached_data() -> pd.DataFrame | None:
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE)
            df = normalize_df(df)
            if len(df) > 0:
                return df
        except Exception:
            return None
    return None

def save_cache(df: pd.DataFrame) -> None:
    try:
        df.to_csv(CACHE_FILE, index=False)
    except Exception:
        pass

def load_initial_data(uploaded_file) -> tuple[pd.DataFrame, str]:
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            df = normalize_df(df)
            if len(df) > 0:
                return df, "uploaded CSV"
        except Exception:
            pass

    cached = load_cached_data()
    if cached is not None:
        return cached, "local cached dataset"

    demo = generate_demo_data()
    save_cache(demo)
    return demo, "synthetic demo dataset"

def build_cluster_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if len(df) < 3:
        df["cluster"] = -1
        return df

    coords = df[["lat", "lng"]].to_numpy()
    db = DBSCAN(eps=0.012, min_samples=3).fit(coords)
    df["cluster"] = db.labels_
    return df

def local_neighbor_counts(df: pd.DataFrame, radius: float = 0.015) -> list[int]:
    counts = []
    for row in df.itertuples():
        nearby = (
            (df["lat"] - row.lat).abs() < radius
        ) & (
            (df["lng"] - row.lng).abs() < radius
        )
        counts.append(int(nearby.sum()))
    return counts

def compute_risk_model(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df = build_cluster_labels(df)

    local_counts = local_neighbor_counts(df, radius=0.015)
    baseline_count = float(np.median(local_counts)) if local_counts else 0.0

    risks = []
    signals = []
    confidence = []

    for idx, row in df.iterrows():
        t = str(row["type"]).lower()

        base = CATEGORY_WEIGHTS.get(t, 0.3)

        nearby_mask = (
            (df["lat"] - row["lat"]).abs() < 0.015
        ) & (
            (df["lng"] - row["lng"]).abs() < 0.015
        )
        nearby = df.loc[nearby_mask]
        nearby_types = set(nearby["type"].astype(str).str.lower())

        density = min(local_counts[idx] / 10.0, 3.0)

        combo_bonus = 0.0
        signal_bits = []

        if {"hotel", "motel"} & nearby_types and {"bar", "nightclub"} & nearby_types:
            combo_bonus += 2.0
            signal_bits.append("hotel+nightlife")

        if {"hotel", "motel"} & nearby_types and {"spa", "massage"} & nearby_types:
            combo_bonus += 1.4
            signal_bits.append("lodging+wellness")

        if {"bar", "nightclub"} & nearby_types and {"spa", "massage"} & nearby_types:
            combo_bonus += 0.9
            signal_bits.append("nightlife+wellness")

        baseline_dev = max(0.0, local_counts[idx] - baseline_count) / 8.0

        cluster_size = 0
        if int(row["cluster"]) != -1:
            cluster_size = int((df["cluster"] == row["cluster"]).sum())

        cluster_bonus = min(max(cluster_size - 4, 0) * 0.18, 2.0)
        if cluster_size >= 5:
            signal_bits.append(f"cluster={cluster_size}")

        score = base + density + combo_bonus + baseline_dev + cluster_bonus

        if local_counts[idx] < 3:
            score *= 0.7
            signal_bits.append("isolated")

        risks.append(float(score))
        signals.append(", ".join(signal_bits) if signal_bits else "none")
        confidence.append(round(min(1.0, 0.35 + 0.1 * local_counts[idx]), 2))

    df["risk"] = risks
    df["confidence"] = confidence
    df["signals"] = signals

    def topic_map(t: str) -> str:
        if t in {"hotel", "motel"}:
            return "Lodging"
        if t in {"bar", "nightclub"}:
            return "Nightlife"
        if t in {"spa", "massage"}:
            return "Wellness"
        if t in {"restaurant", "cafe"}:
            return "Food / Drink"
        return "Other"

    df["topic"] = df["type"].apply(topic_map)
    df["neighbor_count"] = local_counts

    return df

def summarize_hotspots(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["cluster", "count", "avg_risk", "top_type", "center_lat", "center_lng"])

    clusters = []
    for cluster_id, group in df[df["cluster"] != -1].groupby("cluster"):
        top_type = group["type"].mode().iloc[0] if not group["type"].mode().empty else "unknown"
        clusters.append(
            {
                "cluster": int(cluster_id),
                "count": int(len(group)),
                "avg_risk": round(float(group["risk"].mean()), 2),
                "top_type": top_type,
                "center_lat": round(float(group["lat"].mean()), 6),
                "center_lng": round(float(group["lng"].mean()), 6),
            }
        )

    if not clusters:
        return pd.DataFrame(columns=["cluster", "count", "avg_risk", "top_type", "center_lat", "center_lng"])

    out = pd.DataFrame(clusters).sort_values(["count", "avg_risk"], ascending=[False, False])
    return out.reset_index(drop=True)

# =========================================================
# LOAD DATA
# =========================================================
uploaded = st.sidebar.file_uploader("Upload CSV with columns: name, lat, lng, type, city, street, source", type=["csv"])
df_raw, data_source = load_initial_data(uploaded)

# Save uploaded file to local cache if it was uploaded
if uploaded is not None:
    save_cache(df_raw)

df_raw = normalize_df(df_raw)
df = compute_risk_model(df_raw)

# =========================================================
# SIDEBAR CONTROLS
# =========================================================
st.sidebar.header("🎛️ Controls")
st.sidebar.caption("This version does not call live APIs at runtime, so it loads instantly.")

types = sorted(df["type"].dropna().astype(str).unique().tolist())
topics = sorted(df["topic"].dropna().astype(str).unique().tolist())

selected_types = st.sidebar.multiselect("Category", options=types, default=types)
selected_topics = st.sidebar.multiselect("Topic", options=topics, default=topics)

risk_min, risk_max = float(df["risk"].min()), float(df["risk"].max())
risk_range = st.sidebar.slider("Risk range", min_value=0.0, max_value=max(10.0, risk_max), value=(0.0, max(10.0, risk_max)))

cluster_choices = sorted([int(x) for x in df["cluster"].dropna().unique().tolist() if int(x) != -1])
cluster_filter = st.sidebar.multiselect("Cluster", options=cluster_choices, default=cluster_choices)

search_text = st.sidebar.text_input("Search name / city / street", value="")
show_heat = st.sidebar.checkbox("Heatmap", value=True)
show_points = st.sidebar.checkbox("Points", value=True)
show_signals = st.sidebar.checkbox("Show signals in table", value=False)

# =========================================================
# FILTER DATA
# =========================================================
filtered = df[
    df["type"].isin(selected_types)
    & df["topic"].isin(selected_topics)
    & (df["risk"] >= risk_range[0])
    & (df["risk"] <= risk_range[1])
].copy()

if cluster_choices:
    filtered = filtered[
        (filtered["cluster"].isin(cluster_filter)) | (filtered["cluster"] == -1)
    ].copy()

if search_text.strip():
    q = search_text.strip().lower()
    filtered = filtered[
        filtered["name"].str.lower().str.contains(q, na=False)
        | filtered["city"].str.lower().str.contains(q, na=False)
        | filtered["street"].str.lower().str.contains(q, na=False)
    ].copy()

# =========================================================
# TOP METRICS
# =========================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total points", len(df))
c2.metric("Filtered points", len(filtered))
c3.metric("Avg risk", round(float(df["risk"].mean()), 2) if len(df) else 0.0)
c4.metric("Hot clusters", int((df["cluster"] != -1).sum()) if len(df) else 0)

st.caption(f"Data source: {data_source}")

st.divider()

# =========================================================
# TABS
# =========================================================
tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Map", "Hotspots", "Data"])

with tab1:
    left, right = st.columns([1, 1])

    with left:
        st.subheader("Category mix")
        type_counts = filtered["type"].value_counts()
        if len(type_counts) > 0:
            st.bar_chart(type_counts)

        st.subheader("Topic mix")
        topic_counts = filtered["topic"].value_counts()
        if len(topic_counts) > 0:
            st.bar_chart(topic_counts)

    with right:
        st.subheader("Risk distribution")
        risk_bins = pd.cut(filtered["risk"], bins=8) if len(filtered) else pd.Series(dtype="category")
        if len(filtered):
            st.bar_chart(risk_bins.value_counts().sort_index())

        st.subheader("Data quality")
        quality = pd.DataFrame(
            {
                "metric": ["rows", "clusters", "missing types", "source"],
                "value": [
                    len(df),
                    int((df["cluster"] != -1).sum()),
                    int(df["type"].isna().sum()),
                    data_source,
                ],
            }
        )
        st.dataframe(quality, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("Spatial view")

    center_lat = float(filtered["lat"].mean()) if len(filtered) else LAT
    center_lng = float(filtered["lng"].mean()) if len(filtered) else LNG

    m = folium.Map(location=[center_lat, center_lng], zoom_start=11, control_scale=True)

    if show_heat and len(filtered):
        heat_data = [[r.lat, r.lng, float(r.risk)] for r in filtered.itertuples()]
        HeatMap(heat_data, radius=18, blur=15, min_opacity=0.25).add_to(m)

    if show_points and len(filtered):
        for r in filtered.itertuples():
            popup_html = f"""
            <b>{r.name}</b><br>
            Type: {r.type}<br>
            Topic: {r.topic}<br>
            Risk: {r.risk:.2f}<br>
            Confidence: {r.confidence:.2f}<br>
            Cluster: {r.cluster}<br>
            Neighbors: {r.neighbor_count}<br>
            Signals: {r.signals}<br>
            City: {r.city}<br>
            Street: {r.street}<br>
            Source: {r.source}
            """
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=5,
                popup=folium.Popup(popup_html, max_width=340),
                fill=True,
                fill_opacity=0.8,
            ).add_to(m)

    st_folium(m, width=1100, height=680, key="osint_map")

with tab3:
    st.subheader("Hotspot ranking")

    hotspots = summarize_hotspots(filtered)
    if hotspots.empty:
        st.info("No clusters found in the current filter set.")
    else:
        st.dataframe(hotspots, use_container_width=True, hide_index=True)

        top_hotspots = hotspots.head(10).copy()
        if len(top_hotspots):
            st.bar_chart(top_hotspots.set_index("cluster")["avg_risk"])

    st.divider()
    st.subheader("Highest risk points")
    top_points = filtered.sort_values("risk", ascending=False).head(15)
    if len(top_points):
        st.dataframe(
            top_points[
                ["name", "type", "topic", "risk", "confidence", "cluster", "neighbor_count", "signals", "city", "street"]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No points match the selected filters.")

with tab4:
    st.subheader("Filtered data table")

    cols = ["name", "type", "topic", "risk", "confidence", "cluster", "neighbor_count", "city", "street", "source"]
    if show_signals:
        cols.insert(8, "signals")

    st.dataframe(
        filtered[cols],
        use_container_width=True,
        height=600,
        hide_index=True,
    )

    csv_bytes = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered CSV",
        data=csv_bytes,
        file_name="osint_filtered.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "Offline-first OSINT dashboard: local cache + upload support + clustering + hotspots + risk scoring. "
    "No live Overpass request is made at runtime, which prevents the white-screen loading issue."
)
