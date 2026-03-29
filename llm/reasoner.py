import json
import os
from datetime import datetime

from dotenv import load_dotenv

try:
    from groq import Groq
except Exception:  # pragma: no cover
    Groq = None


load_dotenv()


class LLMReasoner:
    """
    Provides LLM-polished customer-facing explanations and a structured rationale.
    If GROQ_API_KEY is missing (or Groq is unavailable), it falls back to templates.
    """

    def __init__(self):
        self.available = bool(Groq) and bool(os.getenv("GROQ_API_KEY"))
        self.client = None
        self.model = "llama-3.3-70b-versatile"
        if self.available:
            self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    def generate_rationale(self, result: dict, action_plan: dict) -> dict:
        """
        Returns:
          {
            "agent": "llm_reasoner",
            "timestamp": "...",
            "risk_summary": "...",
            "reasoning_steps": [...],
            "customer_message": "...",
            "human_review_reasons": [...]
          }
        """
        if not self.available:
            return self._fallback_rationale(result, action_plan)

        disruption = result.get("disruption", {})
        delay = result.get("delay", {})
        damage = result.get("damage", {})
        route = result.get("route", {})

        prompt = {
            "role": "user",
            "content": (
                "You are a logistics risk advisor for an Indian courier company. "
                "Generate a structured rationale for an agent decision.\n\n"
                "Output MUST be valid JSON with keys: "
                '"risk_summary"(string), "reasoning_steps"(array of strings), '
                '"customer_message"(string), "human_review_reasons"(array of strings).\n\n'
                "Keep it practical and non-technical. Mention safety and weather risk clearly.\n\n"
                "Input:\n"
                f"- Severity: {disruption.get('severity')} (confidence: {disruption.get('confidence')})\n"
                f"- Weather: rainfall={disruption.get('weather_data', {}).get('rainfall_mm')}mm, "
                f"wind={disruption.get('weather_data', {}).get('wind_kmh')}km/h, "
                f"temp={disruption.get('weather_data', {}).get('temperature_c')}C\n"
                f"- Predicted delay: {delay.get('predicted_delay_hours')}h ({delay.get('interpretation')})\n"
                f"- Route distance: {route.get('original_route', {}).get('distance_km')} km\n"
                f"- Damage: {damage.get('damage_type')} (confidence: {damage.get('confidence')}) "
                f"action={damage.get('action')}\n"
                f"- Dispatch decision: {action_plan.get('dispatch_decision')}\n"
                f"- Action steps: {action_plan.get('action_steps')}\n"
            ),
        }

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=450,
                temperature=0.2,
                messages=[prompt],
            )
            text = response.choices[0].message.content or ""
            # Try parsing as JSON; if the model wraps it, strip extra text.
            try:
                parsed = json.loads(text)
            except Exception:
                # Best-effort extraction: find first { ... last }
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    parsed = json.loads(text[start : end + 1])
                else:
                    raise ValueError("LLM did not return JSON")

            return {
                "agent": "llm_reasoner",
                "timestamp": datetime.utcnow().isoformat(),
                "risk_summary": parsed.get("risk_summary", ""),
                "reasoning_steps": parsed.get("reasoning_steps", []),
                "customer_message": parsed.get("customer_message", ""),
                "human_review_reasons": parsed.get("human_review_reasons", []),
            }
        except Exception:
            return self._fallback_rationale(result, action_plan)

    def _fallback_rationale(self, result: dict, action_plan: dict) -> dict:
        disruption = result.get("disruption", {})
        delay = result.get("delay", {})
        damage = result.get("damage", {})
        severity = disruption.get("severity", "LOW")

        risk_summary = (
            f"Risk level is {severity}. "
            f"Live weather signals suggest {severity.lower()} disruptions, "
            f"with an estimated delay of {delay.get('predicted_delay_hours', 0)} hours."
        )

        reasoning_steps = [
            "Checked live weather at the origin to estimate disruption risk.",
            "Predicted delay time using a trained model and traffic inputs.",
            "Generated a route recommendation aligned with the risk level.",
            "Evaluated package condition using the provided image/notes.",
            "Selected dispatch actions to minimize safety and customer impact.",
        ]

        if damage.get("action") == "REQUEST_IMAGE":
            human_review = ["No parcel image was provided; request image for inspection."]
        else:
            human_review = []

        return {
            "agent": "llm_reasoner",
            "timestamp": datetime.utcnow().isoformat(),
            "risk_summary": risk_summary,
            "reasoning_steps": reasoning_steps,
            "customer_message": action_plan.get("customer_message", ""),
            "human_review_reasons": human_review,
        }

    def generate_scenario_analysis(self, delivery: dict, scenario: str) -> str:
        """
        Generates a scenario-specific impact writeup for demo purposes.
        Designed to keep the UI fast and readable (no strict JSON required).
        """
        if not self.available:
            return (
                f"Scenario '{scenario}' may impact the route from {delivery.get('origin')} to {delivery.get('destination')}. "
                "For the demo, we recommend adding buffer time, monitoring live updates, and rerouting if needed."
            )

        prompt = (
            "You are a logistics risk advisor for an Indian courier company. "
            "Simulate how the following scenario could impact THIS delivery route.\n\n"
            f"Route: {delivery.get('origin', 'Unknown')} to {delivery.get('destination', 'Unknown')}\n"
            f"Scenario: {scenario}\n\n"
            "Write in plain language with the following sections:\n"
            "1) SCENARIO IMPACT (2-3 sentences)\n"
            "2) ESTIMATED DELAY (give a specific number of hours + why)\n"
            "3) IMMEDIATE ACTIONS (3 bullet points)\n"
            "4) FINANCIAL IMPACT (rough INR estimate range)\n"
            "5) RECOVERY TIMELINE (how long until normal ops resume)\n\n"
            "Mention relevant Indian highways when appropriate (e.g., NH-44, NH-48) and keep it practical."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=700,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or ""
        except Exception:
            return (
                f"Scenario '{scenario}' may impact the route from {delivery.get('origin')} to {delivery.get('destination')}. "
                "Detailed generation failed; use a conservative delay buffer and rerouting guidance."
            )

