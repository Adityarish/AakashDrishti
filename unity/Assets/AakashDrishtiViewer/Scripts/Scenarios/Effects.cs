using System;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace AakashDrishti.Viewer.Scenarios
{
    /// <summary>Everything an effect needs from the viewer: the terrain, the camera and the shared sprite batches.</summary>
    public sealed class FxContext
    {
        public TerrainView Terrain;
        public Camera Cam;
        public Transform Root;
        public SpriteBatch Glow, Flame, Smoke;

        public HeightField Field => Terrain.Field;
        public float Exag => Terrain.Exaggeration;
        public float GroundY(float x, float z) => Field.Sample(x, z) * Exag;
        public float Diagonal => Mathf.Sqrt(Field.SizeX * Field.SizeX + Field.SizeZ * Field.SizeZ);
    }

    public abstract class ScenarioEffect
    {
        /// <param name="t">Seconds since this effect was created.</param>
        public abstract void Tick(FxContext c, float dt, float t);
        public abstract void Dispose();
    }

    // ------------------------------------------------------------------ flood

    /// <summary>The flood surface: a translucent rippling plane at a chosen height (DSM metres) over the whole terrain.</summary>
    public sealed class WaterEffect : ScenarioEffect
    {
        readonly GameObject go;
        readonly float baseSizeY;
        public float Level;

        public WaterEffect(FxContext c, float level)
        {
            Level = level;
            HeightField f = c.Field;
            go = new GameObject("FloodWater");
            go.transform.SetParent(c.Terrain.WorldRoot, false); // inherits the vertical exaggeration with the terrain
            var mesh = new Mesh { name = "FloodWater" };
            float mx = f.SizeX * 0.01f, mz = f.SizeZ * 0.01f;
            mesh.vertices = new[] { new Vector3(-mx, 0, -mz), new Vector3(f.SizeX + mx, 0, -mz), new Vector3(f.SizeX + mx, 0, f.SizeZ + mz), new Vector3(-mx, 0, f.SizeZ + mz) };
            mesh.triangles = new[] { 0, 2, 1, 0, 3, 2 };
            mesh.bounds = new Bounds(new Vector3(f.SizeX * 0.5f, 0, f.SizeZ * 0.5f), new Vector3(f.SizeX * 1.2f, 10000f, f.SizeZ * 1.2f));
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterial = new Material(FxKit.WaterBase);
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
            baseSizeY = Mathf.Max(f.SizeX, f.SizeZ);
            Apply(0f);
        }

        void Apply(float t) => go.transform.localPosition = new Vector3(0, Level + Mathf.Sin(t * 1.6f) * baseSizeY * 0.0004f, 0);

        public override void Tick(FxContext c, float dt, float t) => Apply(t);

        public override void Dispose()
        {
            if (go == null) return;
            var mf = go.GetComponent<MeshFilter>();
            if (mf != null) Object.Destroy(mf.sharedMesh);
            Object.Destroy(go);
        }
    }

    // ------------------------------------------------------------------ pin

    /// <summary>A pulsing pin marking a picked point before its scenario runs.</summary>
    public sealed class PinEffect : ScenarioEffect
    {
        readonly GameObject root;
        readonly TerrainDecal ring;
        readonly Vector2 pos;
        readonly float size;
        readonly float baseY;

        public PinEffect(FxContext c, Vector2 pos, Color color)
        {
            this.pos = pos;
            size = Mathf.Max(c.Diagonal * 0.012f, 3f);
            baseY = c.GroundY(pos.x, pos.y);
            root = new GameObject("Pin");
            Vehicle.Prim(PrimitiveType.Cylinder, root.transform, new Vector3(0, size * 1.1f, 0), new Vector3(size * 0.16f, size * 1.1f, size * 0.16f), color);
            Vehicle.Prim(PrimitiveType.Sphere, root.transform, new Vector3(0, size * 2.4f, 0), Vector3.one * size * 0.75f, color);
            ring = new TerrainDecal(c.Root, FxKit.AlphaBase, "PinRing");
        }

        public override void Tick(FxContext c, float dt, float t)
        {
            float bob = Mathf.Sin(t * 3f) * size * 0.12f;
            root.transform.position = new Vector3(pos.x, baseY + bob, pos.y);
            float p = (t * 0.9f) % 1f;
            float r = size * (1f + p * 1.8f);
            ring.Set(c.Field, c.Exag, pos, r * 0.82f, r, FxKit.Rgba(Color.red, 0.6f * (1f - p)), FxKit.Rgba(Color.red, 0.6f * (1f - p)), 0.3f);
        }

        public override void Dispose()
        {
            if (root != null) Object.Destroy(root);
            ring.Destroy();
        }
    }

    // ------------------------------------------------------------------ fire

    /// <summary>
    /// A fire that catches (a spark, then flames spreading outward), burns with embers and smoke, and stays alight
    /// until <see cref="Douse"/> puts it out.
    /// </summary>
    public sealed class FireEffect : ScenarioEffect
    {
        struct Tongue { public Vector2 P; public float W, H, Delay, Phase, Dist, Y; }
        struct Ember { public Vector2 P; public float Phase, Drift, Y; }
        struct Puff { public float Phase; public Vector2 P; public float Y; }

        readonly Vector2 centre;
        readonly float radius;
        readonly Tongue[] tongues = new Tongue[26];
        readonly Ember[] embers = new Ember[34];
        readonly Puff[] puffs = new Puff[9];
        readonly TerrainDecal scorch, glow;
        readonly float groundY;
        bool ignitePending = true;
        float igniteAt, douseAt = float.PositiveInfinity, douseDur = 3f, douseDelay = -1f;

        public FireEffect(FxContext c, Vector2 centre, float radius)
        {
            this.centre = centre;
            this.radius = radius;
            groundY = c.GroundY(centre.x, centre.y);
            var rng = new Rng(7);
            for (int i = 0; i < tongues.Length; i++)
            {
                float r = Mathf.Sqrt(rng.Next()) * radius * 0.85f, a = rng.Next() * Mathf.PI * 2f;
                float closeness = 1f - r / radius;
                float w = (2.4f + 2.6f * closeness) * (0.7f + 0.6f * rng.Next()) * (radius / 7f);
                float x = centre.x + Mathf.Cos(a) * r, z = centre.y + Mathf.Sin(a) * r;
                tongues[i] = new Tongue { P = new Vector2(x, z), W = w, H = w * 2.1f, Delay = r / radius * 2.1f + rng.Next() * 0.4f, Phase = rng.Next() * 10f + i, Dist = r / radius, Y = c.GroundY(x, z) };
            }
            for (int i = 0; i < embers.Length; i++)
            {
                float a = rng.Next() * Mathf.PI * 2f, r = Mathf.Sqrt(rng.Next()) * radius * 0.75f;
                embers[i] = new Ember { P = new Vector2(centre.x + Mathf.Cos(a) * r, centre.y + Mathf.Sin(a) * r), Phase = rng.Next(), Drift = (rng.Next() - 0.5f) * radius * 0.8f, Y = groundY };
            }
            for (int i = 0; i < puffs.Length; i++)
                puffs[i] = new Puff { Phase = i / (float)puffs.Length, P = centre + new Vector2(rng.Next() - 0.5f, rng.Next() - 0.5f) * radius * 0.5f, Y = groundY };
            scorch = new TerrainDecal(c.Root, FxKit.AlphaBase, "Scorch");
            glow = new TerrainDecal(c.Root, FxKit.AddBase, "FireGlow");
        }

        /// <summary>Restart the ignition sequence.</summary>
        public void Ignite()
        {
            ignitePending = true;
            douseAt = float.PositiveInfinity;
            douseDelay = -1f;
        }

        /// <summary>Start putting the fire out <paramref name="delay"/> seconds from now, over <paramref name="duration"/> seconds.</summary>
        public void Douse(float delay, float duration)
        {
            douseDelay = delay;
            douseDur = Mathf.Max(duration, 0.5f);
        }

        public override void Tick(FxContext c, float dt, float t)
        {
            if (ignitePending) { igniteAt = t; ignitePending = false; }
            if (douseDelay >= 0f) { douseAt = t + douseDelay; douseDelay = -1f; }

            float burn = Mathf.Clamp01((t - igniteAt) / 2.6f);
            float dGlobal = FxKit.EaseInOut((t - douseAt) / douseDur);
            float intensity = burn * (1f - dGlobal);
            Camera cam = c.Cam;

            foreach (Tongue f in tongues)
            {
                float grow = Mathf.Max(FxKit.EaseOutBack((t - igniteAt - f.Delay) / 0.7f), 0f);
                float out01 = FxKit.EaseInOut((t - douseAt - f.Dist * douseDur * 0.35f) / (douseDur * 0.65f));
                float vis = grow * (1f - out01);
                if (vis <= 0.001f) continue;
                float flick = 1f + 0.13f * Mathf.Sin(t * 9f + f.Phase) + 0.07f * Mathf.Sin(t * 17f + f.Phase * 2f);
                float sway = Mathf.Sin(t * 3f + f.Phase) * 0.09f * f.W;
                float alpha = Mathf.Min(1f, vis * 2f);
                Vector3 p = new Vector3(f.P.x + sway, f.Y + 0.15f, f.P.y);
                c.Flame.Add(cam, p, f.W * vis * flick, f.H * vis * flick, new Color32(255, 92, 20, (byte)(230 * alpha)), true, 0.04f);
                c.Flame.Add(cam, p + Vector3.up * 0.05f, f.W * 0.55f * vis * flick, f.H * 0.55f * vis * flick, new Color32(255, 214, 80, (byte)(245 * alpha)), true, 0.04f);
            }

            float scorchGrow = Mathf.Clamp01((t - igniteAt) / 6f);
            scorch.Set(c.Field, c.Exag, centre, 0f, radius * 0.95f, FxKit.Rgba(new Color(0.08f, 0.05f, 0.03f), 0.55f * scorchGrow), FxKit.Rgba(new Color(0.08f, 0.05f, 0.03f), 0f), 0.2f);
            float glowA = 0.6f * intensity * (0.85f + 0.15f * Mathf.Sin(t * 8f));
            glow.Set(c.Field, c.Exag, centre, 0f, radius * 1.35f * (0.4f + 0.6f * FxKit.EaseOut(burn)), FxKit.Rgba(new Color(1f, 0.36f, 0.08f), glowA), FxKit.Rgba(new Color(1f, 0.2f, 0.02f), 0f), 0.35f);

            foreach (Ember e in embers)
            {
                float age = (t * 0.32f + e.Phase) % 1f;
                Vector3 p = new Vector3(e.P.x + Mathf.Sin(t * 2f + e.Phase * 9f) * e.Drift * age, e.Y + 1.5f + age * radius * 2.4f, e.P.y);
                c.Glow.Add(cam, p, radius * 0.16f * (1f - age * 0.6f), radius * 0.16f * (1f - age * 0.6f), new Color32(255, 180, 70, (byte)(240 * (1f - age) * intensity)));
            }

            float smokeLinger = burn * (1f - Mathf.Clamp01((t - douseAt - douseDur) / (douseDur * 1.8f)));
            foreach (Puff s in puffs)
            {
                float age = (t * 0.15f + s.Phase) % 1f;
                Vector3 p = new Vector3(s.P.x + age * radius * 0.5f, s.Y + 2.5f + age * radius * 3.4f, s.P.y);
                float size = radius * (0.7f + age * 1.7f);
                float lightMix = Mathf.Max(dGlobal, age * 0.35f);
                byte g = (byte)Mathf.Lerp(43f, 229f, lightMix);
                float a = 0.34f * Mathf.Sin(Mathf.PI * age) * smokeLinger * (0.6f + 0.4f * (1f - dGlobal));
                c.Smoke.Add(cam, p, size, size, new Color32(g, g, g, (byte)(255f * a)));
            }
        }

        public override void Dispose()
        {
            scorch.Destroy();
            glow.Destroy();
        }
    }

    // ------------------------------------------------------------------ drone + water arc

    /// <summary>
    /// A drone flies in from the sky to the stand-off point and pours water on the fire along the true projectile
    /// arc (horizontal release: x = v t, drop = g t^2 / 2), so the stand-off it uses is exactly the reach that was computed.
    /// </summary>
    public sealed class DroneDropEffect : ScenarioEffect
    {
        const float Fly = 3.4f, Settle = 0.7f, Fall = 1.9f, Spray = 6.5f;
        const int Drops = 220;

        readonly Vehicle drone;
        readonly Vector3 fire, standoff, spawn;
        readonly float scale, standoffDist;
        readonly TerrainDecal ring;
        readonly LineRenderer guide;
        readonly float[] jx = new float[Drops], jz = new float[Drops];
        readonly Vector3 dir;

        /// <summary>Seconds after the effect starts when the first water reaches the fire.</summary>
        public float FirstHitAfter => Fly + Settle + Fall;

        public DroneDropEffect(FxContext c, Vector3 fire, Vector3 standoff, Vector3 spawn, float droneScale)
        {
            this.fire = fire; this.standoff = standoff; this.spawn = spawn; scale = droneScale;
            Vector3 toFire = new Vector3(fire.x - standoff.x, 0, fire.z - standoff.z);
            standoffDist = toFire.magnitude;
            dir = standoffDist > 1e-3f ? toFire / standoffDist : Vector3.right;
            drone = Vehicle.Drone(droneScale);
            drone.Root.transform.position = spawn;
            drone.Root.transform.rotation = Quaternion.Euler(0, Mathf.Atan2(-dir.z, dir.x) * Mathf.Rad2Deg, 0);
            var rng = new Rng(11);
            for (int i = 0; i < Drops; i++) { jx[i] = (rng.Next() - 0.5f) * droneScale * 0.5f; jz[i] = (rng.Next() - 0.5f) * droneScale * 0.5f; }
            ring = new TerrainDecal(c.Root, FxKit.AlphaBase, "StandoffRing");

            var g = new GameObject("DroneGuide");
            g.transform.SetParent(c.Root, false);
            guide = g.AddComponent<LineRenderer>();
            guide.material = new Material(FxKit.AlphaBase);
            guide.material.SetTexture("_BaseMap", Texture2D.whiteTexture);
            guide.positionCount = 2;
            guide.widthMultiplier = Mathf.Max(droneScale * 0.05f, 0.2f);
            guide.shadowCastingMode = ShadowCastingMode.Off;
            guide.receiveShadows = false;
        }

        public override void Tick(FxContext c, float dt, float t)
        {
            Camera cam = c.Cam;
            float u = Mathf.Clamp01(t / Fly), e = FxKit.EaseInOut(u);
            Vector3 p = Vector3.Lerp(spawn, standoff, e);
            if (u >= 1f) p.y += Mathf.Sin(t * 2.2f) * 0.12f * scale;
            var tr = drone.Root.transform;
            tr.position = p;
            float roll = u < 1f ? -0.22f * (1f - u) * Mathf.Rad2Deg : Mathf.Sin(t * 1.7f) * 0.03f * Mathf.Rad2Deg;
            tr.rotation = Quaternion.Euler(Mathf.Sin(t * 1.3f) * 1.7f * (u >= 1f ? 1f : 0f), Mathf.Atan2(-dir.z, dir.x) * Mathf.Rad2Deg, roll);
            drone.Spin(dt, t, 3200f);

            float arrive = Mathf.Clamp01((t - Fly * 0.8f) / 0.8f);
            Color amber = new Color(0.98f, 0.75f, 0.14f);
            guide.startColor = guide.endColor = new Color(amber.r, amber.g, amber.b, 0.75f * arrive);
            guide.SetPosition(0, p);
            guide.SetPosition(1, new Vector3(p.x, c.GroundY(p.x, p.z) + 0.3f, p.z));
            Color32 ringC = FxKit.Rgba(amber, 0.85f * arrive);
            ring.Set(c.Field, c.Exag, new Vector2(fire.x, fire.z), Mathf.Max(standoffDist - scale * 0.25f, 0.1f), standoffDist + scale * 0.25f, ringC, ringC, 0.4f);

            float start = Fly + Settle;
            Vector3 nozzle = new Vector3(standoff.x + dir.x * scale * 0.4f, standoff.y - scale * 0.4f, standoff.z + dir.z * scale * 0.4f);
            float fadeOut = 1f - Mathf.Clamp01((t - (start + Spray + Fall)) / 0.8f);
            for (int i = 0; i < Drops; i++)
            {
                float age = t - (start + i / (float)Drops * Spray);
                float k = age / Fall;
                if (k < 0f || k > 1f) continue;
                float px = Mathf.Lerp(nozzle.x, fire.x, k) + jx[i] * (0.3f + k);
                float pz = Mathf.Lerp(nozzle.z, fire.z, k) + jz[i] * (0.3f + k);
                float py = nozzle.y - (nozzle.y - fire.y) * k * k;
                float sz = scale * 0.5f;
                c.Glow.Add(cam, new Vector3(px, py, pz), sz, sz, new Color32(143, 211, 255, (byte)(240 * fadeOut)));
            }

            bool arriving = t > start + Fall && t < start + Spray + Fall;
            for (int i = 0; i < 6; i++)
            {
                float age = (t * 0.9f + i / 6f) % 1f;
                float a = arriving ? 0.5f * Mathf.Sin(Mathf.PI * age) : 0f;
                float size = scale * (3f + age * 6f);
                c.Smoke.Add(cam, new Vector3(fire.x + (i - 2.5f) * scale * 0.6f, fire.y + scale * 1.2f + age * scale * 5f, fire.z + Mathf.Sin(i * 2f) * scale), size, size, new Color32(219, 234, 254, (byte)(255f * a)));
            }
        }

        public override void Dispose()
        {
            drone.Destroy();
            ring.Destroy();
            if (guide != null) Object.Destroy(guide.gameObject);
        }
    }

    // ------------------------------------------------------------------ explosion

    /// <summary>
    /// Flash, fireball, expanding shock ring with a dust wave, debris and a rising smoke column with a cap. The three
    /// damage-band rings (light, moderate, severe) appear as the shock front passes and stay on the terrain.
    /// </summary>
    public sealed class ExplosionEffect : ScenarioEffect
    {
        struct Ball { public Vector2 O; public float Size, Delay; public bool Hot; }
        struct Debris { public Vector2 V; public float Vy, Delay; }
        struct Smoke { public bool Cap; public float Delay, Size, Ox, Oz, Phase; }

        static readonly Color[] BandColors = { new Color(1f, 0.92f, 0.2f), new Color(1f, 0.55f, 0.1f), new Color(0.9f, 0.1f, 0.1f) };

        readonly Vector2 centre;
        readonly float[] radii; // light, moderate, severe (metres)
        readonly float outer, core, groundY;
        readonly Ball[] balls = new Ball[7];
        readonly Debris[] debris = new Debris[120];
        readonly Smoke[] smoke = new Smoke[18];
        readonly TerrainDecal shock, scorch;
        readonly TerrainDecal[] fills = new TerrainDecal[3], lines = new TerrainDecal[3];

        public ExplosionEffect(FxContext c, Vector2 centre, float[] radii)
        {
            this.centre = centre;
            this.radii = radii;
            outer = Mathf.Max(radii[0], Mathf.Max(radii[1], radii[2]));
            core = Mathf.Max(Mathf.Min(radii[0], Mathf.Min(radii[1], radii[2])), 2f);
            groundY = c.GroundY(centre.x, centre.y);
            var rng = new Rng(5);
            for (int i = 0; i < balls.Length; i++)
                balls[i] = new Ball { O = new Vector2(rng.Next() - 0.5f, rng.Next() - 0.5f) * core * 0.5f, Size = core * (0.9f + rng.Next() * 0.9f), Delay = rng.Next() * 0.25f, Hot = i % 2 == 1 };
            for (int i = 0; i < debris.Length; i++)
            {
                float a = rng.Next() * Mathf.PI * 2f, sp = core * (0.6f + rng.Next() * 1.5f);
                debris[i] = new Debris { V = new Vector2(Mathf.Cos(a), Mathf.Sin(a)) * sp, Vy = core * (1.4f + rng.Next() * 2.4f), Delay = rng.Next() * 0.15f };
            }
            for (int i = 0; i < smoke.Length; i++)
            {
                bool cap = i >= 11;
                smoke[i] = new Smoke { Cap = cap, Delay = 0.4f + i * 0.13f, Ox = (rng.Next() - 0.5f) * core * 0.35f, Oz = (rng.Next() - 0.5f) * core * 0.35f, Phase = rng.Next() * 6.28f, Size = core * (cap ? 1.6f + rng.Next() * 0.9f : 0.8f + rng.Next() * 0.5f) };
            }
            shock = new TerrainDecal(c.Root, FxKit.AddBase, "Shock");
            scorch = new TerrainDecal(c.Root, FxKit.AlphaBase, "BlastScorch");
            for (int i = 0; i < 3; i++)
            {
                fills[i] = new TerrainDecal(c.Root, FxKit.AlphaBase, "DamageFill" + i);
                lines[i] = new TerrainDecal(c.Root, FxKit.AlphaBase, "DamageRing" + i);
            }
        }

        public override void Tick(FxContext c, float dt, float t)
        {
            Camera cam = c.Cam;
            Vector3 origin = new Vector3(centre.x, groundY, centre.y);

            // flash
            float flash = 1f - Mathf.Clamp01(t / 0.45f);
            float flashSize = core * (3f + 5f * FxKit.EaseOut(t / 0.45f));
            c.Glow.Add(cam, origin + Vector3.up * core * 0.3f, flashSize, flashSize, new Color32(255, 244, 214, (byte)(255f * flash)));

            // fireball
            foreach (Ball b in balls)
            {
                float u = Mathf.Clamp01((t - b.Delay) / 1.7f), grow = FxKit.EaseOut(u);
                if (t < b.Delay) continue;
                Color hot = Color.Lerp(new Color(1f, 0.88f, 0.54f), new Color(0.85f, 0.26f, 0.04f), Mathf.Clamp01(u * 1.3f));
                if (b.Hot) hot = Color.Lerp(hot, new Color(1f, 0.55f, 0.1f), 0.4f);
                float size = b.Size * (0.3f + 1.2f * grow);
                float a = 0.95f * (1f - Mathf.Clamp01((u - 0.45f) / 0.55f));
                c.Glow.Add(cam, origin + new Vector3(b.O.x * grow, core * (0.25f + 0.9f * u), b.O.y * grow), size, size, FxKit.Rgba(hot, a));
            }

            // shock ring + dust wave
            float shockR = outer * FxKit.EaseOut(t / 2.0f);
            float shockA = 0.9f * (1f - Mathf.Clamp01(t / 2.0f));
            if (shockA > 0.01f && shockR > 0.5f)
                shock.Set(c.Field, c.Exag, centre, Mathf.Max(shockR - Mathf.Max(outer * 0.05f, 1.5f), 0f), shockR, FxKit.Rgba(new Color(1f, 0.88f, 0.54f), 0f), FxKit.Rgba(new Color(1f, 0.88f, 0.54f), shockA), 0.6f);
            else shock.Hide();
            float dust = 1f - Mathf.Clamp01(t / 2.4f);
            for (int i = 0; i < 28; i++)
            {
                float a = i / 28f * Mathf.PI * 2f;
                float x = centre.x + Mathf.Cos(a) * shockR, z = centre.y + Mathf.Sin(a) * shockR;
                float size = core * (0.9f + 1.4f * t / 2f);
                c.Smoke.Add(cam, new Vector3(x, c.GroundY(x, z) + size * 0.25f, z), size, size * 0.8f, new Color32(150, 132, 108, (byte)(255f * 0.4f * dust * (t > 0.05f ? 1f : 0f))));
            }

            // debris
            float g = core * 3.4f;
            foreach (Debris d in debris)
            {
                float a = t - d.Delay;
                if (a < 0f || a > 3.2f) continue;
                float y = Mathf.Max(d.Vy * a - 0.5f * g * a * a, 0f);
                float fade = 1f - Mathf.Clamp01((t - 1.8f) / 1.4f);
                float sz = Mathf.Max(core * 0.05f, 0.6f);
                c.Glow.Add(cam, origin + new Vector3(d.V.x * a * 0.7f, y, d.V.y * a * 0.7f), sz, sz, new Color32(255, 160, 64, (byte)(255f * fade)));
            }

            // smoke column with a cap
            foreach (Smoke s in smoke)
            {
                float u = Mathf.Clamp01((t - s.Delay) / 6f);
                if (t < s.Delay) continue;
                float rise = FxKit.EaseOut(u);
                float height = s.Cap ? core * (3.2f + 0.5f * u) * rise : core * (0.4f + 2.8f * (0.35f + 0.65f * rise) * ((s.Delay - 0.4f) / 2.4f + 0.2f)) * (0.4f + 0.6f * rise);
                float spread = s.Cap ? core * 1.2f * rise : 0f;
                Vector3 p = origin + new Vector3(s.Ox + Mathf.Cos(s.Phase) * spread, height, s.Oz + Mathf.Sin(s.Phase) * spread);
                float size = s.Size * (0.5f + 1.3f * rise);
                float a = 0.55f * Mathf.Sin(Mathf.PI * Mathf.Pow(u, 0.7f));
                byte gr = (byte)Mathf.Lerp(58f, 138f, u);
                c.Smoke.Add(cam, p, size, size, new Color32(gr, (byte)(gr - 4), (byte)(gr - 8), (byte)(255f * a)));
            }

            scorch.Set(c.Field, c.Exag, centre, 0f, core * 0.9f, FxKit.Rgba(new Color(0.07f, 0.04f, 0.03f), 0.6f * Mathf.Clamp01((t - 0.3f) / 1.5f)), FxKit.Rgba(new Color(0.07f, 0.04f, 0.03f), 0f), 0.25f);

            // damage rings appear as the shock front reaches them, and stay
            for (int i = 0; i < 3; i++)
            {
                float reveal = Mathf.Clamp01((shockR - radii[i]) / Mathf.Max(radii[i] * 0.08f, 0.5f) + (t > 1.9f ? 1f : 0f));
                if (reveal <= 0.001f) continue;
                Color col = BandColors[i];
                fills[i].Set(c.Field, c.Exag, centre, 0f, radii[i], FxKit.Rgba(col, 0.1f * reveal), FxKit.Rgba(col, 0.16f * reveal), 0.3f);
                lines[i].Set(c.Field, c.Exag, centre, radii[i] * 0.985f, radii[i] * 1.01f, FxKit.Rgba(col, 0.95f * reveal), FxKit.Rgba(col, 0.95f * reveal), 0.5f);
            }
        }

        public override void Dispose()
        {
            shock.Destroy();
            scorch.Destroy();
            for (int i = 0; i < 3; i++) { fills[i].Destroy(); lines[i].Destroy(); }
        }
    }

    // ------------------------------------------------------------------ landing

    public enum AircraftKind { Drone, Helicopter, Plane }

    /// <summary>
    /// An aircraft flies the approach and lands on a marked pad (rotor spool-down, dust wash). A fixed-wing plane on a pad
    /// that is too short flies the approach and goes around instead.
    /// </summary>
    public sealed class LandingEffect : ScenarioEffect
    {
        readonly Vehicle vehicle;
        readonly AircraftKind kind;
        readonly Vector2 centre;
        readonly float radius, groundY, approach, startH, hoverH, restY, scale;
        readonly Vector3 hv;
        readonly bool goAround;
        readonly float tApproach, tDown;
        readonly TerrainDecal fill, ring, inner;
        readonly Color fitColor;

        public LandingEffect(FxContext c, Vector2 centre, float radius, float bearingDeg, AircraftKind kind, bool? fits)
        {
            this.centre = centre; this.radius = radius; this.kind = kind;
            groundY = c.GroundY(centre.x, centre.y);
            float b = bearingDeg * Mathf.Deg2Rad;
            hv = new Vector3(Mathf.Sin(b), 0f, Mathf.Cos(b)); // compass bearing: 0 = north (+z), 90 = east (+x)
            fitColor = fits == false ? new Color(0.94f, 0.27f, 0.27f) : fits == true ? new Color(0.13f, 0.77f, 0.37f) : new Color(0.22f, 0.74f, 0.97f);

            float realLength = kind == AircraftKind.Helicopter ? 13f : kind == AircraftKind.Plane ? 8f : 1.6f;
            float minVisible = c.Diagonal * 0.011f;
            scale = Mathf.Max(1f, minVisible / realLength);
            vehicle = kind == AircraftKind.Helicopter ? Vehicle.Helicopter(scale) : kind == AircraftKind.Plane ? Vehicle.Plane(scale) : Vehicle.Drone(scale);
            vehicle.Root.transform.rotation = Quaternion.Euler(0, Mathf.Atan2(-hv.z, hv.x) * Mathf.Rad2Deg, 0);

            approach = Mathf.Max(radius * 5f, 60f);
            startH = Mathf.Max(40f, scale * 6f);
            hoverH = kind == AircraftKind.Plane ? scale * 1.2f : Mathf.Max(3.5f, scale * 1.6f);
            restY = kind == AircraftKind.Helicopter ? 1.28f * scale : kind == AircraftKind.Drone ? 0.6f * scale : 0.8f * scale;
            goAround = kind == AircraftKind.Plane && fits != true;
            tApproach = kind == AircraftKind.Plane ? 5.2f : 4.4f;
            tDown = 2.4f;

            fill = new TerrainDecal(c.Root, FxKit.AlphaBase, "PadFill");
            ring = new TerrainDecal(c.Root, FxKit.AlphaBase, "PadRing");
            inner = new TerrainDecal(c.Root, FxKit.AlphaBase, "PadMark");
        }

        public override void Tick(FxContext c, float dt, float t)
        {
            float pulse = 0.5f + 0.5f * Mathf.Sin(t * 4f);
            fill.Set(c.Field, c.Exag, centre, 0f, radius, FxKit.Rgba(fitColor, 0.12f + 0.06f * pulse), FxKit.Rgba(fitColor, 0.16f), 0.3f);
            ring.Set(c.Field, c.Exag, centre, radius * 0.93f, radius, FxKit.Rgba(fitColor, 0.65f + 0.25f * pulse), FxKit.Rgba(fitColor, 0.65f + 0.25f * pulse), 0.45f);
            inner.Set(c.Field, c.Exag, centre, radius * 0.4f, radius * 0.46f, FxKit.Rgba(Color.white, 0.8f), FxKit.Rgba(Color.white, 0.8f), 0.45f);

            Vector3 pos;
            float pitch = 0f, spin = 3000f;
            float touch = -1f;
            if (goAround)
            {
                float u = Mathf.Clamp01(t / tApproach);
                if (t <= tApproach)
                {
                    float along = Mathf.Lerp(-approach, 0f, 1f - Mathf.Pow(1f - u, 1.4f));
                    pos = new Vector3(centre.x + hv.x * along, groundY + Mathf.Lerp(startH, hoverH, FxKit.EaseOut(u)), centre.y + hv.z * along);
                    pitch = -7f;
                }
                else
                {
                    float k = t - tApproach;
                    pos = new Vector3(centre.x + hv.x * k * radius * 1.6f, groundY + hoverH + k * k * scale * 1.4f, centre.y + hv.z * k * radius * 1.6f);
                    pitch = 18f;
                }
                spin = 5000f;
            }
            else
            {
                float u = Mathf.Clamp01(t / tApproach);
                if (t <= tApproach)
                {
                    float along = Mathf.Lerp(-approach, 0f, FxKit.EaseOut(u));
                    float y = hoverH + (startH - hoverH) * Mathf.Pow(1f - u, 1.7f);
                    pos = new Vector3(centre.x + hv.x * along, groundY + y, centre.y + hv.z * along);
                    pitch = -11f * (1f - u);
                }
                else if (t <= tApproach + tDown)
                {
                    float d = FxKit.EaseInOut((t - tApproach) / tDown);
                    pos = new Vector3(centre.x, groundY + Mathf.Lerp(hoverH, restY, d), centre.y);
                    touch = 0f;
                }
                else
                {
                    pos = new Vector3(centre.x, groundY + restY, centre.y);
                    touch = t - (tApproach + tDown);
                    spin = 3000f * (1f - Mathf.Clamp01(touch / 3.2f));
                }
            }
            var tr = vehicle.Root.transform;
            tr.position = pos;
            float yaw = Mathf.Atan2(-hv.z, hv.x) * Mathf.Rad2Deg;
            float wob = kind == AircraftKind.Plane || touch >= 0f ? 0f : Mathf.Sin(t * 1.6f) * 1.1f;
            tr.rotation = Quaternion.Euler(wob, yaw, pitch);
            vehicle.Spin(dt, t, spin);

            bool washing = kind != AircraftKind.Plane && t > tApproach - 0.8f && t < tApproach + tDown + 2.2f;
            for (int i = 0; i < 14; i++)
            {
                float cyc = (t * 0.7f + i / 14f) % 1f, a = i / 14f * Mathf.PI * 2f, r = radius * (0.25f + cyc * 0.9f);
                float x = centre.x + Mathf.Cos(a) * r, z = centre.y + Mathf.Sin(a) * r;
                float size = 2.5f + cyc * 6f;
                float al = washing ? 0.32f * Mathf.Sin(Mathf.PI * cyc) : 0f;
                c.Smoke.Add(c.Cam, new Vector3(x, c.GroundY(x, z) + 0.6f + cyc * 1.6f, z), size, size, new Color32(181, 155, 122, (byte)(255f * al)));
            }
        }

        public override void Dispose()
        {
            vehicle.Destroy();
            fill.Destroy(); ring.Destroy(); inner.Destroy();
        }
    }
}
