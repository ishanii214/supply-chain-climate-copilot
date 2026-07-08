import sys
sys.path.append(".")

import streamlit as st
import pandas as pd
import json

from agents.orchestrator_v2 import OrchestratorV2
from llm.explainer import LLMExplainer
from compliance.audit_logger import AuditLogger
from core.impact_model import compute_fleet_impact, ImpactAssumptions

st.set_page_config(
    page_title="Supply Chain Climate Copilot",
    page_icon="🌦️",
    layout="wide"
)

st.title("Supply Chain Climate Copilot")
st.caption("A multi-agent pipeline for climate-aware logistics risk assessment")


@st.cache_data
def load_deliveries():
    return pd.read_csv("data/deliveries.csv")


df = load_deliveries()

# Sidebar
st.sidebar.header("Select a delivery")
delivery_ids = df["delivery_id"].tolist()
selected_id = st.sidebar.selectbox("Delivery ID", delivery_ids)
driver_notes = st.sidebar.text_input("Driver notes (optional)", "package looks intact")

st.sidebar.markdown("---")
st.sidebar.header("Multimodal inputs")
uploaded_image = st.sidebar.file_uploader(
    "Upload parcel image (optional)",
    type=["jpg", "jpeg", "png"]
)
if uploaded_image:
    st.sidebar.image(uploaded_image, caption="Parcel image uploaded", width=150)
    st.sidebar.success("Image will be analyzed by the damage detector")
    image_bytes = uploaded_image.getvalue() if hasattr(uploaded_image, "getvalue") else uploaded_image.read()
else:
    image_bytes = None

st.sidebar.markdown("---")
st.sidebar.header("Climate scenario")
scenario = st.sidebar.selectbox(
    "Inject scenario (for demo)",
    ["Real weather data", "Simulate flood", "Simulate cyclone", "Simulate heatwave"]
)
if scenario != "Real weather data":
    st.sidebar.warning(f"Scenario active: {scenario}")

scenario_overrides = {
    "Simulate flood":    {"rainfall_mm": 120, "wind_kmh": 65,  "temperature_c": 28},
    "Simulate cyclone":  {"rainfall_mm": 85,  "wind_kmh": 145, "temperature_c": 26},
    "Simulate heatwave": {"rainfall_mm": 0,   "wind_kmh": 20,  "temperature_c": 47},
}

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Live Agent Demo",
    "What-If Scenario",
    "Event Stream",
    "Impact Model",
    "Audit Trail",
    "Risk Report",
])

# Tab 1: Live Agent Demo
with tab1:
    with st.expander("About this system", expanded=False):
        st.markdown("""
**Supply Chain Climate Copilot** is a multi-agent pipeline that turns live
weather data, route information, and parcel images into a climate-risk
assessment and a recommended dispatch decision.

**Pipeline:** 8 agents — data ingestion, disruption detection, delay
prediction, route optimization, damage detection, action planning, action
execution, and monitoring — coordinated by a custom state-machine
orchestrator. An LLM (Groq / Llama 3.3) generates the plain-language
explanation at the end of the run.

**How to demo:** select a delivery, optionally upload a parcel image or
add driver notes, then click "Run pipeline" below.
        """)

    st.subheader("Run Multi-Agent Pipeline")

    delivery = df[df["delivery_id"] == selected_id].iloc[0].to_dict()

    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Route:** {delivery['origin']} → {delivery['destination']}")
        st.info(f"**Climate event in training data:** {delivery['climate_event']}")
    with col2:
        st.info(f"**Weather score (synthetic feature):** {delivery['weather_score']}/10")
        st.info(f"**Traffic index:** {delivery['traffic_index']}")

    if scenario in scenario_overrides:
        override = scenario_overrides[scenario]
        st.info(
            f"Injecting: rainfall={override['rainfall_mm']}mm, "
            f"wind={override['wind_kmh']}km/h, "
            f"temp={override['temperature_c']}°C"
        )

    if st.button("Run pipeline", type="primary"):
        orch = OrchestratorV2()
        weather_override = scenario_overrides.get(scenario) if scenario in scenario_overrides else None

        with st.spinner("Running multi-agent pipeline..."):
            result = orch.run(
                delivery,
                driver_notes=driver_notes,
                image_bytes=image_bytes,
                weather_override=weather_override,
            )

        severity_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
        emoji = severity_emoji.get(result["disruption"]["severity"], "")

        st.success("Pipeline run complete")

        # Metrics row
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Climate Severity", f"{emoji} {result['disruption']['severity']}")
            st.caption(f"Confidence: {result['disruption']['confidence']}")
        with c2:
            st.metric("Predicted Delay", f"{result['delay']['predicted_delay_hours']}h")
            st.caption(result["delay"]["interpretation"])
        with c3:
            dist = result['route']['original_route'].get('distance_km', 'N/A')
            st.metric("Route Distance", f"{dist} km")
            action = result['route']['recommendation']['action']
            st.caption(action[:50] + "..." if len(action) > 50 else action)
        with c4:
            flagged = result["damage"].get("flagged", False)
            st.metric("Package Status", result["damage"]["damage_type"].replace("_", " ").title())
            st.caption("Flagged for inspection" if flagged else "Clear")

        # Impact metrics (real, from impact_model.py)
        impact = result.get("impact", {})
        if impact:
            st.markdown("### Estimated Impact (this delivery)")
            st.caption(
                "Calculated against an assumed baseline (delays 40% worse without "
                "the system) — see the Impact Model tab for the underlying assumptions."
            )
            ic1, ic2, ic3, ic4 = st.columns(4)
            ic1.metric("Est. Delay Reduced", f"{impact.get('delay_saved_hours', 0)}h",
                       f"-{impact.get('delay_reduction_pct', 0)}%")
            ic2.metric("Est. Cost Saved", f"₹{impact.get('total_cost_saved_inr', 0):,}")
            ic3.metric("Reroute Saving", f"{impact.get('reroute_saving_hours', 0)}h")
            ic4.metric("SLA (4h window)", "Met" if impact.get("meets_sla") else "Missed")

        # Guardrail warnings (real)
        warnings = result.get("guardrail_warnings", [])
        if warnings:
            st.warning("**Guardrail alerts:**\n" + "\n".join(f"- {w}" for w in warnings))

        # Monitoring alerts (real)
        monitoring = result.get("monitoring", {})
        if monitoring.get("alerts"):
            st.markdown("### Monitoring Alerts")
            for alert in monitoring["alerts"]:
                if alert["severity"] == "CRITICAL":
                    st.error(f"[{alert['severity']}] {alert['message']}")
                elif alert["severity"] == "HIGH":
                    st.warning(f"[{alert['severity']}] {alert['message']}")
                else:
                    st.info(f"[{alert['severity']}] {alert['message']}")

        # Action plan (real)
        st.markdown("---")
        st.subheader("Recommended Action")
        dispatch_decision = result.get("action_plan", {}).get("dispatch_decision")
        if dispatch_decision:
            st.info(f"Dispatch decision: **{dispatch_decision}**")
        action_steps = result.get("action_plan", {}).get("action_steps", [])
        for step in action_steps:
            st.write(f"- {step}")

        # Executed actions (real)
        ae = result.get("action_execution", {})
        if ae and not ae.get("skipped"):
            st.markdown("### Executed Actions")
            for act in ae.get("executed_actions", []):
                with st.expander(f"{act.get('action_type', 'N/A')}"):
                    st.write(act.get("message", ""))
                    st.json(act)
        elif ae and ae.get("skipped"):
            st.info(f"Action execution skipped: {ae.get('reason', '')}")

        # Timeline checklist (real)
        timeline = result.get("action_plan", {}).get("timeline_checklist", [])
        if timeline:
            st.subheader("Timeline Checklist")
            for evt in timeline:
                st.write(f"**{evt.get('t', '')}**: {evt.get('item', '')}")

        # LLM reasoning (real)
        rationale = result.get("rationale", {})
        if rationale:
            st.markdown("### AI Reasoning")
            st.write(rationale.get("risk_summary", ""))
            if rationale.get("reasoning_steps"):
                with st.expander("Reasoning steps"):
                    for step in rationale["reasoning_steps"]:
                        st.write(f"- {step}")

        st.session_state["last_result"] = result
        st.session_state["last_events"] = result.get("event_stream", [])

# Tab 2: What-If Scenario
with tab2:
    st.subheader("What-if scenario simulator")
    st.caption("Re-run the pipeline with an injected weather scenario for this route")

    delivery = df[df["delivery_id"] == selected_id].iloc[0].to_dict()

    whatif_scenario = st.selectbox(
        "Choose a scenario to simulate",
        [
            "Major flood hits the route",
            "Severe cyclone warning issued",
            "Extreme heatwave (48°C+)",
            "Road blocked due to landslide",
            "Port congestion due to storm surge",
        ]
    )

    if st.button("Run scenario"):
        whatif_overrides = {
            "Major flood hits the route": {"rainfall_mm": 120, "wind_kmh": 65, "temperature_c": 28},
            "Severe cyclone warning issued": {"rainfall_mm": 85, "wind_kmh": 145, "temperature_c": 26},
            "Extreme heatwave (48°C+)": {"rainfall_mm": 0, "wind_kmh": 20, "temperature_c": 48},
            "Road blocked due to landslide": {"rainfall_mm": 70, "wind_kmh": 25, "temperature_c": 34},
            "Port congestion due to storm surge": {"rainfall_mm": 90, "wind_kmh": 110, "temperature_c": 30},
        }

        with st.spinner("Running pipeline with injected scenario..."):
            orch = OrchestratorV2()
            override = whatif_overrides.get(whatif_scenario)
            result = orch.run(
                delivery,
                driver_notes=driver_notes,
                image_bytes=image_bytes,
                weather_override=override,
            )

        st.markdown("### Simulation Results")
        st.caption(f"Route: {delivery['origin']} → {delivery['destination']} | Scenario: {whatif_scenario}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Severity", result["disruption"]["severity"])
        c2.metric("Delay", f"{result['delay']['predicted_delay_hours']}h")
        c3.metric("Decision", result.get("action_plan", {}).get("dispatch_decision", "N/A"))

        impact = result.get("impact", {})
        if impact:
            st.markdown("#### Estimated Impact")
            ic1, ic2 = st.columns(2)
            ic1.metric("Est. Cost Saved", f"₹{impact.get('total_cost_saved_inr', 0):,}")
            ic2.metric("Delay Reduction", f"{impact.get('delay_reduction_pct', 0)}%")

        rationale = result.get("rationale", {})
        if rationale.get("risk_summary"):
            st.markdown("#### Risk Summary")
            st.write(rationale["risk_summary"])

        st.session_state["last_result"] = result
        st.session_state["last_events"] = result.get("event_stream", [])

# Tab 3: Event Stream
with tab3:
    st.subheader("Agent Event Stream")
    st.caption("Event log from the last pipeline run (via the EventBus)")

    if "last_events" in st.session_state and st.session_state["last_events"]:
        events = st.session_state["last_events"]
        st.info(f"Showing {len(events)} events from the last pipeline run")

        for evt in events:
            with st.expander(
                f"{evt['event_type']} ← {evt['source_agent']} ({evt['timestamp'][:19]})"
            ):
                st.write(f"**Event ID:** {evt.get('event_id', 'N/A')}")
                st.write(f"**Data keys:** {', '.join(evt.get('data_keys', []))}")

        st.markdown("### Pipeline Flow")
        st.caption(
            "The orchestrator runs these steps in order. The EventBus records "
            "what happened at each step for this audit trail — it does not "
            "control the execution order itself; that's handled by the "
            "orchestrator's state machine."
        )
        st.code(
            "INGEST -> DETECT_DISRUPTION -> PREDICT_DELAY -> OPTIMIZE_ROUTE\n"
            "       -> DETECT_DAMAGE -> PLAN_ACTIONS -> EXECUTE_ACTIONS\n"
            "       -> EXPLAIN -> COMPUTE_IMPACT -> MONITOR",
            language="text"
        )
    else:
        st.info("Run the pipeline in the Live Demo tab first to see the event stream.")

# Tab 4: Impact Model
with tab4:
    st.subheader("Business Impact Model")
    st.caption(
        "These figures are projections based on stated assumptions "
        "(see below), not measurements from real fleet data."
    )

    if "last_result" in st.session_state:
        result = st.session_state["last_result"]
        impact = result.get("impact", {})

        st.markdown("### Per-Delivery Impact")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Baseline Delay (assumed)", f"{impact.get('baseline_delay_hours', 0)}h",
                   help="Assumed delay without the system — baseline_delay_multiplier=1.40")
        c2.metric("System Delay", f"{impact.get('system_delay_hours', 0)}h")
        c3.metric("Delay Saved", f"{impact.get('delay_saved_hours', 0)}h",
                   f"-{impact.get('delay_reduction_pct', 0)}%")
        c4.metric("Cost Saved (est.)", f"₹{impact.get('total_cost_saved_inr', 0):,}")

        st.markdown("---")
        st.markdown("### Fleet-Wide Extrapolation")
        st.caption(
            "Extrapolated from this single delivery's result, scaled up to the "
            "deliveries-per-day figure below. This is a projection, not a "
            "measured result across a real fleet."
        )

        deliveries_per_day = st.slider("Deliveries per day (assumed fleet size)", 50, 2000, 500)
        assumptions = ImpactAssumptions(deliveries_per_day=deliveries_per_day)
        fleet = compute_fleet_impact([impact] * 10, assumptions)

        fc1, fc2, fc3, fc4 = st.columns(4)
        fc1.metric("Avg Delay Reduction", f"{fleet['avg_delay_reduction_pct']}%")
        fc2.metric("SLA Compliance", f"{fleet['sla_compliance_pct']}%")
        fc3.metric("Daily Savings (est.)", f"₹{fleet['daily_cost_saved_inr']:,}")
        fc4.metric("Annual Savings (est.)", f"₹{fleet['annual_cost_saved_inr']:,}")

        st.markdown("---")
        st.markdown("### Assumptions Used")
        st.caption("All figures above are derived from these configurable assumptions:")
        st.json(fleet["assumptions"])

        st.markdown("### Formulas")
        st.latex(r"\text{Baseline Delay} = \text{Predicted Delay} \times \text{baseline\_delay\_multiplier}")
        st.latex(r"\text{Delay Saved} = \text{Baseline Delay} - \text{System Delay}")
        st.latex(r"\text{Cost Saved} = \text{Delay Saved (hours)} \times \text{cost\_per\_delay\_hour}")
        st.latex(r"\text{SLA Met} = \text{System Delay} \leq \text{sla\_window\_hours}")

        st.markdown("### Data & Model Notes")
        st.info(
            "The delay prediction model (RandomForest) is trained on synthetic "
            "delivery data generated for this project — weather and traffic "
            "scores mapped to delay hours using a hand-written formula, not "
            "real historical delivery records. Weather data at inference time "
            "comes from the Open-Meteo API (free, no key required). Route "
            "alternatives come from the OSRM public routing API, with a "
            "straight-line-distance fallback if that API is unavailable."
        )
    else:
        st.info("Run the pipeline in the Live Demo tab first to see impact metrics.")

# Tab 5: Audit Trail
with tab5:
    st.subheader("Audit Trail")
    st.caption("Every agent decision is logged to a local SQLite database (data/audit.db)")

    audit = AuditLogger()
    logs = audit.get_all()

    if logs:
        filter_id = st.checkbox("Filter by selected delivery ID")
        if filter_id:
            logs = [l for l in logs if l["delivery_id"] == selected_id]

        st.caption(f"Showing {min(20, len(logs))} most recent entries")
        for log in logs[:20]:
            with st.expander(
                f"{log['agent']} — {log['delivery_id']} — {log['timestamp'][:19]}"
            ):
                st.json(log["details"])
    else:
        st.info("No audit logs yet. Run the pipeline from the Live Demo tab first.")

    st.markdown("---")
    st.subheader("Input/Output Guardrails")
    st.caption("Implemented in compliance/guardrails.py")
    st.write("- **PII redaction:** driver name, driver phone, customer address, and "
              "customer email are replaced with `[REDACTED]` before processing.")
    st.write("- **Input validation:** required fields (delivery_id, coordinates) "
              "must be present, or the pipeline raises an error before running.")
    st.write("- **Output sanity checks:** delay predictions are capped at 168 hours "
              "(1 week); low-confidence disruption assessments and CRITICAL "
              "severity results are flagged for human review.")

# Tab 6: Risk Report
with tab6:
    st.subheader("AI Risk Report")

    if "last_result" in st.session_state:
        result = st.session_state["last_result"]

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Delivery:** {result.get('origin', '')} → {result.get('destination', '')}")
            st.markdown(f"**Overall risk:** {result['overall_risk']}")
        with col2:
            st.markdown(f"**Completed at:** {(result.get('completed_at') or '')[:19]}")
            st.markdown(f"**Delay predicted:** {result['delay']['predicted_delay_hours']} hours")

        st.markdown("---")

        explainer = LLMExplainer()

        st.markdown("### Why did this delay happen?")
        st.write(explainer.explain_why_delay(result))

        st.markdown("### What action was taken?")
        st.write(explainer.explain_what_action(result))

        st.markdown("### What could happen next?")
        st.write(explainer.explain_what_next(result))

        st.markdown("---")
        with st.expander("View raw agent outputs"):
            st.json(result)

        meta = result.get("pipeline_metadata", {})
        if meta:
            with st.expander("Pipeline Metadata"):
                st.write(f"**Version:** {meta.get('version')}")
                st.write(f"**Steps completed:** {', '.join(meta.get('steps_completed', []))}")
                st.write(f"**Errors:** {len(meta.get('errors', []))}")
    else:
        st.info("Run the pipeline in the Live Demo tab first, then come here for the report.")