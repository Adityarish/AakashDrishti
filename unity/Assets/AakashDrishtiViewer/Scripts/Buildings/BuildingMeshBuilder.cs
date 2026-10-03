using System.Collections.Generic;
using AakashDrishti.Viewer.Loading;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Buildings
{
    /// <summary>How a building mesh is coloured.</summary>
    public enum BuildingLook
    {
        /// <summary>Roofs show the scene photo under them; walls a facade colour derived from the roof colour.</summary>
        Imagery,
        /// <summary>No photo available: roofs use the sampled roof colour as a flat colour.</summary>
        FlatColour,
        /// <summary>Plain white so a material colour fully decides the look (the selection highlight).</summary>
        Plain,
    }

    /// <summary>
    /// Accumulates extruded buildings (flat roof + walls) into one combined mesh and remembers which
    /// triangles belong to which building so a raycast hit can be mapped back to it.
    /// </summary>
    public sealed class BuildingMeshBuilder
    {
        readonly HeightField field;
        readonly float inflate;
        readonly BuildingLook look;
        readonly EarClipper clipper = new EarClipper();
        readonly List<Vector3> verts = new List<Vector3>(4096);
        readonly List<Vector3> normals = new List<Vector3>(4096);
        readonly List<Vector2> uvs = new List<Vector2>(4096);
        readonly List<Color32> colors = new List<Color32>(4096);
        readonly List<int> indices = new List<int>(16384);
        readonly List<int> roofTris = new List<int>(64);
        readonly List<int> firstTriangle = new List<int>(256);
        readonly List<BuildingData> included = new List<BuildingData>(256);
        readonly List<Vector2> ringScratch = new List<Vector2>(64);

        // Facades are not visible from above, so their colour is the roof colour pulled toward a neutral
        // warm concrete: a black tar roof then gets grey walls instead of a black box.
        static readonly Color32 NeutralFacade = new Color32(205, 200, 190, 255);
        const float WallBottomShade = 0.62f, WallTopShade = 0.90f; // cheap ambient occlusion toward the ground

        /// <param name="inflate">Pushes every vertex out along its normal (meters); used for the selection shell.</param>
        public BuildingMeshBuilder(HeightField field, float inflate = 0f, BuildingLook look = BuildingLook.Imagery)
        {
            this.field = field;
            this.inflate = inflate;
            this.look = look;
        }

        static Color32 Shade(Color32 c, float k) =>
            new Color32((byte)Mathf.Clamp(c.r * k, 0f, 255f), (byte)Mathf.Clamp(c.g * k, 0f, 255f), (byte)Mathf.Clamp(c.b * k, 0f, 255f), 0);

        public int BuildingCount => included.Count;

        public bool Add(BuildingData b)
        {
            Vector2[] ring = Clean(b.Footprint);
            if (ring == null) return false;

            // Base sits on the lowest terrain sample under the footprint so no wall floats above the ground.
            float baseY = float.MaxValue;
            foreach (Vector2 v in ring) baseY = Mathf.Min(baseY, field.Sample(v.x, v.y));
            float bottom = baseY - 0.25f; // small skirt hides gaps on slopes
            float top = baseY + b.HeightM;

            roofTris.Clear();
            if (!clipper.Triangulate(ring, roofTris)) return false;

            bool ccw = EarClipper.SignedArea(ring) > 0f;
            int n = ring.Length;
            firstTriangle.Add(indices.Count / 3);
            included.Add(b);

            Color32 roof = b.RoofColor ?? NeutralFacade;
            Color32 facade = new Color32(
                (byte)((roof.r + NeutralFacade.r) / 2), (byte)((roof.g + NeutralFacade.g) / 2), (byte)((roof.b + NeutralFacade.b) / 2), 255);
            bool plain = look == BuildingLook.Plain;
            Color32 wallBottom = plain ? new Color32(255, 255, 255, 0) : Shade(facade, WallBottomShade);
            Color32 wallTop = plain ? new Color32(255, 255, 255, 0) : Shade(facade, WallTopShade);
            // vertex alpha 255 = take the colour from the imagery under this roof; 0 = flat vertex colour
            Color32 roofVertex = look == BuildingLook.Imagery ? new Color32(255, 255, 255, 255)
                               : plain ? new Color32(255, 255, 255, 0)
                               : new Color32(roof.r, roof.g, roof.b, 0);

            // Roof: shared vertices, normal up. Triangulate() returns CCW in (x,z); Unity wants clockwise from above.
            // UVs are the same world-space mapping the terrain uses, so the roof shows the photo of that exact roof.
            int roofBase = verts.Count;
            for (int i = 0; i < n; i++)
            {
                verts.Add(new Vector3(ring[i].x, top + inflate, ring[i].y));
                normals.Add(Vector3.up);
                uvs.Add(new Vector2(ring[i].x / field.SizeX, ring[i].y / field.SizeZ));
                colors.Add(roofVertex);
            }
            for (int t = 0; t < roofTris.Count; t += 3)
            {
                indices.Add(roofBase + roofTris[t]);
                indices.Add(roofBase + roofTris[t + 2]);
                indices.Add(roofBase + roofTris[t + 1]);
            }

            // Walls: one quad per edge with its own vertices for flat shading. Edges are walked in CCW order so
            // the outward normal is (dz, 0, -dx).
            for (int e = 0; e < n; e++)
            {
                Vector2 p0 = ring[ccw ? e : n - 1 - e];
                Vector2 p1 = ring[ccw ? (e + 1) % n : n - 1 - ((e + 1) % n)];
                Vector2 d = p1 - p0;
                float len = d.magnitude;
                if (len < 1e-5f) continue;
                Vector3 nrm = new Vector3(d.y / len, 0f, -d.x / len);
                Vector3 push = nrm * inflate;

                int w = verts.Count;
                verts.Add(new Vector3(p0.x, bottom, p0.y) + push);
                verts.Add(new Vector3(p0.x, top, p0.y) + push + Vector3.up * inflate);
                verts.Add(new Vector3(p1.x, bottom, p1.y) + push);
                verts.Add(new Vector3(p1.x, top, p1.y) + push + Vector3.up * inflate);
                for (int k = 0; k < 4; k++) { normals.Add(nrm); uvs.Add(Vector2.zero); }
                colors.Add(wallBottom); colors.Add(wallTop); colors.Add(wallBottom); colors.Add(wallTop);
                indices.Add(w); indices.Add(w + 1); indices.Add(w + 2);
                indices.Add(w + 2); indices.Add(w + 1); indices.Add(w + 3);
            }
            return true;
        }

        /// <summary>
        /// Removes a duplicated closing point and consecutive duplicates. Returns null if fewer than
        /// three distinct points remain or the polygon has no area.
        /// </summary>
        Vector2[] Clean(Vector2[] src)
        {
            ringScratch.Clear();
            foreach (Vector2 p in src)
                if (ringScratch.Count == 0 || (p - ringScratch[ringScratch.Count - 1]).sqrMagnitude > 1e-8f)
                    ringScratch.Add(p);
            while (ringScratch.Count > 1 && (ringScratch[0] - ringScratch[ringScratch.Count - 1]).sqrMagnitude <= 1e-8f)
                ringScratch.RemoveAt(ringScratch.Count - 1);
            if (ringScratch.Count < 3) return null;
            var ring = ringScratch.ToArray();
            return Mathf.Abs(EarClipper.SignedArea(ring)) < 1e-4f ? null : ring;
        }

        public BuildingSet Finish(bool keepReadable)
        {
            var mesh = new Mesh { name = "Buildings", indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(verts);
            mesh.SetNormals(normals);
            mesh.SetUVs(0, uvs);
            mesh.SetColors(colors);
            mesh.SetIndices(indices, MeshTopology.Triangles, 0);
            mesh.RecalculateBounds();
            if (!keepReadable) mesh.UploadMeshData(true);
            return new BuildingSet(mesh, included.ToArray(), firstTriangle.ToArray());
        }
    }

    /// <summary>The combined mesh plus a triangle-index lookup back to individual buildings.</summary>
    public sealed class BuildingSet
    {
        public readonly Mesh Mesh;
        public readonly BuildingData[] Buildings;
        readonly int[] firstTriangle;

        public BuildingSet(Mesh mesh, BuildingData[] buildings, int[] firstTriangle)
        {
            Mesh = mesh; Buildings = buildings; this.firstTriangle = firstTriangle;
        }

        public BuildingData FromTriangle(int triangleIndex)
        {
            int lo = 0, hi = firstTriangle.Length - 1;
            while (lo < hi)
            {
                int mid = (lo + hi + 1) >> 1;
                if (firstTriangle[mid] <= triangleIndex) lo = mid; else hi = mid - 1;
            }
            return Buildings.Length == 0 ? null : Buildings[lo];
        }
    }
}
