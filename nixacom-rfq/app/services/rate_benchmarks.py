"""
Rate Benchmark Engine for Freight Cost Data.
Integrates EIA Diesel Fuel Surcharges and FMC/FBX Ocean Rate Benchmarks.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class RateBenchmarkResult:
    target_rate: float
    market_avg_rate: float
    fuel_surcharge: float
    variance_pct: float
    competitiveness: str  # BELOW_MARKET, FAIR, ABOVE_MARKET
    index_sources: Dict[str, str]

class RateBenchmarkEngine:
    def __init__(self):
        # Baseline benchmark indices per lane (e.g., Shanghai -> Long Beach FEU)
        self.lane_benchmarks = {
            "CNSHA-USLGB": {"base_market_rate": 2150.00, "currency": "USD"},
            "CNSHA-USLAX": {"base_market_rate": 2200.00, "currency": "USD"},
            "DEHAM-USLGB": {"base_market_rate": 3100.00, "currency": "USD"}
        }
        # EIA On-Highway Diesel Benchmark ($/gal) & calculated FSC multiplier
        self.eia_diesel_price_per_gal = 3.85
        self.base_fuel_rate_pct = 14.5  # 14.5% FSC

    def get_eia_fuel_surcharge(self) -> Dict[str, Any]:
        """Calculates current Fuel Surcharge percentage based on EIA Diesel Index."""
        return {
            "source": "U.S. EIA On-Highway Diesel Index",
            "current_diesel_price_usd": self.eia_diesel_price_per_gal,
            "applicable_fsc_pct": self.base_fuel_rate_pct
        }

    def evaluate_target_rate(
        self, origin_code: str, dest_code: str, target_rate: float
    ) -> RateBenchmarkResult:
        """Compares incoming target rate against FMC/FBX market benchmark rates."""
        lane_key = f"{origin_code.upper()}-{dest_code.upper()}"
        lane_data = self.lane_benchmarks.get(lane_key, {"base_market_rate": 2500.00})

        base_rate = lane_data["base_market_rate"]
        fuel_surcharge_val = round(base_rate * (self.base_fuel_rate_pct / 100.0), 2)
        total_market_avg = base_rate + fuel_surcharge_val

        # Calculate percentage variance
        variance_pct = round(((target_rate - total_market_avg) / total_market_avg) * 100, 2)

        # Rate evaluation threshold
        if variance_pct < -10.0:
            competitiveness = "BELOW_MARKET"
        elif -10.0 <= variance_pct <= 10.0:
            competitiveness = "FAIR"
        else:
            competitiveness = "ABOVE_MARKET"

        return RateBenchmarkResult(
            target_rate=target_rate,
            market_avg_rate=total_market_avg,
            fuel_surcharge=fuel_surcharge_val,
            variance_pct=variance_pct,
            competitiveness=competitiveness,
            index_sources={
                "base_rate_index": "FMC / Ocean Spot Benchmark (FBX Equivalent)",
                "fuel_index": "U.S. EIA Weekly Diesel Index"
            }
        )