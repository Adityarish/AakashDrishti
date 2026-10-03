using System.Collections.Generic;
using UnityEngine;

namespace AakashDrishti.Viewer.Buildings
{
    /// <summary>Ear-clipping triangulation of a simple polygon (convex or concave, either winding).</summary>
    public sealed class EarClipper
    {
        readonly List<int> ring = new List<int>(64);

        /// <summary>
        /// Appends counter-clockwise triangles (indices into <paramref name="p"/>, x-right / y-up plane) to
        /// <paramref name="tris"/>. Returns false if nothing could be triangulated.
        /// </summary>
        public bool Triangulate(Vector2[] p, List<int> tris)
        {
            int n = p.Length;
            if (n < 3) return false;
            int before = tris.Count;

            ring.Clear();
            bool ccw = SignedArea(p) > 0f;
            for (int i = 0; i < n; i++) ring.Add(ccw ? i : n - 1 - i);

            int guard = n * n + 8;
            while (ring.Count > 3 && guard-- > 0)
            {
                int c = ring.Count;
                bool clipped = false;
                int flattest = 0;
                float flattestCross = float.MaxValue;

                for (int k = 0; k < c; k++)
                {
                    int ia = ring[(k + c - 1) % c], ib = ring[k], ic = ring[(k + 1) % c];
                    Vector2 a = p[ia], b = p[ib], cc = p[ic];
                    float cross = Cross(b - a, cc - b);
                    if (Mathf.Abs(cross) < flattestCross) { flattestCross = Mathf.Abs(cross); flattest = k; }
                    if (cross <= 1e-9f) continue; // reflex or collinear corner: not an ear

                    bool blocked = false;
                    for (int m = 0; m < c && !blocked; m++)
                    {
                        int im = ring[m];
                        if (im == ia || im == ib || im == ic) continue;
                        blocked = InTriangle(p[im], a, b, cc);
                    }
                    if (blocked) continue;

                    tris.Add(ia); tris.Add(ib); tris.Add(ic);
                    ring.RemoveAt(k);
                    clipped = true;
                    break;
                }

                // Degenerate input (collinear runs, touching edges): drop the flattest corner so we always progress.
                if (!clipped) ring.RemoveAt(flattest);
            }

            if (ring.Count == 3 && Cross(p[ring[1]] - p[ring[0]], p[ring[2]] - p[ring[1]]) > 1e-9f)
            {
                tris.Add(ring[0]); tris.Add(ring[1]); tris.Add(ring[2]);
            }
            return tris.Count > before;
        }

        public static float SignedArea(Vector2[] p)
        {
            float a = 0f;
            for (int i = 0, j = p.Length - 1; i < p.Length; j = i++)
                a += p[j].x * p[i].y - p[i].x * p[j].y;
            return a * 0.5f;
        }

        static float Cross(Vector2 u, Vector2 v) => u.x * v.y - u.y * v.x;

        static bool InTriangle(Vector2 pt, Vector2 a, Vector2 b, Vector2 c)
        {
            float d1 = Cross(b - a, pt - a);
            float d2 = Cross(c - b, pt - b);
            float d3 = Cross(a - c, pt - c);
            return d1 >= 0f && d2 >= 0f && d3 >= 0f;
        }
    }
}
