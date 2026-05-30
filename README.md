# NOVA Computational Engineering Model

NOVA is a deterministic Python engineering-model prototype for generating
validated physical designs from typed requirements. This first build focuses on
the core physics solvers, mesh-backed geometry engine, manufacturing rules,
rocket-propulsion pipeline, API, CLI, and tests.

The implementation deliberately does not call LLMs in any physics or geometry
path. Optional geometry and reporting packages are declared in `pyproject.toml`;
when they are unavailable, NOVA uses deterministic local fallbacks so the core
pipeline remains testable.

## Quick Start

```bash
python -m pytest
python -m nova.cli.main design rocket-engine --thrust 5000N --propellant kerolox --chamber-pressure 50
uvicorn nova.api.main:app --reload
```

