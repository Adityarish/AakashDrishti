using System;
using System.Collections.Generic;
using AakashDrishti.Viewer.Bridge;
using AakashDrishti.Viewer.Cameras;
using AakashDrishti.Viewer.Loading;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;

namespace AakashDrishti.Viewer.Scenarios
{
    /// <summary>
    /// Runs the disaster-scenario animations on the loaded terrain. The host page drives it with JSON commands
    /// (ViewerBootstrap.RunScenario) and receives picked terrain positions back through HostBridge.
    ///
    /// Positions travel as fractions u = x / world width (east) and v = z / world depth (north), so the page
    /// needs no knowledge of the world size; distances are metres.
    /// </summary>
    public sealed class ScenarioController : MonoBehaviour
    {
        sealed class Running { public ScenarioEffect Effect; public float Start; public string Slot; }

        TerrainView terrain;
        CameraRig rig;
        Camera cam;
        FxContext ctx;
        readonly List<Running> running = new List<Running>();
        WaterEffect water;
        FireEffect fire;
        Vector2 fireAt;
        bool picking;
        float clock;

        public bool Picking => picking;

        public void Init(TerrainView terrainView, CameraRig cameraRig, Camera camera)
        {
            terrain = terrainView;
            rig = cameraRig;
            cam = camera;
        }

        /// <summary>Drop every effect; called when another scene is loaded.</summary>
        public void Clear()
        {
            foreach (Running r in running) r.Effect.Dispose();
            running.Clear();
            water = null;
            fire = null;
            picking = false;
            if (ctx != null)
            {
                ctx.Glow.Destroy(); ctx.Flame.Destroy(); ctx.Smoke.Destroy();
                if (ctx.Root != null) Destroy(ctx.Root.gameObject);
                ctx = null;
            }
        }

        bool EnsureContext()
        {
            if (terrain == null || terrain.Field == null) return false;
            if (ctx != null) return true;
            var root = new GameObject("ScenarioFx").transform;
            root.SetParent(transform, false);
            ctx = new FxContext { Terrain = terrain, Cam = cam, Root = root };
            ctx.Glow = new SpriteBatch(root, FxKit.AddBase, FxKit.Glow, 700, "GlowSprites");
            ctx.Flame = new SpriteBatch(root, FxKit.AddBase, FxKit.Flame, 200, "FlameSprites");
            ctx.Smoke = new SpriteBatch(root, FxKit.AlphaBase, FxKit.Smoke, 300, "SmokeSprites");
            return true;
        }

        // ------------------------------------------------------------------ commands from the page

        public void Run(string json)
        {
            if (string.IsNullOrEmpty(json)) return;
            Dictionary<string, object> cmd;
            try { cmd = MiniJson.Parse(json) as Dictionary<string, object>; }
            catch (FormatException e) { Debug.LogWarning("[Scenario] invalid JSON: " + e.Message); return; }
            if (cmd == null || !EnsureContext() && Str(cmd, "cmd") != "clear") return;

            switch (Str(cmd, "cmd"))
            {
                case "clear": Clear(); break;
                case "pick": picking = Bool(cmd, "on", true); break;
                case "water": SetWater(cmd); break;
                case "pin": ShowPin(cmd); break;
                case "explosion": Explode(cmd); break;
                case "fire": Ignite(cmd); break;
                case "drop": DropWater(cmd); break;
                case "landing": Land(cmd); break;
                case "focus": Focus(cmd); break;
                default: Debug.LogWarning("[Scenario] unknown command: " + Str(cmd, "cmd")); break;
            }
        }

        /// <summary>Called by the viewer when the user clicks the terrain while picking; reports u,v to the page.</summary>
        public bool TryPick(Vector3 worldPoint)
        {
            if (!picking || terrain == null || terrain.Field == null) return false;
            picking = false;
            Vector3 local = terrain.WorldRoot.InverseTransformPoint(worldPoint);
            HostBridge.Picked(Mathf.Clamp01(local.x / terrain.Field.SizeX), Mathf.Clamp01(local.z / terrain.Field.SizeZ));
            return true;
        }

        // ------------------------------------------------------------------ scenario setup

        Vector2 At(Dictionary<string, object> cmd) => new Vector2(Mathf.Clamp01(Num(cmd, "u", 0.5f)) * terrain.Field.SizeX, Mathf.Clamp01(Num(cmd, "v", 0.5f)) * terrain.Field.SizeZ);

        void Replace(string slot, ScenarioEffect effect)
        {
            for (int i = running.Count - 1; i >= 0; i--)
                if (running[i].Slot == slot) { running[i].Effect.Dispose(); running.RemoveAt(i); }
            running.Add(new Running { Effect = effect, Start = clock, Slot = slot });
        }

        void Remove(string slot)
        {
            for (int i = running.Count - 1; i >= 0; i--)
                if (running[i].Slot == slot) { running[i].Effect.Dispose(); running.RemoveAt(i); }
        }

        void SetWater(Dictionary<string, object> cmd)
        {
            if (!cmd.TryGetValue("level", out object lv) || !(lv is double))
            {
                Remove("water");
                water = null;
                return;
            }
            float level = (float)(double)lv;
            if (water == null)
            {
                water = new WaterEffect(ctx, level);
                Replace("water", water);
            }
            water.Level = level;
        }

        void ShowPin(Dictionary<string, object> cmd)
        {
            if (!Bool(cmd, "on", true)) { Remove("pin"); return; }
            Replace("pin", new PinEffect(ctx, At(cmd), new Color(0.9f, 0.1f, 0.1f)));
        }

        void Explode(Dictionary<string, object> cmd)
        {
            Remove("pin");
            float[] radii = { 30f, 15f, 8f };
            if (cmd.TryGetValue("radii", out object r) && r is List<object> l && l.Count >= 3)
                for (int i = 0; i < 3; i++) radii[i] = Mathf.Max(1f, (float)(l[i] is double d ? d : 1.0));
            Replace("explosion", new ExplosionEffect(ctx, At(cmd), radii));
        }

        void Ignite(Dictionary<string, object> cmd)
        {
            Remove("pin");
            Remove("drop");
            fireAt = At(cmd);
            float radius = Mathf.Max(7f, ctx.Diagonal * 0.008f);
            fire = new FireEffect(ctx, fireAt, radius);
            Replace("fire", fire);
        }

        void DropWater(Dictionary<string, object> cmd)
        {
            if (fire == null) { Ignite(cmd); }
            float hover = Num(cmd, "hover", 30f), reach = Num(cmd, "reach", 40f);
            HeightField f = terrain.Field;
            Vector2 at = fireAt;
            float groundY = ctx.GroundY(at.x, at.y);
            Vector3 fireGround = new Vector3(at.x, groundY, at.y);

            // stand off on whichever side keeps the drone over the terrain
            Vector3 dir = Vector3.right;
            for (int k = 0; k < 8; k++)
            {
                float a = Mathf.PI * 0.25f + k * Mathf.PI * 0.25f;
                Vector3 cand = new Vector3(Mathf.Cos(a), 0f, Mathf.Sin(a));
                float x = at.x + cand.x * reach, z = at.y + cand.z * reach;
                if (x > f.SizeX * 0.02f && x < f.SizeX * 0.98f && z > f.SizeZ * 0.02f && z < f.SizeZ * 0.98f) { dir = cand; break; }
            }
            Vector3 standoff = new Vector3(at.x + dir.x * reach, groundY + hover, at.y + dir.z * reach);
            float away = Mathf.Max(reach * 0.9f, ctx.Diagonal * 0.18f);
            Vector3 spawn = new Vector3(standoff.x + dir.x * away, standoff.y + ctx.Diagonal * 0.12f, standoff.z + dir.z * away);
            float droneScale = Mathf.Max(1.2f, ctx.Diagonal * 0.009f);

            var effect = new DroneDropEffect(ctx, fireGround, standoff, spawn, droneScale);
            Replace("drop", effect);
            fire.Ignite();
            fire.Douse(effect.FirstHitAfter, 4.5f);
        }

        void Land(Dictionary<string, object> cmd)
        {
            string k = Str(cmd, "kind");
            AircraftKind kind = k == "plane" ? AircraftKind.Plane : k == "drone" ? AircraftKind.Drone : AircraftKind.Helicopter;
            bool? fits = cmd.TryGetValue("fits", out object fv) && fv is bool b ? b : (bool?)null;
            Replace("landing", new LandingEffect(ctx, At(cmd), Mathf.Max(2f, Num(cmd, "radius", 15f)), Num(cmd, "bearing", 0f), kind, fits));
        }

        void Focus(Dictionary<string, object> cmd)
        {
            Vector2 at = At(cmd);
            float dist = Num(cmd, "distance", 0.3f) * ctx.Diagonal;
            rig.FocusOn(new Vector3(at.x, 0f, at.y), dist);
        }

        // ------------------------------------------------------------------ frame

        void LateUpdate()
        {
            if (ctx == null || terrain == null || terrain.Field == null) return;
            float dt = Time.deltaTime;
            clock += dt;
            ctx.Glow.Begin(); ctx.Flame.Begin(); ctx.Smoke.Begin();
            foreach (Running r in running) r.Effect.Tick(ctx, dt, clock - r.Start);
            ctx.Glow.End(); ctx.Flame.End(); ctx.Smoke.End();
        }

        // ------------------------------------------------------------------ json helpers

        static string Str(Dictionary<string, object> d, string key) => d.TryGetValue(key, out object v) && v is string s ? s : null;
        static float Num(Dictionary<string, object> d, string key, float fallback) => d.TryGetValue(key, out object v) && v is double n ? (float)n : fallback;
        static bool Bool(Dictionary<string, object> d, string key, bool fallback) => d.TryGetValue(key, out object v) && v is bool b ? b : fallback;
    }
}
