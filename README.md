# Supply Chain Climate Copilot

Submission for ET AI Hackathon 2026, Problem Statement 5 (domain-specific AI agents with compliance guardrails). A multi-agent system for logistics — give it a delivery (weather + route + optionally a photo of the package), and it runs 8 agents to figure out how risky the delivery is and what should be done about it, then explains the decision in plain English.

## Overview

Most delay/disruption alerts in logistics apps just say *something's wrong* after it's already happened, with no explanation. This project reasons through the problem step by step instead — check the weather, predict the delay, check if the route is safe, check if the package looks damaged, decide what to do, and then explain why — rather than just outputting a number.

## Architecture
INGEST → DETECT_DISRUPTION → PREDICT_DELAY → OPTIMIZE_ROUTE
→ DETECT_DAMAGE → PLAN_ACTIONS → EXECUTE_ACTIONS
→ EXPLAIN → COMPUTE_IMPACT → MONITOR

This is a custom state machine rather than a framework like LangGraph, built this way to work through how state machines and multi-agent coordination actually function, rather than relying on a framework's abstractions from the start.

Each step is a separate agent:
- **Disruption Detector** — takes rainfall/wind/temperature and calculates a hazard score (weighted, rainfall matters most since that's what causes most delivery problems in India), then maps that to LOW/MEDIUM/HIGH/CRITICAL
- **Delay Predictor** — a RandomForest model (scikit-learn) trained on synthetic data, since real delivery records weren't available
- **Route Optimizer** — pulls alternative routes from OSRM and picks the best one factoring in the hazard score, not just distance
- **Damage Detector** — doesn't use a trained CV model, it's simpler than that — checks pixel color ratios (dark/brown pixels can indicate stains or water damage) and does blur detection so it can ask for a clearer photo if needed
- **Action Planner** — a rule-based decision tree that outputs things like HOLD, REROUTE, RESCHEDULE, or PROCEED
- **Action Execution** — simulates what would happen next (reroute, alerts, etc.)
- **Monitoring** — checks thresholds and looks for patterns across recent runs

The LLM (Groq, Llama 3.3) only comes in at the very end, to turn all these structured results into an explanation a non-technical person could read. It's not doing the actual decision-making — that's rule-based/ML, on purpose, so it's more predictable and auditable.

There's also an event bus and a SQLite audit log recording everything that happens, mainly for the dashboard and for debugging — they're not what actually controls the pipeline, that's the orchestrator directly.

## Setup

```bash
git clone https://github.com/ishanii214/supply-chain-climate-copilot.git
cd supply-chain-climate-copilot
pip install -r requirements.txt
streamlit run dashboard/app.py
```

For real LLM explanations instead of the template fallback, add a Groq API key in a `.env` file: `GROQ_API_KEY=your_key_here` (free at console.groq.com).

There's also `python demo/demo_flow.py` for an end-to-end run in the terminal without the dashboard.

## Data & Assumptions

Since this is a hackathon project, here's what's actually backed by real data vs. what's an assumption for the demo:

- The delay model is trained on **synthetic data** (see `data/generator.py`) — a formula mapping weather/traffic to delay hours, with some randomness added so it's not perfectly predictable. Real historical delivery data wasn't available for this.
- Weather at inference time is real though — it comes from Open-Meteo's free API.
- Route data comes from OSRM's public routing API, with a fallback to straight-line distance if that's down.
- The business impact numbers (cost saved, delay reduction %) shown in the dashboard are calculated from stated assumptions — a 40% "worse without the system" baseline, ₹1,500/hour delay cost, etc. These are editable in the Impact Model tab. The hackathon rules actually ask for exactly this kind of thing — "back-of-envelope math is fine as long as the logic holds" — so the assumptions are kept visible rather than hidden.

## Guardrails

`compliance/guardrails.py` handles three things:
1. Redacts PII (driver name/phone, customer address/email) before any processing
2. Checks required fields exist before running the pipeline
3. Sanity-checks the output — caps unrealistic delay predictions, flags low-confidence or CRITICAL results for human review

Every decision also gets logged to a local SQLite database so there's a full audit trail per delivery.

## Project structure
supply-chain-climate-copilot/
├── agents/
│   ├── orchestrator_v2.py
│   ├── data_ingestion_agent.py
│   ├── disruption_detector.py
│   ├── delay_predictor.py
│   ├── route_optimizer.py
│   ├── damage_detector.py
│   ├── action_planner.py
│   ├── action_execution_agent.py
│   └── monitoring_agent.py
├── core/
│   ├── base_agent.py
│   ├── event_bus.py
│   ├── state_manager.py
│   └── impact_model.py
├── compliance/
│   ├── guardrails.py
│   └── audit_logger.py
├── llm/
│   ├── reasoner.py
│   └── explainer.py
├── api/
│   └── server.py
├── dashboard/
│   └── app.py
├── demo/
│   └── demo_flow.py
├── data/
│   ├── generator.py
│   └── weather.py
├── tests/
│   ├── test_event_bus.py
│   ├── test_impact_model.py
│   └── test_orchestrator_v2.py
├── requirements.txt
└── README.md

## Tests

A few tests, mostly to check the trickier logic actually works:
- `test_impact_model.py` checks the impact math against hand-calculated expected values
- `test_event_bus.py` checks that if one subscriber crashes, it doesn't take down the rest of the event bus
- `test_orchestrator_v2.py` runs the whole pipeline end-to-end and checks all 10 steps complete, that low-severity deliveries correctly skip the action-execution step, and that memory persists across multiple runs

Run any of them directly, e.g. `python tests/test_orchestrator_v2.py`.

## Improvements

- The delay model only knows what it learned from a synthetic formula — real delivery data would make it far more trustworthy
- The damage detector is more of a placeholder than a real solution — checking pixel colors works for a demo, but it's guessing, not actually seeing damage the way a trained CNN would
- The audit logger opens a fresh SQLite connection on every single call — fine at this scale, not how it should be done for anything with real traffic
- The fleet-wide savings numbers in the impact tab are extrapolated from a pretty small sample, so those annual figures shouldn't be taken too seriously without a lot more real data behind them
