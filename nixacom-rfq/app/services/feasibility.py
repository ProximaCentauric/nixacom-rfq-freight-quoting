from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class FeasibilityResult:
    score: float
    verdict: str  # ACCEPTED, TRANSFERRED, REJECTED
    transfer_lane: Optional[str]
    reasons: List[str]
    score_breakdown: Dict[str, float]

class FeasibilityEngine:
    def __init__(self):
        # Operational parameters & supported network
        self.supported_ports = {"CNSHA", "USLGB", "USLAX", "CNSNZ", "DEHAM", "NLRTM"}
        self.specialized_partner_lanes = {
            "HAZMAT": "Partner Network - Special Cargo Desk",
            "OUT_OF_NETWORK": "Partner Network - Interline Desk",
            "OVERWEIGHT": "Heavy Haul Operations"
        }
        self.max_payload_kg = 24000.0  # Max payload per container
        self.weekly_capacity_cap = 50   # Max FEUs per week on lane
        self.current_weekly_allocated = 42

    def evaluate_rfq(self, rfq_data: Dict) -> FeasibilityResult:
        score_breakdown = {}
        reasons = []
        transfer_lane = None

        # 1. Route Feasibility (Weight: 40%)
        origin = rfq_data.get("origin", "")
        destination = rfq_data.get("destination", "")
        
        origin_code = origin.get("port_code", origin) if isinstance(origin, dict) else origin
        dest_code = destination.get("port_code", destination) if isinstance(destination, dict) else destination

        route_in_network = origin_code in self.supported_ports and dest_code in self.supported_ports
        if route_in_network:
            score_breakdown["route"] = 40.0
        else:
            score_breakdown["route"] = 0.0
            reasons.append(f"Route {origin_code} -> {dest_code} outside primary network.")
            transfer_lane = self.specialized_partner_lanes["OUT_OF_NETWORK"]

        # 2. Equipment & Payload Limits (Weight: 30%)
        cargo_physicals = rfq_data.get("cargo_physicals", {})
        weight_kg = cargo_physicals.get("gross_weight_kg", 0) or rfq_data.get("gross_weight_kg", 0)
        
        if weight_kg <= self.max_payload_kg:
            score_breakdown["equipment_payload"] = 30.0
        else:
            score_breakdown["equipment_payload"] = 10.0
            reasons.append(f"Payload weight ({weight_kg} kg) exceeds max unit threshold ({self.max_payload_kg} kg).")
            if not transfer_lane:
                transfer_lane = self.specialized_partner_lanes["OVERWEIGHT"]

        # 3. HazMat & Special Handling Constraints (Weight: 15%)
        hazmat_info = rfq_data.get("hazmat_special", {})
        is_hazmat = hazmat_info.get("is_hazardous", False) or rfq_data.get("is_hazardous", False)

        if not is_hazmat:
            score_breakdown["special_handling"] = 15.0
        else:
            score_breakdown["special_handling"] = 0.0
            reasons.append("Hazardous cargo requires specialized compliance approval.")
            if not transfer_lane:
                transfer_lane = self.specialized_partner_lanes["HAZMAT"]

        # 4. Capacity Constraints (Weight: 15%)
        equipment_qty = rfq_data.get("equipment_quantity", 1)
        remaining_capacity = self.weekly_capacity_cap - self.current_weekly_allocated

        if equipment_qty <= remaining_capacity:
            score_breakdown["capacity"] = 15.0
        else:
            score_breakdown["capacity"] = 5.0
            reasons.append(f"Requested quantity ({equipment_qty}) exceeds available weekly capacity ({remaining_capacity}).")

        # Total Score Calculation
        total_score = sum(score_breakdown.values())

        # Verdict Decision Matrix
        if total_score >= 80.0 and not is_hazmat and route_in_network:
            verdict = "ACCEPTED"
        elif total_score >= 40.0 or transfer_lane:
            verdict = "TRANSFERRED"
        else:
            verdict = "REJECTED"

        return FeasibilityResult(
            score=total_score,
            verdict=verdict,
            transfer_lane=transfer_lane,
            reasons=reasons,
            score_breakdown=score_breakdown
        )