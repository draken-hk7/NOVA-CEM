import json
from dataclasses import dataclass

import numpy as np

from nova.core.analysis import analyze_combustion_stability
from nova.core.output.exporter import NOVAJSONEncoder, PerformanceReporter
from nova.core.types import CEMRunResult


@dataclass
class _JSONDesign:
    metadata: dict


def test_nova_json_encoder_handles_dataclasses_numpy_and_unknown_values():
    stability = analyze_combustion_stability(
        chamber_length_mm=100.0,
        chamber_radius_mm=25.0,
        speed_of_sound_m_s=400.0,
    )
    encoded = json.dumps(
        {
            "stability": stability,
            "float32": np.float32(1.25),
            "float64": np.float64(2.5),
            "int32": np.int32(3),
            "int64": np.int64(4),
            "array": np.array([5, 6]),
            "opaque": object(),
        },
        cls=NOVAJSONEncoder,
    )
    decoded = json.loads(encoded)

    assert decoded["stability"]["chamber_acoustic_frequency_hz"] == 2000.0
    assert decoded["float32"] == 1.25
    assert decoded["float64"] == 2.5
    assert decoded["int32"] == 3
    assert decoded["int64"] == 4
    assert decoded["array"] == [5, 6]
    assert isinstance(decoded["opaque"], str)


def test_generate_json_data_normalizes_stability_analysis_for_standard_json_dumps():
    stability = analyze_combustion_stability(
        chamber_length_mm=100.0,
        chamber_radius_mm=25.0,
        speed_of_sound_m_s=400.0,
    )
    run = CEMRunResult(
        job_id="json-export",
        module="rocket-engine",
        inputs={"scalar": np.int64(9)},
        design=_JSONDesign(metadata={"aerospace_analysis": {"combustion_stability": stability}}),
    )

    payload = PerformanceReporter().generate_json_data(run)

    assert json.loads(json.dumps(payload))["inputs"]["scalar"] == 9
    assert payload["design"]["metadata"]["aerospace_analysis"]["combustion_stability"]["stability_risk"] is False
