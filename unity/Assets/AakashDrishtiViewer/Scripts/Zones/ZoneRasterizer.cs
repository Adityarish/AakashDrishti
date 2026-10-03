using System;
using System.Collections.Generic;
using AakashDrishti.Viewer.Loading;
using UnityEngine;

namespace AakashDrishti.Viewer.Zones
{
    /// <summary>
    /// Paints disaster-zone polygons into an RGBA texture that covers the whole terrain, so the overlay is a
    /// single draw call regardless of zone count. Texels are premultiplied (rgb already scaled by alpha), which
    /// keeps bilinear filtering from dragging dark fringes into the zone edges.
    /// </summary>
    public static class ZoneRasterizer
    {
        public const int MaxTextureDimension = 1024;

        public static readonly Color32 Low = new Color32(255, 235, 51, 255);
        public static readonly Color32 Medium = new Color32(255, 140, 26, 255);
        public static readonly Color32 High = new Color32(230, 26, 26, 255);

        public static Texture2D Rasterize(IList<ZoneData> zones, float sizeX, float sizeZ)
        {
            float scale = MaxTextureDimension / Mathf.Max(sizeX, sizeZ);
            int w = Mathf.Max(2, Mathf.RoundToInt(sizeX * scale));
            int h = Mathf.Max(2, Mathf.RoundToInt(sizeZ * scale));
            var px = new Color32[w * h]; // default (0,0,0,0) = transparent

            var crossings = new List<float>(32);
            // Low first so overlapping higher levels win.
            for (int level = 0; level <= (int)ZoneLevel.High; level++)
            {
                Color32 color = level == 0 ? Low : level == 1 ? Medium : High;
                foreach (ZoneData z in zones)
                    if ((int)z.Level == level)
                        Fill(px, w, h, z.Polygon, w / sizeX, h / sizeZ, color, crossings);
            }

            var tex = new Texture2D(w, h, TextureFormat.RGBA32, false, false)
            {
                name = "DisasterZones",
                wrapMode = TextureWrapMode.Clamp,
                filterMode = FilterMode.Bilinear,
            };
            tex.SetPixels32(px);
            tex.Apply(false, true);
            return tex;
        }

        /// <summary>Even-odd scanline fill sampled at texel centres. Texture row 0 = south (z = 0).</summary>
        static void Fill(Color32[] px, int w, int h, Vector2[] poly, float kx, float kz, Color32 color, List<float> xs)
        {
            int n = poly.Length;
            float minY = float.MaxValue, maxY = float.MinValue;
            for (int i = 0; i < n; i++)
            {
                float y = poly[i].y * kz;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
            }

            int row0 = Math.Max(0, (int)Math.Ceiling(minY - 0.5f));
            int row1 = Math.Min(h - 1, (int)Math.Floor(maxY - 0.5f));
            for (int row = row0; row <= row1; row++)
            {
                float yc = row + 0.5f;
                xs.Clear();
                for (int i = 0, j = n - 1; i < n; j = i++)
                {
                    float ay = poly[j].y * kz, by = poly[i].y * kz;
                    if ((ay <= yc) == (by <= yc)) continue; // edge does not straddle this scanline
                    float ax = poly[j].x * kx, bx = poly[i].x * kx;
                    xs.Add(ax + (yc - ay) / (by - ay) * (bx - ax));
                }
                xs.Sort();
                for (int k = 0; k + 1 < xs.Count; k += 2)
                {
                    int c0 = Math.Max(0, (int)Math.Ceiling(xs[k] - 0.5f));
                    int c1 = Math.Min(w - 1, (int)Math.Ceiling(xs[k + 1] - 0.5f) - 1);
                    for (int c = c0; c <= c1; c++) px[row * w + c] = color;
                }
            }
        }
    }
}
