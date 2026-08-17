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

## Optional ShapeKernel Geometry Backend

NOVA can produce a rocket-engine STL through LEAP71 ShapeKernel and its PicoGK
voxel engine. It is optional: when its runner, source checkout, or .NET runtime
is unavailable, NOVA automatically uses CadQuery instead.

ShapeKernel is supplied by LEAP71 as source or a Git submodule, rather than as a
ShapeKernel NuGet package. The runner references the official `PicoGK` NuGet
package (`2.3.0`) and compiles the ShapeKernel source with it. This version
matches the current ShapeKernel source APIs, including `PicoGK.Numerics` and
`PicoGK.Shapes`.

1. Install the current **.NET 9 SDK**. The current LEAP71 PicoGK NuGet package
   targets `net9.0`; .NET 8 alone is detected by NOVA but cannot build this
   runner.
2. Fetch ShapeKernel and build the runner:

   ```powershell
   cd nova/shapekernel_runner
   git clone https://github.com/leap71/LEAP71_ShapeKernel.git vendor/LEAP71_ShapeKernel
   dotnet build -c Release
   ```

3. Select it for a design:

   ```powershell
   $env:NOVA_GEOMETRY_BACKEND = "shapekernel"
   nova design rocket-engine --thrust 5000N --propellant kerolox --chamber-pressure 50 --geometry-backend shapekernel
   ```

The bridge sends engine dimensions as JSON to the C# runner and uses its native
STL when it succeeds. NOVA retains the CadQuery B-rep for structural validation,
STEP export, and assemblies. Use `NOVA_SHAPEKERNEL_SOURCE` for a ShapeKernel
checkout outside `nova/shapekernel_runner/vendor`, or
`NOVA_SHAPEKERNEL_RUNNER` for a prebuilt runner DLL/executable.
