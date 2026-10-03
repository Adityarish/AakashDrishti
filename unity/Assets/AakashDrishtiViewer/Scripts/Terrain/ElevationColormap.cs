using UnityEngine;

namespace AakashDrishti.Viewer.Terrains
{
    public static class ElevationColormap
    {
        // deep blue > teal > green > yellow > orange-brown > near white
        static readonly Color32[] Stops =
        {
            new Color32(46, 61, 140, 255),
            new Color32(26, 140, 153, 255),
            new Color32(89, 191, 89, 255),
            new Color32(230, 217, 89, 255),
            new Color32(191, 115, 64, 255),
            new Color32(250, 247, 242, 255),
        };

        public static Color32 Evaluate(float t)
        {
            t = Mathf.Clamp01(t) * (Stops.Length - 1);
            int i = Mathf.Min((int)t, Stops.Length - 2);
            return Color32.Lerp(Stops[i], Stops[i + 1], t - i);
        }

        /// <summary>One texel per height sample, so it lines up with the render mesh UVs.</summary>
        public static Texture2D BuildTexture(HeightField hf)
        {
            float range = hf.MaxM - hf.MinM;
            float inv = range > 1e-6f ? 1f / range : 0f;
            var px = new Color32[hf.Heights.Length];
            for (int k = 0; k < px.Length; k++)
                px[k] = Evaluate((hf.Heights[k] - hf.MinM) * inv);

            var tex = new Texture2D(hf.Width, hf.Height, TextureFormat.RGBA32, false, false)
            {
                name = "ElevationColormap",
                wrapMode = TextureWrapMode.Clamp,
                filterMode = FilterMode.Bilinear,
            };
            tex.SetPixels32(px);
            tex.Apply(false, true);
            return tex;
        }
    }
}
