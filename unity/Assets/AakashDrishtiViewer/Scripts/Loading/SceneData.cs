using System;
using System.Collections.Generic;
using UnityEngine;

namespace AakashDrishti.Viewer.Loading
{
    /// <summary>User-facing load failure (bad data, missing file, unreachable backend).</summary>
    public sealed class ViewerLoadException : Exception
    {
        public ViewerLoadException(string message) : base(message) { }
    }

    public enum ZoneLevel { Low, Medium, High }

    public sealed class BuildingData
    {
        public int Id;
        public float HeightM;
        /// <summary>(x = east, y = north) in meters, origin at the terrain's bottom-left corner.</summary>
        public Vector2[] Footprint;
        /// <summary>Mean photo colour inside the footprint (the real roof colour); null when the scene has none.</summary>
        public Color32? RoofColor;
    }

    public enum ObjectKind { Vehicle, Truck, Tank, Pool, Slab, Aircraft, Ship, Box }

    /// <summary>A detected object (car, truck, pool, tank...) with real size, heading and photo colour.</summary>
    public sealed class ObjectData
    {
        public int Id;
        public ObjectKind Kind;
        /// <summary>(x = east, y = north) in meters.</summary>
        public Vector2 Center;
        /// <summary>Counter-clockwise from east toward north, in degrees.</summary>
        public float YawDeg;
        public float Length, Width, Height;
        public Color32 Color;
        /// <summary>Bare-earth elevation under the object in meters, or NaN when unknown.</summary>
        public float BaseM = float.NaN;
    }

    public sealed class TreeData
    {
        public Vector2 Position;
        public float HeightM;
        public float CrownRadiusM;
        public Color32 Color;
        public float BaseM = float.NaN;
    }

    public sealed class ZoneData
    {
        public int Id;
        public ZoneLevel Level;
        public Vector2[] Polygon;
    }

    /// <summary>Parsed unity_scene.json.</summary>
    public sealed class SceneData
    {
        public string JobId;
        public string HeightmapFile;
        public int HeightmapWidth;
        public int HeightmapHeight;
        public float MinM;
        public float MaxM;
        public string TextureFile;
        public float WorldSizeX;
        public float WorldSizeZ;
        public bool IsMetric;
        public readonly List<BuildingData> Buildings = new List<BuildingData>();
        public readonly List<ZoneData> Zones = new List<ZoneData>();
        public readonly List<ObjectData> Objects = new List<ObjectData>();
        public readonly List<TreeData> Trees = new List<TreeData>();
        public int SkippedBuildings;
        public int SkippedZones;

        public static SceneData Parse(string json)
        {
            object root;
            try { root = MiniJson.Parse(json); }
            catch (FormatException e) { throw new ViewerLoadException("unity_scene.json is not valid JSON: " + e.Message); }

            var obj = root as Dictionary<string, object>;
            if (obj == null) throw new ViewerLoadException("unity_scene.json must contain a JSON object.");

            var d = new SceneData();
            d.JobId = GetString(obj, "job_id", null) ?? "";

            var hm = GetObject(obj, "heightmap", "unity_scene.json");
            d.HeightmapFile = GetString(hm, "file", "heightmap");
            d.HeightmapWidth = (int)GetNumber(hm, "width", "heightmap");
            d.HeightmapHeight = (int)GetNumber(hm, "height", "heightmap");
            d.MinM = (float)GetNumber(hm, "min_m", "heightmap");
            d.MaxM = (float)GetNumber(hm, "max_m", "heightmap");
            if (d.HeightmapWidth < 2 || d.HeightmapHeight < 2)
                throw new ViewerLoadException($"heightmap size {d.HeightmapWidth}x{d.HeightmapHeight} is invalid (must be at least 2x2).");
            if (d.MaxM < d.MinM)
                throw new ViewerLoadException($"heightmap max_m ({d.MaxM}) is smaller than min_m ({d.MinM}).");

            if (obj.TryGetValue("texture", out object texObj) && texObj is Dictionary<string, object> tex)
                d.TextureFile = GetString(tex, "file", null);

            var ws = GetObject(obj, "world_size_m", "unity_scene.json");
            d.WorldSizeX = (float)GetNumber(ws, "x", "world_size_m");
            d.WorldSizeZ = (float)GetNumber(ws, "z", "world_size_m");
            if (!(d.WorldSizeX > 0f) || !(d.WorldSizeZ > 0f))
                throw new ViewerLoadException("world_size_m must be positive in both axes.");

            // Missing flag = treat heights as relative, the safer assumption.
            d.IsMetric = obj.TryGetValue("is_metric", out object metric) && metric is bool b && b;

            if (obj.TryGetValue("buildings", out object bl) && bl is List<object> blist)
                foreach (object o in blist) ParseBuilding(o, d);

            if (obj.TryGetValue("disaster_zones", out object zl) && zl is List<object> zlist)
                foreach (object o in zlist) ParseZone(o, d);

            // Optional: scenes written before objects/trees existed simply have neither.
            if (obj.TryGetValue("objects", out object ol) && ol is List<object> olist)
                foreach (object o in olist) ParseObject(o, d);

            if (obj.TryGetValue("trees", out object tl) && tl is List<object> tlist)
                foreach (object o in tlist) ParseTree(o, d);

            return d;
        }

        static void ParseBuilding(object o, SceneData d)
        {
            var b = o as Dictionary<string, object>;
            Vector2[] ring = b != null && b.TryGetValue("footprint", out object f) ? ParseRing(f) : null;
            if (b == null || ring == null || ring.Length < 3) { d.SkippedBuildings++; return; }
            float h = b.TryGetValue("height_m", out object ho) && ho is double hd ? (float)hd : 0f;
            if (float.IsNaN(h) || float.IsInfinity(h)) h = 0f;
            d.Buildings.Add(new BuildingData
            {
                Id = b.TryGetValue("id", out object id) && id is double idd ? (int)idd : d.Buildings.Count + 1,
                HeightM = Mathf.Max(h, 0.5f),
                Footprint = ring,
                RoofColor = b.TryGetValue("color_rgb", out object rc) ? ParseColor(rc) : null,
            });
        }

        static void ParseObject(object o, SceneData d)
        {
            var e = o as Dictionary<string, object>;
            if (e == null || !e.TryGetValue("center", out object c) || !TryPair(c, out Vector2 center)) return;
            if (!e.TryGetValue("size_m", out object so) || !(so is Dictionary<string, object> size)) return; // old scenes: outline only
            float len = Num(size, "length"), wid = Num(size, "width"), hgt = Num(size, "height");
            if (!(len > 0f) || !(wid > 0f) || !(hgt > 0f)) return;
            string kind = e.TryGetValue("kind", out object k) ? k as string : null;
            d.Objects.Add(new ObjectData
            {
                Id = e.TryGetValue("id", out object id) && id is double idd ? (int)idd : d.Objects.Count + 1,
                Kind = kind == "vehicle" ? ObjectKind.Vehicle : kind == "truck" ? ObjectKind.Truck : kind == "tank" ? ObjectKind.Tank
                     : kind == "pool" ? ObjectKind.Pool : kind == "slab" ? ObjectKind.Slab : kind == "aircraft" ? ObjectKind.Aircraft
                     : kind == "ship" ? ObjectKind.Ship : ObjectKind.Box,
                Center = center,
                YawDeg = Num(e, "yaw_deg"),
                Length = len, Width = wid, Height = hgt,
                Color = (e.TryGetValue("color_rgb", out object rc) ? ParseColor(rc) : null) ?? new Color32(150, 150, 150, 255),
                BaseM = e.TryGetValue("base_m", out object bm) && bm is double bd ? (float)bd : float.NaN,
            });
        }

        static void ParseTree(object o, SceneData d)
        {
            var e = o as Dictionary<string, object>;
            if (e == null || !e.TryGetValue("position", out object p) || !TryPair(p, out Vector2 pos)) return;
            float h = Num(e, "height_m"), r = Num(e, "crown_radius_m");
            if (!(h > 0f) || !(r > 0f)) return;
            d.Trees.Add(new TreeData
            {
                Position = pos, HeightM = h, CrownRadiusM = r,
                Color = (e.TryGetValue("color_rgb", out object rc) ? ParseColor(rc) : null) ?? new Color32(70, 100, 55, 255),
                BaseM = e.TryGetValue("base_m", out object bm) && bm is double bd ? (float)bd : float.NaN,
            });
        }

        static float Num(Dictionary<string, object> d, string key) =>
            d.TryGetValue(key, out object v) && v is double n && !double.IsNaN(n) && !double.IsInfinity(n) ? (float)n : 0f;

        static bool TryPair(object o, out Vector2 v)
        {
            v = default;
            var l = o as List<object>;
            if (l == null || l.Count < 2 || !(l[0] is double x) || !(l[1] is double z)) return false;
            if (double.IsNaN(x) || double.IsInfinity(x) || double.IsNaN(z) || double.IsInfinity(z)) return false;
            v = new Vector2((float)x, (float)z);
            return true;
        }

        /// <summary>[r,g,b] 0-255 to Color32; null when malformed.</summary>
        static Color32? ParseColor(object o)
        {
            var l = o as List<object>;
            if (l == null || l.Count < 3 || !(l[0] is double r) || !(l[1] is double g) || !(l[2] is double b)) return null;
            return new Color32((byte)Mathf.Clamp((float)r, 0f, 255f), (byte)Mathf.Clamp((float)g, 0f, 255f), (byte)Mathf.Clamp((float)b, 0f, 255f), 255);
        }

        static void ParseZone(object o, SceneData d)
        {
            var z = o as Dictionary<string, object>;
            Vector2[] ring = z != null && z.TryGetValue("polygon", out object p) ? ParseRing(p) : null;
            if (z == null || ring == null || ring.Length < 3) { d.SkippedZones++; return; }
            string level = z.TryGetValue("level", out object lo) ? lo as string : null;
            d.Zones.Add(new ZoneData
            {
                Id = z.TryGetValue("id", out object id) && id is double idd ? (int)idd : d.Zones.Count + 1,
                Level = level == "high" ? ZoneLevel.High : level == "medium" ? ZoneLevel.Medium : ZoneLevel.Low,
                Polygon = ring,
            });
        }

        /// <summary>[[x,z],...] to Vector2[]; returns null for malformed or non-finite input.</summary>
        static Vector2[] ParseRing(object o)
        {
            var list = o as List<object>;
            if (list == null) return null;
            var pts = new Vector2[list.Count];
            for (int i = 0; i < list.Count; i++)
            {
                var pair = list[i] as List<object>;
                if (pair == null || pair.Count < 2 || !(pair[0] is double x) || !(pair[1] is double z)) return null;
                if (double.IsNaN(x) || double.IsInfinity(x) || double.IsNaN(z) || double.IsInfinity(z)) return null;
                pts[i] = new Vector2((float)x, (float)z);
            }
            return pts;
        }

        static Dictionary<string, object> GetObject(Dictionary<string, object> parent, string key, string where)
        {
            if (parent.TryGetValue(key, out object v) && v is Dictionary<string, object> o) return o;
            throw new ViewerLoadException($"{where} is missing the '{key}' object.");
        }

        static double GetNumber(Dictionary<string, object> parent, string key, string where)
        {
            if (parent.TryGetValue(key, out object v) && v is double n && !double.IsNaN(n) && !double.IsInfinity(n)) return n;
            throw new ViewerLoadException($"'{where}.{key}' is missing or not a number.");
        }

        static string GetString(Dictionary<string, object> parent, string key, string where)
        {
            if (parent.TryGetValue(key, out object v) && v is string s && s.Length > 0) return s;
            if (where == null) return null;
            throw new ViewerLoadException($"'{where}.{key}' is missing or not a string.");
        }
    }
}
