"""Tests for the Impact Model calculations."""

import sys
sys.path.append(".")

from core.impact_model import (
    compute_single_delivery_impact,
    compute_fleet_impact,
    ImpactAssumptions,
)


def test_single_delivery_basic():
    """Basic delay reduction calculation."""
    result = compute_single_delivery_impact(
        predicted_delay_hours=6.0,
        severity="HIGH",
        damage_flagged=False,
        dispatch_decision="REROUTE_AND_BUFFER",
    )
    # With rerouting: system_delay = 6.0 - (6.0 * 0.30) = 4.2
    # baseline = 6.0 * 1.40 = 8.4
    # saved = 8.4 - 4.2 = 4.2
    assert result["baseline_delay_hours"] == 8.4
    assert result["system_delay_hours"] == 4.2
    assert result["delay_saved_hours"] == 4.2
    assert result["delay_reduction_pct"] == 50.0
    assert result["meets_sla"] is False  # 4.2 > 4.0
    print("✓ test_single_delivery_basic passed")


def test_single_delivery_with_damage():
    """Damage detection adds cost savings."""
    result = compute_single_delivery_impact(
        predicted_delay_hours=3.0,
        severity="MEDIUM",
        damage_flagged=True,
        dispatch_decision="MONITOR_AND_CHECKPOINT",
    )
    assert result["damage_cost_saved_inr"] > 0
    assert result["total_cost_saved_inr"] > result["delay_cost_saved_inr"]
    print("✓ test_single_delivery_with_damage passed")


def test_single_delivery_meets_sla():
    """Low delay should meet SLA."""
    result = compute_single_delivery_impact(
        predicted_delay_hours=2.0,
        severity="LOW",
        damage_flagged=False,
        dispatch_decision="PROCEED",
    )
    assert result["meets_sla"] is True
    print("✓ test_single_delivery_meets_sla passed")


def test_fleet_impact():
    """Fleet-wide extrapolation works correctly."""
    single = compute_single_delivery_impact(
        predicted_delay_hours=6.0,
        severity="HIGH",
        damage_flagged=True,
        dispatch_decision="REROUTE_AND_BUFFER",
    )
    fleet = compute_fleet_impact([single] * 10)

    assert fleet["sample_size"] == 10
    assert fleet["avg_delay_reduction_pct"] > 0
    assert fleet["daily_cost_saved_inr"] > 0
    assert fleet["annual_cost_saved_inr"] > fleet["monthly_cost_saved_inr"]
    assert "assumptions" in fleet
    print("✓ test_fleet_impact passed")


def test_custom_assumptions():
    """Custom assumptions override defaults."""
    custom = ImpactAssumptions(
        cost_per_delay_hour_inr=3000,
        deliveries_per_day=1000,
    )
    result = compute_single_delivery_impact(
        predicted_delay_hours=5.0,
        severity="HIGH",
        damage_flagged=False,
        dispatch_decision="PROCEED",
        assumptions=custom,
    )
    # Higher cost per hour = higher savings
    default = compute_single_delivery_impact(
        predicted_delay_hours=5.0,
        severity="HIGH",
        damage_flagged=False,
        dispatch_decision="PROCEED",
    )
    assert result["delay_cost_saved_inr"] > default["delay_cost_saved_inr"]
    print("✓ test_custom_assumptions passed")


if __name__ == "__main__":
    test_single_delivery_basic()
    test_single_delivery_with_damage()
    test_single_delivery_meets_sla()
    test_fleet_impact()
    test_custom_assumptions()
    print("\n✅ All impact model tests passed!")
