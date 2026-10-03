using System;
using AakashDrishti.Viewer.Loading;
using UnityEngine;

namespace AakashDrishti.Viewer.Terrains
{
    /// <summary>
    /// Decoded heights in meters on a (possibly downsampled) grid.
    /// Index layout: Heights[j * Width + i], i = east, j = north, so row 0 is the SOUTH edge
    /// (the r16 file is north-first; it is flipped while decoding).
    /// </summary>
    public sealed class HeightField
    {
        public const int MaxGridDimension = 512;

        public readonly int Width;
        public readonly int Height;
        public readonly float[] Heights;
        public readonly float SizeX;
        public readonly float SizeZ;
        public readonly float MinM;
        public readonly float MaxM;
        public readonly bool Downsampled;

        HeightField(int w, int h, float sizeX, float sizeZ, float minM, float maxM, bool downsampled)
        {
            Width = w; Height = h; SizeX = sizeX; SizeZ = sizeZ; MinM = minM; MaxM = maxM; Downsampled = downsampled;
            Heights = new float[w * h];
        }

        /// <summary>
        /// Decodes little-endian uint16 samples (height = min + v/65535 * (max - min)) and box-averages
        /// down to at most MaxGridDimension per side. Bytes come straight from the download handler because
        /// Texture2D.LoadImage would truncate to 8 bits.
        /// </summary>
        public static HeightField FromR16(byte[] data, SceneData scene)
        {
            int srcW = scene.HeightmapWidth, srcH = scene.HeightmapHeight;
            long expected = (long)srcW * srcH * 2;
            if (data == null || data.Length != expected)
                throw new ViewerLoadException(
                    $"{scene.HeightmapFile} has {(data == null ? 0 : data.Length)} bytes but {srcW}x{srcH} uint16 samples need {expected}.");

            int gw = srcW, gh = srcH;
            int longest = Mathf.Max(srcW, srcH);
            if (longest > MaxGridDimension)
            {
                double k = (double)MaxGridDimension / longest;
                gw = Mathf.Max(2, (int)Math.Round(srcW * k));
                gh = Mathf.Max(2, (int)Math.Round(srcH * k));
            }

            var hf = new HeightField(gw, gh, scene.WorldSizeX, scene.WorldSizeZ, scene.MinM, scene.MaxM, gw != srcW || gh != srcH);
            float range = scene.MaxM - scene.MinM;
            float scale = range / 65535f;

            // Each output vertex averages the source samples within +-half a grid step around its position,
            // which keeps the corner vertices exactly on the terrain corners.
            double stepX = (double)(srcW - 1) / (gw - 1);
            double stepZ = (double)(srcH - 1) / (gh - 1);
            double halfX = hf.Downsampled ? stepX * 0.5 : 0.5;
            double halfZ = hf.Downsampled ? stepZ * 0.5 : 0.5;

            for (int j = 0; j < gh; j++)
            {
                double srcRowNorth = (srcH - 1) - j * stepZ; // j = 0 is south = last file row
                int r0 = Math.Max(0, (int)Math.Ceiling(srcRowNorth - halfZ - 1e-6));
                int r1 = Math.Min(srcH - 1, (int)Math.Floor(srcRowNorth + halfZ + 1e-6));
                if (r1 < r0) r0 = r1 = Mathf.Clamp((int)Math.Round(srcRowNorth), 0, srcH - 1);

                for (int i = 0; i < gw; i++)
                {
                    double srcCol = i * stepX;
                    int c0 = Math.Max(0, (int)Math.Ceiling(srcCol - halfX - 1e-6));
                    int c1 = Math.Min(srcW - 1, (int)Math.Floor(srcCol + halfX + 1e-6));
                    if (c1 < c0) c0 = c1 = Mathf.Clamp((int)Math.Round(srcCol), 0, srcW - 1);

                    long sum = 0;
                    for (int r = r0; r <= r1; r++)
                    {
                        int o = (r * srcW + c0) * 2;
                        for (int c = c0; c <= c1; c++, o += 2)
                            sum += data[o] | (data[o + 1] << 8);
                    }
                    double avg = (double)sum / ((r1 - r0 + 1) * (c1 - c0 + 1));
                    hf.Heights[j * gw + i] = scene.MinM + (float)avg * scale;
                }
            }
            return hf;
        }

        /// <summary>Bilinear height in meters at scene-space (x = east, z = north).</summary>
        public float Sample(float x, float z)
        {
            float fx = Mathf.Clamp01(x / SizeX) * (Width - 1);
            float fz = Mathf.Clamp01(z / SizeZ) * (Height - 1);
            int ix = Mathf.Min((int)fx, Width - 2);
            int iz = Mathf.Min((int)fz, Height - 2);
            float tx = fx - ix, tz = fz - iz;
            int i00 = iz * Width + ix;
            float h0 = Mathf.Lerp(Heights[i00], Heights[i00 + 1], tx);
            float h1 = Mathf.Lerp(Heights[i00 + Width], Heights[i00 + Width + 1], tx);
            return Mathf.Lerp(h0, h1, tz);
        }
    }
}
