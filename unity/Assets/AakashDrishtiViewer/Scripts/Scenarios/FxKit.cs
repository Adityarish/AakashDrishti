using System;
using System.Collections.Generic;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace AakashDrishti.Viewer.Scenarios
{
    /// <summary>Shared materials, procedural textures and small math helpers for the scenario effects.</summary>
    public static class FxKit
    {
        const string Folder = "AakashDrishtiViewer/";
        static Material addBase, alphaBase, waterBase, litBase;
        static Texture2D glow, smoke, flame;
        static readonly Dictionary<int, Material> litCache = new Dictionary<int, Material>();

        public static Material AddBase => addBase != null ? addBase : addBase = Resources.Load<Material>(Folder + "FxAdd");
        public static Material AlphaBase => alphaBase != null ? alphaBase : alphaBase = Resources.Load<Material>(Folder + "FxAlpha");
        public static Material WaterBase => waterBase != null ? waterBase : waterBase = Resources.Load<Material>(Folder + "Water");
        static Material LitBase => litBase != null ? litBase : litBase = Resources.Load<Material>(Folder + "Building");

        public static Texture2D Glow => glow != null ? glow : glow = MakeTexture(64, 64, (u, v) =>
        {
            float d = Mathf.Sqrt((u - 0.5f) * (u - 0.5f) + (v - 0.5f) * (v - 0.5f)) * 2f;
            return Mathf.Pow(Mathf.Clamp01(1f - d), 1.7f);
        });

        public static Texture2D Smoke => smoke != null ? smoke : smoke = MakeTexture(64, 64, (u, v) =>
        {
            float d = Mathf.Sqrt((u - 0.5f) * (u - 0.5f) + (v - 0.5f) * (v - 0.5f)) * 2f;
            float soft = Mathf.SmoothStep(1f, 0f, d);
            float n = 0.85f + 0.15f * Mathf.Sin(u * 17f) * Mathf.Sin(v * 13f);
            return soft * n;
        });

        /// <summary>Teardrop flame, opaque at the base and fading to the tip.</summary>
        public static Texture2D Flame => flame != null ? flame : flame = MakeTexture(48, 96, (u, v) =>
        {
            // v = 0 is the base; the half-width follows a bulb that narrows to a point at the top
            float half = Mathf.Sin(Mathf.Clamp01(v * 1.05f) * Mathf.PI * 0.92f) * (1f - v * 0.55f) * 0.5f;
            float dx = Mathf.Abs(u - 0.5f);
            if (half <= 0.001f || dx > half) return 0f;
            float edge = 1f - Mathf.Pow(dx / half, 2f);
            float fade = 1f - Mathf.Pow(v, 1.6f) * 0.85f;
            return Mathf.Clamp01(edge * fade * 1.15f);
        });

        static Texture2D MakeTexture(int w, int h, Func<float, float, float> alphaAt)
        {
            var tex = new Texture2D(w, h, TextureFormat.RGBA32, false, false) { wrapMode = TextureWrapMode.Clamp, filterMode = FilterMode.Bilinear };
            var px = new Color32[w * h];
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                {
                    byte a = (byte)Mathf.RoundToInt(Mathf.Clamp01(alphaAt((x + 0.5f) / w, (y + 0.5f) / h)) * 255f);
                    px[y * w + x] = new Color32(255, 255, 255, a);
                }
            tex.SetPixels32(px);
            tex.Apply(false, true);
            return tex;
        }

        /// <summary>Opaque lit material (the viewer's SimpleLit shader) in a given colour, cached.</summary>
        public static Material Lit(Color c)
        {
            int key = ((Color32)c).GetHashCode();
            if (litCache.TryGetValue(key, out Material m) && m != null) return m;
            m = new Material(LitBase);
            m.SetColor("_BaseColor", c);
            litCache[key] = m;
            return m;
        }

        public static float Ease(float t) => t * t * (3f - 2f * t);
        public static float EaseOut(float t) { t = Mathf.Clamp01(t); return 1f - Mathf.Pow(1f - t, 3f); }
        public static float EaseInOut(float t) { t = Mathf.Clamp01(t); return t < 0.5f ? 4f * t * t * t : 1f - Mathf.Pow(-2f * t + 2f, 3f) / 2f; }
        public static float EaseOutBack(float t) { t = Mathf.Clamp01(t); const float c1 = 1.70158f, c3 = c1 + 1f; return 1f + c3 * Mathf.Pow(t - 1f, 3f) + c1 * Mathf.Pow(t - 1f, 2f); }

        public static Color32 Rgba(Color c, float alpha) => new Color32((byte)(c.r * 255f), (byte)(c.g * 255f), (byte)(c.b * 255f), (byte)(Mathf.Clamp01(alpha) * 255f));
    }

    /// <summary>Deterministic PRNG so an effect looks the same every time it is replayed.</summary>
    public sealed class Rng
    {
        uint s;
        public Rng(uint seed) { s = seed == 0 ? 1u : seed; }
        public float Next()
        {
            s ^= s << 13; s ^= s >> 17; s ^= s << 5;
            return (s & 0xFFFFFF) / 16777216f;
        }
        public float Range(float a, float b) => a + (b - a) * Next();
    }

    /// <summary>
    /// One dynamic mesh that draws many camera-facing quads with a single draw call.
    /// Call Begin, then Add for each sprite, then End every frame.
    /// </summary>
    public sealed class SpriteBatch
    {
        readonly Mesh mesh;
        readonly Vector3[] verts;
        readonly Color32[] cols;
        readonly int capacity;
        readonly GameObject go;
        int count;

        public SpriteBatch(Transform parent, Material baseMat, Texture2D tex, int capacity, string name)
        {
            this.capacity = capacity;
            go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var mat = new Material(baseMat);
            mat.SetTexture("_BaseMap", tex);
            mesh = new Mesh { name = name };
            mesh.MarkDynamic();
            verts = new Vector3[capacity * 4];
            cols = new Color32[capacity * 4];
            var uv = new Vector2[capacity * 4];
            var tri = new int[capacity * 6];
            for (int i = 0; i < capacity; i++)
            {
                int v = i * 4;
                uv[v] = new Vector2(0, 0); uv[v + 1] = new Vector2(1, 0); uv[v + 2] = new Vector2(1, 1); uv[v + 3] = new Vector2(0, 1);
                int t = i * 6;
                tri[t] = v; tri[t + 1] = v + 2; tri[t + 2] = v + 1; tri[t + 3] = v; tri[t + 4] = v + 3; tri[t + 5] = v + 2;
            }
            mesh.vertices = verts;
            mesh.uv = uv;
            mesh.triangles = tri;
            mesh.colors32 = cols;
            mesh.bounds = new Bounds(Vector3.zero, Vector3.one * 100000f);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterial = mat;
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
        }

        public void Begin() => count = 0;

        /// <param name="upright">Keep the sprite vertical (flames) instead of facing the camera fully.</param>
        /// <param name="pivotY">0 = the position is the sprite's base, 0.5 = its centre.</param>
        public void Add(Camera cam, Vector3 pos, float width, float height, Color32 color, bool upright = false, float pivotY = 0.5f)
        {
            if (count >= capacity || color.a == 0 || width <= 0f || height <= 0f) return;
            Vector3 right = cam.transform.right;
            Vector3 up = cam.transform.up;
            if (upright)
            {
                right.y = 0f;
                if (right.sqrMagnitude < 1e-6f) right = Vector3.right;
                right.Normalize();
                up = Vector3.up;
            }
            Vector3 r = right * (width * 0.5f);
            Vector3 u0 = up * (-height * pivotY);
            Vector3 u1 = up * (height * (1f - pivotY));
            int v = count * 4;
            verts[v] = pos - r + u0;
            verts[v + 1] = pos + r + u0;
            verts[v + 2] = pos + r + u1;
            verts[v + 3] = pos - r + u1;
            cols[v] = cols[v + 1] = cols[v + 2] = cols[v + 3] = color;
            count++;
        }

        public void End()
        {
            for (int i = count * 4; i < capacity * 4; i++) verts[i] = Vector3.zero; // unused quads collapse to a point
            mesh.vertices = verts;
            mesh.colors32 = cols;
        }

        public void Destroy()
        {
            if (mesh != null) Object.Destroy(mesh);
            if (go != null) Object.Destroy(go);
        }
    }

    /// <summary>
    /// A flat disc or ring that follows the terrain surface (heights are re-sampled whenever it is set),
    /// with a colour that fades between an inner and an outer value. Used for pads, scorch marks and shock rings.
    /// </summary>
    public sealed class TerrainDecal
    {
        const int Segments = 56, Rings = 4;
        readonly Mesh mesh;
        readonly Vector3[] verts;
        readonly Color32[] cols;
        readonly GameObject go;

        public TerrainDecal(Transform parent, Material baseMat, string name)
        {
            go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var mat = new Material(baseMat);
            mat.SetTexture("_BaseMap", Texture2D.whiteTexture);
            int n = (Rings + 1) * Segments;
            verts = new Vector3[n];
            cols = new Color32[n];
            var uv = new Vector2[n];
            var tri = new List<int>(Rings * Segments * 6);
            for (int r = 0; r < Rings; r++)
                for (int s = 0; s < Segments; s++)
                {
                    int a = r * Segments + s, b = r * Segments + (s + 1) % Segments;
                    int c = (r + 1) * Segments + s, d = (r + 1) * Segments + (s + 1) % Segments;
                    tri.Add(a); tri.Add(c); tri.Add(b);
                    tri.Add(b); tri.Add(c); tri.Add(d);
                }
            for (int i = 0; i < n; i++) uv[i] = new Vector2(0.5f, 0.5f);
            mesh = new Mesh { name = name };
            mesh.MarkDynamic();
            mesh.vertices = verts;
            mesh.uv = uv;
            mesh.triangles = tri.ToArray();
            mesh.colors32 = cols;
            mesh.bounds = new Bounds(Vector3.zero, Vector3.one * 100000f);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterial = mat;
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
        }

        public void Hide()
        {
            if (go.activeSelf) go.SetActive(false);
        }

        /// <summary>Lays the decal between innerR and outerR (metres) around a centre on the terrain.</summary>
        public void Set(HeightField f, float exag, Vector2 centre, float innerR, float outerR, Color32 innerColor, Color32 outerColor, float lift)
        {
            if (!go.activeSelf) go.SetActive(true);
            for (int r = 0; r <= Rings; r++)
            {
                float t = (float)r / Rings;
                float radius = Mathf.Lerp(innerR, outerR, t);
                Color32 c = Color32.Lerp(innerColor, outerColor, t);
                for (int s = 0; s < Segments; s++)
                {
                    float a = s * Mathf.PI * 2f / Segments;
                    float x = centre.x + Mathf.Cos(a) * radius, z = centre.y + Mathf.Sin(a) * radius;
                    int i = r * Segments + s;
                    verts[i] = new Vector3(x, f.Sample(x, z) * exag + lift, z);
                    cols[i] = c;
                }
            }
            mesh.vertices = verts;
            mesh.colors32 = cols;
        }

        public void Destroy()
        {
            if (mesh != null) Object.Destroy(mesh);
            if (go != null) Object.Destroy(go);
        }
    }

    /// <summary>A vehicle built from primitives; it faces +X and knows which parts spin.</summary>
    public sealed class Vehicle
    {
        public GameObject Root;
        public readonly List<Transform> Rotors = new List<Transform>();
        public readonly List<GameObject> Beacons = new List<GameObject>();
        public Transform Nozzle;

        public void Spin(float dt, float time, float speedDegPerSec)
        {
            for (int i = 0; i < Rotors.Count; i++)
                Rotors[i].Rotate(0f, speedDegPerSec * dt * (i % 2 == 0 ? 1f : -1f), 0f, Space.Self);
            bool on = Mathf.Sin(time * 7f) > -0.2f;
            for (int i = 0; i < Beacons.Count; i++) Beacons[i].SetActive(on);
        }

        public void Destroy()
        {
            if (Root != null) Object.Destroy(Root);
        }

        // ---------------------------------------------------------------- construction helpers

        public static GameObject Prim(PrimitiveType type, Transform parent, Vector3 pos, Vector3 scale, Color color, Vector3 euler = default)
        {
            var g = GameObject.CreatePrimitive(type);
            Object.Destroy(g.GetComponent<Collider>()); // the models must never take clicks meant for the terrain
            g.transform.SetParent(parent, false);
            g.transform.localPosition = pos;
            g.transform.localScale = scale;
            g.transform.localRotation = Quaternion.Euler(euler);
            var mr = g.GetComponent<MeshRenderer>();
            mr.sharedMaterial = FxKit.Lit(color);
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
            return g;
        }

        /// <summary>Cylinder of a given diameter and length (a Unity cylinder is 2 units tall).</summary>
        static GameObject Cyl(Transform parent, Vector3 pos, float diameter, float length, Color color, Vector3 euler = default)
            => Prim(PrimitiveType.Cylinder, parent, pos, new Vector3(diameter, length * 0.5f, diameter), color, euler);

        static Transform Blades(Vehicle v, Transform parent, Vector3 pos, float span, float thick, Color color, Vector3 euler = default)
        {
            var pivot = new GameObject("Rotor").transform;
            pivot.SetParent(parent, false);
            pivot.localPosition = pos;
            pivot.localRotation = Quaternion.Euler(euler);
            Prim(PrimitiveType.Cube, pivot, Vector3.zero, new Vector3(span, thick, span * 0.08f), color);
            Prim(PrimitiveType.Cube, pivot, Vector3.zero, new Vector3(span, thick, span * 0.08f), color, new Vector3(0, 90, 0));
            v.Rotors.Add(pivot);
            return pivot;
        }

        static GameObject Beacon(Vehicle v, Transform parent, Vector3 pos, float size)
        {
            var b = Prim(PrimitiveType.Sphere, parent, pos, Vector3.one * size, new Color(1f, 0.25f, 0.2f));
            v.Beacons.Add(b);
            return b;
        }

        public static Vehicle Drone(float s)
        {
            var v = new Vehicle { Root = new GameObject("Drone") };
            Transform t = v.Root.transform;
            Prim(PrimitiveType.Cube, t, Vector3.zero, new Vector3(0.75f, 0.22f, 0.75f) * s, new Color(0.16f, 0.19f, 0.25f));
            Prim(PrimitiveType.Sphere, t, new Vector3(0, 0.1f, 0) * s, new Vector3(0.45f, 0.3f, 0.45f) * s, new Color(0.58f, 0.64f, 0.72f));
            Cyl(t, new Vector3(0, -0.31f, 0) * s, 0.44f * s, 0.42f * s, new Color(0.11f, 0.56f, 0.88f));
            var nozzle = Cyl(t, new Vector3(0.3f, -0.36f, 0) * s, 0.12f * s, 0.34f * s, new Color(0.88f, 0.11f, 0.28f), new Vector3(0, 0, -68));
            v.Nozzle = nozzle.transform;
            Beacon(v, t, new Vector3(-0.36f, 0.03f, 0) * s, 0.12f * s);
            for (int sx = -1; sx <= 1; sx += 2)
                for (int sz = -1; sz <= 1; sz += 2)
                {
                    Prim(PrimitiveType.Cube, t, new Vector3(sx * 0.5f, 0.02f, sz * 0.5f) * s, new Vector3(0.95f, 0.07f, 0.09f) * s, new Color(0.22f, 0.25f, 0.32f), new Vector3(0, sx * sz * -45f, 0));
                    Cyl(t, new Vector3(sx * 0.82f, 0.05f, sz * 0.82f) * s, 0.2f * s, 0.14f * s, new Color(0.07f, 0.09f, 0.15f));
                    Blades(v, t, new Vector3(sx * 0.82f, 0.15f, sz * 0.82f) * s, 0.95f * s, 0.018f * s, new Color(0.06f, 0.09f, 0.16f));
                }
            for (int sz = -1; sz <= 1; sz += 2)
                Prim(PrimitiveType.Cube, t, new Vector3(0, -0.56f, sz * 0.32f) * s, new Vector3(0.8f, 0.04f, 0.05f) * s, new Color(0.28f, 0.33f, 0.41f));
            return v;
        }

        public static Vehicle Helicopter(float s)
        {
            var v = new Vehicle { Root = new GameObject("Helicopter") };
            Transform t = v.Root.transform;
            var white = new Color(0.95f, 0.96f, 0.98f);
            var red = new Color(0.86f, 0.15f, 0.15f);
            Prim(PrimitiveType.Capsule, t, Vector3.zero, new Vector3(1.9f, 2.6f, 1.9f) * s, white, new Vector3(0, 0, 90));
            Cyl(t, new Vector3(0.1f, 0, 0) * s, 1.94f * s, 0.5f * s, red, new Vector3(0, 0, 90));
            Prim(PrimitiveType.Sphere, t, new Vector3(1.5f, 0.1f, 0) * s, new Vector3(1.2f, 1.3f, 1.5f) * s, new Color(0.12f, 0.22f, 0.37f));
            Cyl(t, new Vector3(-4.3f, 0, 0) * s, 0.4f * s, 5.4f * s, white, new Vector3(0, 0, 90));
            Prim(PrimitiveType.Cube, t, new Vector3(-6.7f, 0.7f, 0) * s, new Vector3(0.9f, 1.5f, 0.1f) * s, red);
            Cyl(t, new Vector3(0, 1.15f, 0) * s, 0.2f * s, 0.7f * s, new Color(0.2f, 0.25f, 0.33f));
            Blades(v, t, new Vector3(0, 1.55f, 0) * s, 11f * s, 0.05f * s, new Color(0.07f, 0.09f, 0.15f));
            Blades(v, t, new Vector3(-6.9f, 0.7f, 0.25f) * s, 1.5f * s, 0.03f * s, new Color(0.07f, 0.09f, 0.15f), new Vector3(90, 0, 0));
            for (int sz = -1; sz <= 1; sz += 2)
            {
                Prim(PrimitiveType.Cube, t, new Vector3(0.2f, -1.25f, sz * 0.8f) * s, new Vector3(3.6f, 0.09f, 0.09f) * s, new Color(0.28f, 0.33f, 0.41f));
                for (int dx = -1; dx <= 1; dx += 2)
                    Prim(PrimitiveType.Cube, t, new Vector3(dx * 0.9f, -0.9f, sz * 0.8f) * s, new Vector3(0.08f, 0.7f, 0.08f) * s, new Color(0.28f, 0.33f, 0.41f));
            }
            Beacon(v, t, new Vector3(-0.2f, 0.98f, 0) * s, 0.24f * s);
            return v;
        }

        public static Vehicle Plane(float s)
        {
            var v = new Vehicle { Root = new GameObject("Plane") };
            Transform t = v.Root.transform;
            var white = new Color(0.9f, 0.91f, 0.92f);
            var red = new Color(0.86f, 0.15f, 0.15f);
            Prim(PrimitiveType.Capsule, t, Vector3.zero, new Vector3(1.2f, 3.3f, 1.2f) * s, white, new Vector3(0, 0, 90));
            Prim(PrimitiveType.Cube, t, new Vector3(0.5f, 0.35f, 0) * s, new Vector3(1.7f, 0.14f, 11f) * s, white);
            Prim(PrimitiveType.Cube, t, new Vector3(-3.4f, 0.25f, 0) * s, new Vector3(1f, 0.1f, 3.6f) * s, white);
            Prim(PrimitiveType.Cube, t, new Vector3(-3.5f, 0.9f, 0) * s, new Vector3(1.2f, 1.3f, 0.1f) * s, red);
            Prim(PrimitiveType.Sphere, t, new Vector3(0.7f, 0.4f, 0) * s, new Vector3(1.1f, 0.8f, 0.9f) * s, new Color(0.12f, 0.22f, 0.37f));
            Blades(v, t, new Vector3(3.3f, 0, 0) * s, 1.9f * s, 0.05f * s, new Color(0.07f, 0.09f, 0.15f), new Vector3(0, 0, 90));
            for (int sz = -1; sz <= 1; sz += 2)
                Cyl(t, new Vector3(0.9f, -0.75f, sz * 0.9f) * s, 0.44f * s, 0.14f * s, new Color(0.07f, 0.09f, 0.15f), new Vector3(90, 0, 0));
            return v;
        }
    }
}
