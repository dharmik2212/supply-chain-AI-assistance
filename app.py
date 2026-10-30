import os
import sys
from pathlib import Path
import streamlit as st
import pandas as pd
import altair as alt

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.graph import create_agent, stream_agent_workflow
from agent.database import execute_query

# Page Configuration
st.set_page_config(
    page_title="Supply Chain AI Assistant",
    layout="wide",
    initial_sidebar_state="expanded"
)

@st.cache_resource
def load_agent():
    return create_agent()

# App Header
st.title("Supply Chain & Fleet AI Operations Assistant")

# Sidebar
with st.sidebar:
    st.subheader("Example Queries")
    sample_queries = [
        "What is the average ETA variation and fuel consumption rate?",
        "Show me top 5 routes with highest traffic congestion and delay",
        "What is the average loading/unloading time when equipment is available?",
        "How does traffic congestion level affect order fulfillment status?",
        "What are best practices to minimize logistics dwell times?"
    ]
    
    for q in sample_queries:
        if st.button(q, key=f"btn_{q}"):
            st.session_state["user_input_trigger"] = q

# Tabs for Chat vs Analytics
tab_chat, tab_analytics = st.tabs(["AI Logistics Agent", "Fleet Analytics & Telemetry"])

# Session State for Chat History
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {
            "role": "assistant",
            "content": "Hello! I am your AI Supply Chain & Fleet Operations Assistant. Ask me anything about fleet delays, fuel metrics, inventory, equipment availability, or logistics operations.",
            "sql": None,
            "data": None
        }
    ]

with tab_chat:
    # Display message history
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sql"):
                with st.expander("View Executed SQL & Database Output"):
                    st.code(msg["sql"], language="sql")
                    if msg.get("data"):
                        st.dataframe(pd.DataFrame(msg["data"]))

    # Handle triggers from sidebar buttons
    preset_input = st.session_state.pop("user_input_trigger", None)
    user_prompt = st.chat_input("Ask a supply chain or fleet question...") or preset_input

    if user_prompt:
        st.session_state["messages"].append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            try:
                events = stream_agent_workflow(user_prompt)
                
                # First event contains query metadata & executed SQL
                meta_event = next(events)
                sql_query = meta_event.get("sql")
                sql_result = meta_event.get("data")
                sql_error = meta_event.get("error")
                
                if sql_query:
                    with st.expander("View Executed SQL & Database Output"):
                        st.code(sql_query, language="sql")
                        if sql_result:
                            st.dataframe(pd.DataFrame(sql_result))
                        elif sql_error:
                            st.caption(f"Query notice: {sql_error}")

                # Stream the synthesized answer token-by-token
                def token_stream():
                    for ev in events:
                        if ev["type"] == "chunk":
                            yield ev["content"]

                answer = st.write_stream(token_stream)
                
                st.session_state["messages"].append({
                    "role": "assistant",
                    "content": answer,
                    "sql": sql_query,
                    "data": sql_result
                })
            except Exception as e:
                st.error(f"Error executing agent workflow: {e}")

with tab_analytics:
    st.subheader("Interactive Fleet Telemetry Visualizer")
    
    # Interactive Filters Container
    with st.container():
        f1, f2, f3, f4 = st.columns([1.5, 1.5, 1.2, 1.2])
        
        with f1:
            selected_shift = st.selectbox(
                "Operational Shift",
                options=["All Shifts", "Shift 1 (06:00 - 14:00)", "Shift 2 (14:00 - 22:00)", "Shift 3 (22:00 - 06:00)"],
                index=0
            )
            
        with f2:
            traffic_range = st.slider(
                "Traffic Congestion Index",
                min_value=0.0,
                max_value=10.0,
                value=(0.0, 10.0),
                step=0.5
            )
            
        with f3:
            equip_filter = st.selectbox(
                "Equipment Status",
                options=["All", "Available (1)", "Unavailable (0)"],
                index=0
            )
            
        with f4:
            sample_limit = st.select_slider(
                "Record Sample Size",
                options=[100, 250, 500, 1000, 2000],
                value=500
            )

    # Build Dynamic WHERE Clause
    where_conditions = [
        f"TRF_CNG_LVL BETWEEN {traffic_range[0]} AND {traffic_range[1]}"
    ]
    
    if selected_shift == "Shift 1 (06:00 - 14:00)":
        where_conditions.append("CAST(SUBSTR(TS_UTC, 12, 2) AS INT) BETWEEN 6 AND 13")
    elif selected_shift == "Shift 2 (14:00 - 22:00)":
        where_conditions.append("CAST(SUBSTR(TS_UTC, 12, 2) AS INT) BETWEEN 14 AND 21")
    elif selected_shift == "Shift 3 (22:00 - 06:00)":
        where_conditions.append("(CAST(SUBSTR(TS_UTC, 12, 2) AS INT) >= 22 OR CAST(SUBSTR(TS_UTC, 12, 2) AS INT) < 6)")
        
    if equip_filter == "Available (1)":
        where_conditions.append("EQ_AVAIL_IND = 1")
    elif equip_filter == "Unavailable (0)":
        where_conditions.append("EQ_AVAIL_IND = 0")
        
    where_clause_str = " AND ".join(where_conditions)
    
    analytics_query = f"""
        SELECT TOP {sample_limit} 
            V_LAT, V_LON, FUEL_CONS_RATE, ETA_VAR_HRS, TRF_CNG_LVL, LOAD_UNLOAD_TM, ORD_FULFILL_STS
        FROM TBL_SC_FLEET_HIST_RAW
        WHERE {where_clause_str}
    """
    
    sample_df_res = execute_query(analytics_query)
    
    if sample_df_res.get("success") and sample_df_res.get("data"):
        df_viz = pd.DataFrame(sample_df_res["data"])
        
        # Filtered Metrics Row
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Filtered Records", f"{len(df_viz):,}")
        m2.metric("Avg ETA Delay", f"{df_viz['ETA_VAR_HRS'].mean():.2f} hrs")
        m3.metric("Avg Fuel Rate", f"{df_viz['FUEL_CONS_RATE'].mean():.2f} L/hr")
        m4.metric("Avg Loading Time", f"{df_viz['LOAD_UNLOAD_TM'].mean():.2f} hrs")
        
        st.write("")
        
        c1, c2 = st.columns(2)
        with c1:
            st.write("#### Traffic Congestion vs ETA Delay (Hours)")
            scatter = alt.Chart(df_viz).mark_circle(size=60, opacity=0.7).encode(
                x=alt.X('TRF_CNG_LVL:Q', title='Traffic Congestion Level'),
                y=alt.Y('ETA_VAR_HRS:Q', title='ETA Variation (Hours)'),
                color=alt.Color('FUEL_CONS_RATE:Q', scale=alt.Scale(scheme='redyellowblue'), title='Fuel Rate'),
                tooltip=['TRF_CNG_LVL', 'ETA_VAR_HRS', 'FUEL_CONS_RATE']
            ).properties(height=350).interactive()
            st.altair_chart(scatter, width="stretch")
            
        with c2:
            st.write("#### Loading / Unloading Time Distribution")
            hist = alt.Chart(df_viz).mark_bar(color='#1E88E5').encode(
                x=alt.X('LOAD_UNLOAD_TM:Q', bin=alt.Bin(maxbins=20), title='Loading Time (hrs)'),
                y=alt.Y('count()', title='Trip Count')
            ).properties(height=350)
            st.altair_chart(hist, width="stretch")
            
        st.write("#### Fleet Active GPS Positions (Filtered Sample)")
        map_df = df_viz[['V_LAT', 'V_LON']].dropna().rename(columns={'V_LAT': 'latitude', 'V_LON': 'longitude'})
        st.map(map_df, zoom=2)
    else:
        st.info("No telemetry records match the selected filters. Please adjust the filter criteria.")
