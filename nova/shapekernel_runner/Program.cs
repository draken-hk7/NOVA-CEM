using System.Numerics;
using System.Text.Json;
using System.Text.Json.Serialization;
using Leap71.ShapeKernel;
using PicoGK;

namespace Nova.ShapeKernelRunner;

internal static class Program
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static int Main()
    {
        try
        {
            var requestText = Console.In.ReadToEnd();
            var request = JsonSerializer.Deserialize<EngineSpec>(requestText, JsonOptions)
                ?? throw new InvalidOperationException("No ShapeKernel engine request was supplied.");
            request.Validate();

            var outputPath = Path.GetFullPath(request.OutputStl);
            var outputDirectory = Path.GetDirectoryName(outputPath)
                ?? throw new InvalidOperationException("The STL output path must include a directory.");
            Directory.CreateDirectory(outputDirectory);

            // PicoGK owns voxelisation and STL output; geometry work stays inside its task callback.
            Library.Go(request.VoxelSizeMm, () =>
            {
                Voxels engine = EngineGeometry.Build(request);
                Sh.ExportVoxelsToSTLFile(engine, outputPath);
            }, outputDirectory);

            if (!File.Exists(outputPath) || new FileInfo(outputPath).Length == 0)
            {
                throw new InvalidOperationException("ShapeKernel completed without creating the requested STL.");
            }

            WriteResponse(new RunnerResponse(true, outputPath, "ShapeKernel STL generated", null));
            return 0;
        }
        catch (Exception exception)
        {
            WriteResponse(new RunnerResponse(false, null, null, exception.Message));
            return 1;
        }
    }

    private static void WriteResponse(RunnerResponse response)
    {
        // The Python bridge reads the final JSON line even when PicoGK logs to stdout.
        Console.Out.WriteLine(JsonSerializer.Serialize(response, JsonOptions));
    }
}

internal sealed class EngineSpec
{
    [JsonPropertyName("output_stl")]
    public string OutputStl { get; init; } = string.Empty;

    [JsonPropertyName("nozzle_type")]
    public string NozzleType { get; init; } = "bell";

    [JsonPropertyName("throat_radius_mm")]
    public float ThroatRadiusMm { get; init; }

    [JsonPropertyName("chamber_radius_mm")]
    public float ChamberRadiusMm { get; init; }

    [JsonPropertyName("expansion_ratio")]
    public float ExpansionRatio { get; init; }

    [JsonPropertyName("chamber_length_mm")]
    public float ChamberLengthMm { get; init; }

    [JsonPropertyName("wall_thickness_mm")]
    public float WallThicknessMm { get; init; }

    [JsonPropertyName("n_cooling_channels")]
    public int CoolingChannelCount { get; init; } = 8;

    [JsonPropertyName("cooling_channel_depth_mm")]
    public float CoolingChannelDepthMm { get; init; }

    [JsonPropertyName("voxel_size_mm")]
    public float VoxelSizeMm { get; init; } = 0.35f;

    public void Validate()
    {
        if (!string.Equals(NozzleType, "bell", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("The ShapeKernel runner currently supports bell nozzles only.");
        }
        if (string.IsNullOrWhiteSpace(OutputStl))
        {
            throw new InvalidOperationException("output_stl is required.");
        }
        if (ThroatRadiusMm <= 0 || ChamberRadiusMm <= 0 || ExpansionRatio <= 1 || ChamberLengthMm <= 0 || WallThicknessMm <= 0)
        {
            throw new InvalidOperationException("All engine dimensions must be positive and expansion_ratio must exceed one.");
        }
        if (CoolingChannelCount < 0 || VoxelSizeMm is < 0.05f or > 1.0f)
        {
            throw new InvalidOperationException("Cooling channel count must be non-negative and voxel_size_mm must be within 0.05 to 1.0.");
        }
    }
}

internal sealed record RunnerResponse(
    [property: JsonPropertyName("success")] bool Success,
    [property: JsonPropertyName("stl_path")] string? StlPath,
    [property: JsonPropertyName("message")] string? Message,
    [property: JsonPropertyName("error")] string? Error);

internal static class EngineGeometry
{
    public static Voxels Build(EngineSpec spec)
    {
        var chamberOuterRadius = spec.ChamberRadiusMm + spec.WallThicknessMm;
        var throatOuterRadius = spec.ThroatRadiusMm + spec.WallThicknessMm;
        var exitRadius = spec.ThroatRadiusMm * MathF.Sqrt(spec.ExpansionRatio);
        var exitOuterRadius = exitRadius + spec.WallThicknessMm;
        var convergentLength = MathF.Max(1.2f * spec.ChamberRadiusMm, 3.0f * (spec.ChamberRadiusMm - spec.ThroatRadiusMm));
        var divergentLength = MathF.Max(3.0f * exitRadius, 2.0f * spec.ThroatRadiusMm);
        var throatZ = spec.ChamberLengthMm + convergentLength;

        Voxels outerBody = Cylinder(0f, spec.ChamberLengthMm, chamberOuterRadius)
            + Cone(spec.ChamberLengthMm, convergentLength, chamberOuterRadius, throatOuterRadius)
            + Cone(throatZ, divergentLength, throatOuterRadius, exitOuterRadius)
            + Flange(-5f, 5f, spec.ChamberRadiusMm * 0.86f, chamberOuterRadius + 8f)
            + Flange(spec.ChamberLengthMm - 3f, 5f, spec.ChamberRadiusMm * 0.86f, chamberOuterRadius + 6f);

        Voxels bore = Cylinder(-0.2f, spec.ChamberLengthMm + 0.4f, spec.ChamberRadiusMm)
            + Cone(spec.ChamberLengthMm, convergentLength, spec.ChamberRadiusMm, spec.ThroatRadiusMm)
            + Cone(throatZ, divergentLength + 0.2f, spec.ThroatRadiusMm, exitRadius);

        var bossOffset = chamberOuterRadius - 0.35f * spec.WallThicknessMm;
        var inletZ = spec.ChamberLengthMm * 0.30f;
        var outletZ = spec.ChamberLengthMm * 0.72f;
        Voxels bosses = Boss(new Vector3(bossOffset, 0f, inletZ), Vector3.UnitX, 4f, 10f)
            + Boss(new Vector3(0f, bossOffset, outletZ), Vector3.UnitY, 4f, 10f);
        Voxels bossBores = Bore(new Vector3(bossOffset - 0.2f, 0f, inletZ), Vector3.UnitX, 3f, 11f)
            + Bore(new Vector3(0f, bossOffset - 0.2f, outletZ), Vector3.UnitY, 3f, 11f);

        Voxels engine = (outerBody + bosses) - bore - bossBores;
        Voxels? coolingChannels = BuildHelicalChannels(spec, chamberOuterRadius);
        return coolingChannels is null ? engine : engine - coolingChannels;
    }

    private static Voxels? BuildHelicalChannels(EngineSpec spec, float chamberOuterRadius)
    {
        if (spec.CoolingChannelCount == 0)
        {
            return null;
        }

        Voxels? channels = null;
        var requestedChannelRadius = spec.CoolingChannelDepthMm > 0f
            ? spec.CoolingChannelDepthMm * 0.5f
            : spec.WallThicknessMm * 0.28f;
        var channelRadius = MathF.Max(0.25f, MathF.Min(requestedChannelRadius, 0.75f));
        var helixRadius = chamberOuterRadius - MathF.Max(channelRadius + 0.15f, spec.WallThicknessMm * 0.45f);
        var startZ = spec.ChamberLengthMm * 0.08f;
        var length = spec.ChamberLengthMm * 0.84f;
        var turns = MathF.Max(1.0f, length / MathF.Max(45f, 2.0f * chamberOuterRadius));

        for (var channel = 0; channel < spec.CoolingChannelCount; channel++)
        {
            var points = new List<Vector3>();
            var phase = 2f * MathF.PI * channel / spec.CoolingChannelCount;
            for (var step = 0; step <= 160; step++)
            {
                var ratio = step / 160f;
                var angle = phase + 2f * MathF.PI * turns * ratio;
                points.Add(new Vector3(
                    helixRadius * MathF.Cos(angle),
                    helixRadius * MathF.Sin(angle),
                    startZ + length * ratio));
            }
            var frames = new Frames(points, Vector3.UnitZ);
            Voxels channelVoxels = new BasePipe(frames, 0.01f, channelRadius).voxConstruct();
            channels = channels is null ? channelVoxels : channels + channelVoxels;
        }
        return channels;
    }

    private static Voxels Cylinder(float z, float length, float radius) =>
        new BaseCylinder(new LocalFrame(new Vector3(0f, 0f, z), Vector3.UnitZ), length, radius).voxConstruct();

    private static Voxels Cone(float z, float length, float startRadius, float endRadius) =>
        new BaseCone(new LocalFrame(new Vector3(0f, 0f, z), Vector3.UnitZ), length, startRadius, endRadius).voxConstruct();

    private static Voxels Flange(float z, float length, float innerRadius, float outerRadius) =>
        new BasePipe(new LocalFrame(new Vector3(0f, 0f, z), Vector3.UnitZ), length, innerRadius, outerRadius).voxConstruct();

    private static Voxels Boss(Vector3 position, Vector3 axis, float radius, float length) =>
        new BaseCylinder(new LocalFrame(position, axis), length, radius).voxConstruct();

    private static Voxels Bore(Vector3 position, Vector3 axis, float radius, float length) =>
        new BaseCylinder(new LocalFrame(position, axis), length, radius).voxConstruct();
}
