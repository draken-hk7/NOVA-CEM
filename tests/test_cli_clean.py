import json
from pathlib import Path
from uuid import uuid4

from nova.cli.main import main


def _test_root(name: str) -> Path:
    return Path("outputs/test-artifacts/clean-cli") / f"{name}-{uuid4().hex}"


def _make_job(root: Path, name: str, module: str | None, payload_size: int = 8) -> Path:
    job = root / name
    job.mkdir(parents=True, exist_ok=True)
    if module is not None:
        (job / "data.json").write_text(json.dumps({"module": module}), encoding="utf-8")
    (job / "artifact.bin").write_bytes(b"x" * payload_size)
    return job


def test_cli_clean_dry_run_lists_jobs_and_prunes_per_module_type(capsys):
    root = _test_root("dry-run")
    oldest_by_type = {
        "rocket": "kerolox_100N_10bar_2026-01-01_0000",
        "hx": "hx_exhaust_hydrogen_1kW_2026-01-01_0000",
        "actuator": "actuator_1N_1mm_2026-01-01_0000",
        "assembly": "assembly_2026-01-01_0000",
    }
    for day in range(1, 7):
        stamp = f"2026-01-{day:02d}_0000"
        _make_job(root, f"kerolox_100N_10bar_{stamp}", "rocket-engine", payload_size=day)
        _make_job(root, f"hx_exhaust_hydrogen_{day}kW_{stamp}", "heat-exchanger", payload_size=day)
        _make_job(root, f"actuator_{day}N_1mm_{stamp}", "actuator", payload_size=day)
        _make_job(root, f"assembly_{stamp}", None, payload_size=day)

    assert main(["clean", "--output-dir", str(root), "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    deleted_modules = sorted(job["module_type"] for job in payload["would_delete"])

    assert len(payload["jobs"]) == 24
    assert payload["dry_run"] is True
    assert payload["keep"] == 5
    assert payload["would_delete_count"] == 4
    assert payload["deleted_count"] == 0
    assert deleted_modules == ["actuator", "assembly", "hx", "rocket"]
    assert {job["job_id"] for job in payload["would_delete"]} == set(oldest_by_type.values())
    assert all((root / job_id).exists() for job_id in oldest_by_type.values())
    assert payload["jobs"][0]["size_bytes"] > 0


def test_cli_clean_deletes_older_jobs_with_custom_keep(capsys):
    root = _test_root("keep")
    jobs = [
        _make_job(root, f"kerolox_100N_10bar_2026-01-{day:02d}_0000", "rocket-engine")
        for day in range(1, 5)
    ]

    assert main(["clean", "--output-dir", str(root), "--keep", "2"]) == 0

    payload = json.loads(capsys.readouterr().out)

    assert payload["keep"] == 2
    assert payload["would_delete_count"] == 2
    assert payload["deleted_count"] == 2
    assert not jobs[0].exists()
    assert not jobs[1].exists()
    assert jobs[2].exists()
    assert jobs[3].exists()


def test_cli_clean_all_removes_every_cli_output_child(capsys):
    root = _test_root("all")
    job = _make_job(root, "assembly_2026-01-01_0000", None)
    loose_file = root / "assembly.stl"
    loose_file.write_text("solid assembly\nendsolid assembly\n", encoding="ascii")

    assert main(["clean", "--output-dir", str(root), "--all"]) == 0

    payload = json.loads(capsys.readouterr().out)

    assert payload["all"] is True
    assert payload["keep"] is None
    assert payload["would_delete_count"] == 2
    assert payload["deleted_count"] == 2
    assert root.exists()
    assert not job.exists()
    assert not loose_file.exists()
    assert list(root.iterdir()) == []
