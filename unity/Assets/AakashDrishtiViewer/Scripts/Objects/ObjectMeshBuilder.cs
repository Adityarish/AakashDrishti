using System.Collections.Generic;
using AakashDrishti.Viewer.Loading;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Objects
{
    /// <summary>
    /// Builds every detected vehicle, tank, pool and tree into ONE combined mesh with vertex colours (a single draw
    /// call, WebGL friendly). Shapes are deliberately simple low-poly forms sized from the detector's oriented box,
    /// coloured from the photo under them, and sitting on the terrain.
    /// </summary>
    public sealed class ObjectMeshBuilder
    {
        // Cars sit slightly above the surface; trees sink partly into it because the height map already contains a
        // smoothed canopy lump at that spot (trunk base = surface - TreeSink * height).
        const float TreeSink = 0.55f;
        const float VehicleLift = 0.12f;
        const int SphereSegments = 10, SphereRings = 5, TrunkSides = 6, CylinderSides = 16;

        readonly HeightField field;
        readonly List<Vector3> verts = new List<Vector3>(8192);
        readonly List<Vector3> normals = new List<Vector3>(8192);
        readonly List<Color32> colors = new List<Color32>(8192);
        readonly List<int> indices = new List<int>(32768);

        public int ObjectCount { get; private set; }
        public int TreeCount { get; private set; }

        public ObjectMeshBuilder(HeightField field) { this.field = field; }

        // ------------------------------------------------------------------ primitives

        static Color32 Flat(Color32 c, float shade = 1f) =>
            new Color32((byte)Mathf.Clamp(c.r * shade, 0f, 255f), (byte)Mathf.Clamp(c.g * shade, 0f, 255f), (byte)Mathf.Clamp(c.b * shade, 0f, 255f), 0);

        static Color32 Mix(Color32 a, Color32 b, float t) =>
            new Color32((byte)Mathf.Lerp(a.r, b.r, t), (byte)Mathf.Lerp(a.g, b.g, t), (byte)Mathf.Lerp(a.b, b.b, t), 0);

        /// <summary>Adds one triangle of already-added vertices, flipping the winding so it faces `expected`.</summary>
        void Face(int i0, int i1, int i2, Vector3 expected)
        {
            Vector3 cross = Vector3.Cross(verts[i1] - verts[i0], verts[i2] - verts[i0]);
            if (Vector3.Dot(cross, expected) >= 0f) { indices.Add(i0); indices.Add(i1); indices.Add(i2); }
            else { indices.Add(i0); indices.Add(i2); indices.Add(i1); }
        }

        void Quad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 n, Color32 col)
        {
            int s = verts.Count;
            verts.Add(a); verts.Add(b); verts.Add(c); verts.Add(d);
            for (int k = 0; k < 4; k++) { normals.Add(n); colors.Add(col); }
            Face(s, s + 1, s + 2, n);
            Face(s, s + 2, s + 3, n);
        }

        /// <summary>Open-bottom box: top plus four sides. `o` is the centre of the bottom face.</summary>
        void Box(Vector3 o, float length, float width, float height, Vector3 u, Vector3 v, Color32 col)
        {
            Vector3 hu = u * (length * 0.5f), hv = v * (width * 0.5f), up = Vector3.up * height;
            Vector3 b00 = o - hu - hv, b10 = o + hu - hv, b11 = o + hu + hv, b01 = o - hu + hv;
            Vector3 t00 = b00 + up, t10 = b10 + up, t11 = b11 + up, t01 = b01 + up;
            Quad(t00, t10, t11, t01, Vector3.up, col);
            Quad(b00, b10, t10, t00, -v, col);
            Quad(b10, b11, t11, t10, u, col);
            Quad(b11, b01, t01, t11, v, col);
            Quad(b01, b00, t00, t01, -u, col);
        }

        void Cylinder(Vector3 o, float radius, float height, int sides, Color32 col, Color32 topCol)
        {
            int topCentre = verts.Count;
            verts.Add(o + Vector3.up * height); normals.Add(Vector3.up); colors.Add(topCol);
            int ringStart = verts.Count;
            for (int i = 0; i < sides; i++)
            {
                float a = 2f * Mathf.PI * i / sides;
                var radial = new Vector3(Mathf.Cos(a), 0f, Mathf.Sin(a));
                verts.Add(o + radial * radius + Vector3.up * height); normals.Add(Vector3.up); colors.Add(topCol);
            }
            for (int i = 0; i < sides; i++) Face(topCentre, ringStart + i, ringStart + (i + 1) % sides, Vector3.up);

            for (int i = 0; i < sides; i++)
            {
                float a0 = 2f * Mathf.PI * i / sides, a1 = 2f * Mathf.PI * (i + 1) / sides;
                var r0 = new Vector3(Mathf.Cos(a0), 0f, Mathf.Sin(a0));
                var r1 = new Vector3(Mathf.Cos(a1), 0f, Mathf.Sin(a1));
                int s = verts.Count;
                verts.Add(o + r0 * radius); verts.Add(o + r1 * radius);
                verts.Add(o + r1 * radius + Vector3.up * height); verts.Add(o + r0 * radius + Vector3.up * height);
                normals.Add(r0); normals.Add(r1); normals.Add(r1); normals.Add(r0);
                for (int k = 0; k < 4; k++) colors.Add(col);
                Face(s, s + 1, s + 2, r0 + r1);
                Face(s, s + 2, s + 3, r0 + r1);
            }
        }

        // ------------------------------------------------------------------ objects

        float Surface(Vector2 p) => field.Sample(p.x, p.y);

        /// <summary>Resting height for a flat-bottomed object: just under the surface, never below known bare earth.</summary>
        float RestY(ObjectData o)
        {
            float surface = Surface(o.Center);
            float baseline = surface - VehicleLift;
            return float.IsNaN(o.BaseM) ? baseline : Mathf.Max(o.BaseM, surface - 0.4f);
        }

        public void AddObject(ObjectData o)
        {
            float yaw = o.YawDeg * Mathf.Deg2Rad;
            // u runs along the box's long side, v across it; both horizontal. (x = east, z = north.)
            var u = new Vector3(Mathf.Cos(yaw), 0f, Mathf.Sin(yaw));
            var v = new Vector3(-Mathf.Sin(yaw), 0f, Mathf.Cos(yaw));
            var origin = new Vector3(o.Center.x, RestY(o), o.Center.y);
            Color32 c = o.Color;
            Color32 glass = Mix(new Color32(36, 44, 56, 0), c, 0.18f);
            Color32 tyre = new Color32(26, 26, 28, 0);

            switch (o.Kind)
            {
                case ObjectKind.Vehicle:
                {
                    float clearance = 0.16f * o.Height;
                    float body = 0.42f * o.Height, cabin = 0.40f * o.Height;
                    Box(origin + Vector3.up * clearance, o.Length, o.Width, body, u, v, Flat(c));
                    Box(origin + Vector3.up * (clearance + body) - u * (0.04f * o.Length), o.Length * 0.52f, o.Width * 0.86f, cabin, u, v, glass);
                    AddWheels(origin, o.Length, o.Width, 0.6f, clearance + 0.1f, u, v, tyre);
                    break;
                }
                case ObjectKind.Truck:
                {
                    float cabLen = o.Length * 0.26f, cargoLen = o.Length - cabLen - 0.1f;
                    // rear end is at -Length/2 along u, the cab sits at the +u end
                    Vector3 cargoCentre = origin + u * (-0.5f * o.Length + 0.5f * cargoLen) + Vector3.up * (0.22f * o.Height);
                    Box(cargoCentre, cargoLen, o.Width, o.Height * 0.78f, u, v, Flat(c, 0.95f));
                    Box(origin + u * (o.Length * 0.5f - cabLen * 0.5f) + Vector3.up * (0.22f * o.Height), cabLen, o.Width, o.Height * 0.62f, u, v, Mix(c, glass, 0.35f));
                    AddWheels(origin, o.Length, o.Width, 0.9f, 0.45f, u, v, tyre);
                    break;
                }
                case ObjectKind.Tank:
                    Cylinder(origin, Mathf.Max(o.Length, o.Width) * 0.5f, o.Height, CylinderSides, Flat(c), Flat(c, 1.15f));
                    break;
                case ObjectKind.Pool:
                case ObjectKind.Slab:
                    Box(origin + Vector3.up * 0.02f, o.Length, o.Width, o.Height, u, v, Flat(c));
                    break;
                case ObjectKind.Aircraft:
                    Box(origin, o.Length, o.Width * 0.2f, o.Height * 0.5f, u, v, Flat(c));
                    Box(origin + u * (o.Length * 0.05f), o.Length * 0.22f, o.Width, o.Height * 0.12f, u, v, Flat(c, 0.9f));
                    break;
                case ObjectKind.Ship:
                    Box(origin, o.Length, o.Width, o.Height * 0.45f, u, v, Flat(c, 0.9f));
                    Box(origin + Vector3.up * (o.Height * 0.45f) - u * (o.Length * 0.25f), o.Length * 0.22f, o.Width * 0.6f, o.Height * 0.55f, u, v, Flat(c));
                    break;
                default:
                    Box(origin, o.Length, o.Width, o.Height, u, v, Flat(c));
                    break;
            }
            ObjectCount++;
        }

        void AddWheels(Vector3 origin, float length, float width, float spread, float size, Vector3 u, Vector3 v, Color32 tyre)
        {
            float w = Mathf.Min(0.28f, width * 0.14f);
            foreach (float su in new[] { -spread, spread })
                foreach (float sv in new[] { -1f, 1f })
                {
                    Vector3 centre = origin + u * (su * length * 0.33f) + v * (sv * (width * 0.5f - w * 0.5f));
                    Box(centre, Mathf.Min(0.7f, length * 0.16f), w, size, u, v, tyre);
                }
        }

        // ------------------------------------------------------------------ trees

        static float Jitter(int seed)
        {
            unchecked
            {
                uint h = (uint)seed * 2654435761u;
                h ^= h >> 15;
                return ((h >> 4) & 0xFFFF) / 65535f;
            }
        }

        public void AddTree(TreeData t, int seed)
        {
            float h = t.HeightM, radius = t.CrownRadiusM;
            float surface = field.Sample(t.Position.x, t.Position.y);
            float lowest = surface - TreeSink * h;
            float y0 = float.IsNaN(t.BaseM) ? lowest : Mathf.Max(t.BaseM, lowest);
            var foot = new Vector3(t.Position.x, y0, t.Position.y);

            // Trunk: a thin six-sided prism up to just inside the canopy.
            float trunkR = Mathf.Clamp(0.10f + 0.014f * h, 0.14f, 0.40f), trunkH = 0.46f * h;
            Color32 bark = new Color32(86, 62, 42, 0);
            for (int i = 0; i < TrunkSides; i++)
            {
                float a0 = 2f * Mathf.PI * i / TrunkSides, a1 = 2f * Mathf.PI * (i + 1) / TrunkSides;
                var r0 = new Vector3(Mathf.Cos(a0), 0f, Mathf.Sin(a0));
                var r1 = new Vector3(Mathf.Cos(a1), 0f, Mathf.Sin(a1));
                Quad(foot + r0 * trunkR, foot + r1 * trunkR, foot + r1 * trunkR + Vector3.up * trunkH, foot + r0 * trunkR + Vector3.up * trunkH,
                     r0 + r1, bark);
            }

            // Canopy: a squashed low-poly ellipsoid in the colour the photo shows there. Dark (shadowed) samples are
            // lifted so a tree in shade does not become a black ball; a little per-tree variation breaks up the grid.
            Color32 canopy = t.Color;
            float luma = 0.299f * canopy.r + 0.587f * canopy.g + 0.114f * canopy.b;
            float lift = luma < 78f ? 78f / Mathf.Max(luma, 1f) : 1f;
            float variation = 0.90f + 0.20f * Jitter(seed);
            float vertical = 0.40f * h;
            Vector3 centre = foot + Vector3.up * (h - vertical);

            int baseIndex = verts.Count;
            for (int i = 0; i <= SphereRings; i++)
            {
                float phi = Mathf.PI * (-0.5f + (float)i / SphereRings);
                float cp = Mathf.Cos(phi), sp = Mathf.Sin(phi);
                float shade = (0.68f + 0.36f * i / SphereRings) * lift * variation;
                for (int j = 0; j < SphereSegments; j++)
                {
                    float theta = 2f * Mathf.PI * (j + 0.5f * (i & 1)) / SphereSegments;
                    float ct = Mathf.Cos(theta), st = Mathf.Sin(theta);
                    // up to +-9% radius wobble per vertex so crowns are not perfect eggs (deterministic per tree)
                    float wobble = 0.91f + 0.18f * Jitter(seed * 131 + i * 17 + j);
                    verts.Add(centre + new Vector3(radius * wobble * cp * ct, vertical * sp, radius * wobble * cp * st));
                    normals.Add(new Vector3(cp * ct / radius, sp / vertical, cp * st / radius).normalized);
                    colors.Add(Flat(canopy, shade));
                }
            }
            for (int i = 0; i < SphereRings; i++)
                for (int j = 0; j < SphereSegments; j++)
                {
                    int j1 = (j + 1) % SphereSegments;
                    int a = baseIndex + i * SphereSegments + j, b = baseIndex + i * SphereSegments + j1;
                    int c = baseIndex + (i + 1) * SphereSegments + j1, d = baseIndex + (i + 1) * SphereSegments + j;
                    Vector3 outward = normals[a] + normals[b] + normals[c] + normals[d];
                    Face(a, b, c, outward);
                    Face(a, c, d, outward);
                }
            TreeCount++;
        }

        // ------------------------------------------------------------------ result

        public Mesh Finish()
        {
            var mesh = new Mesh { name = "Objects", indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(verts);
            mesh.SetNormals(normals);
            mesh.SetColors(colors);
            mesh.SetIndices(indices, MeshTopology.Triangles, 0);
            mesh.RecalculateBounds();
            mesh.UploadMeshData(true);
            return mesh;
        }
    }
}
