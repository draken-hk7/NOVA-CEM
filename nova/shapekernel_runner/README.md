# NOVA ShapeKernel Runner

This isolated C# runner accepts one JSON rocket-engine request on standard input
and writes one JSON response on standard output. It uses LEAP71 ShapeKernel
BaseShapes and PicoGK to generate the native STL requested by NOVA.

ShapeKernel is distributed by LEAP71 as source/a Git submodule, rather than as a
NuGet package. PicoGK is the NuGet dependency used by this project.

```powershell
cd nova/shapekernel_runner
git clone https://github.com/leap71/LEAP71_ShapeKernel.git vendor/LEAP71_ShapeKernel
dotnet build -c Release
```

Set `NOVA_GEOMETRY_BACKEND=shapekernel` to use the runner. The Python bridge
prefers the built `bin/Release/net9.0/nova_runner.dll`; alternatively set
`NOVA_SHAPEKERNEL_RUNNER` to a published runner DLL or executable. Set
`NOVA_SHAPEKERNEL_SOURCE` when the ShapeKernel source checkout lives elsewhere.
