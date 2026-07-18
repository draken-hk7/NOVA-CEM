import json
import math
import re
from pathlib import Path
from uuid import uuid4

import pytest

from nova.cli.main import main
from nova.core.mission import G0_M_S2, calculate_mission


def _engine_payload() -> dict:
    return {
        "job_id": "engine-hydrolox",
        "module": "rocket-engine",
        "inputs": {"propellant": "hydrolox"},
        "design": {
            "performance": {
                "specific_impulse_s": 450.0,
                "thrust_N": 5000.0,
                "mass_flow_rate_kg_s": 1.2,
            },
            "metadata": {"combustion": {"OF_ratio": 5.5}},
        },
    }


def test_calculate_mission_uses_tsiolkovsky_and_engine_flow_rate():
    result = calculate_mission(
        _engine_payload(),
        vehicle_mass_kg=50.0,
        propellant_mass_kg=20.0,
        engine_job_id="engine-hydrolox",
    )

    assert result.delta_v_m_s == pytest.approx(450.0 * G0_M_S2 * math.log(70.0 / 50.0))
    assert result.burn_time_s == pytest.approx(20.0 / 1.2)
    assert result.thrust_to_weight == pytest.approx(5000.0 / (70.0 * G0_M_S2))
    assert result.hydrogen_mass_needed_kg_s == pytest.approx(1.2 / 6.5)
    assert result.max_altitude_m > 0.0
    assert result.burnout_altitude_m > 0.0
    assert result.coast_altitude_m > 0.0
    assert result.trajectory[-1].altitude_m == pytest.approx(result.max_altitude_m)
    assert result.solar_energy_kwh_per_day > 0.0
    assert result.can_liftoff is True


def test_calculate_mission_falls_back_to_thrust_over_isp_mass_flow():
    payload = _engine_payload()
    del payload["design"]["performance"]["mass_flow_rate_kg_s"]

    result = calculate_mission(payload, vehicle_mass_kg=50.0, propellant_mass_kg=20.0)

    assert result.mass_flow_rate_kg_s == pytest.approx(5000.0 / (450.0 * G0_M_S2))


def test_cli_mission_writes_timestamped_report_and_json(capsys):
    root = Path("outputs/test-artifacts/mission-cli") / uuid4().hex
    engine_dir = root / "engine-job"
    output_root = root / "out"
    engine_dir.mkdir(parents=True, exist_ok=True)
    (engine_dir / "data.json").write_text(json.dumps(_engine_payload()), encoding="utf-8")

    assert (
        main(
            [
                "mission",
                "--engine",
                str(engine_dir),
                "--vehicle-mass",
                "50",
                "--propellant-mass",
                "20",
                "--launches-per-month",
                "4",
                "--output-dir",
                str(output_root),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    output_dir = Path(payload["output_dir"])
    report = Path(payload["report"])
    trajectory = output_dir / "trajectory.svg"
    data = output_dir / "data.json"

    assert output_dir.parent == output_root
    assert re.fullmatch(r"mission_engine-job_\d{4}-\d{2}-\d{2}_\d{4}(?:_\d{2})?", output_dir.name)
    assert report.name == "mission_report.pdf"
    assert report.exists() and b"NOVA Mission Report" in report.read_bytes()
    assert trajectory.exists() and "Mission Trajectory" in trajectory.read_text(encoding="utf-8")
    assert data.exists()
    stored = json.loads(data.read_text(encoding="utf-8"))
    assert stored["module"] == "mission"
    assert stored["mission"]["delta_v_m_s"] == pytest.approx(payload["delta_v_m_s"])
    assert stored["mission"]["planned_launches_per_month"] == pytest.approx(4.0)
    assert stored["mission"]["solar_energy_kwh_per_day"] > 0.0
