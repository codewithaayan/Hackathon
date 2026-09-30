from backend.calculations.risk_adapter import calculate_risk
from backend.calculations.simulator_adapter import SimulationRequest, SimulationResult, simulate
from backend.integrations import Components, JSONComponent


def build_components() -> Components:
    return Components(
        risk=calculate_risk,
        simulator=JSONComponent(SimulationRequest, SimulationResult, simulate),
        # No AI provider/account has been selected, and the database-backed map
        # routes already expose legitimate layers without a replacement adapter.
        ai=None,
        layers=None,
    )
