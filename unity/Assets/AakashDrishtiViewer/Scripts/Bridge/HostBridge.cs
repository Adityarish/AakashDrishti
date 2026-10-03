using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;

namespace AakashDrishti.Viewer.Bridge
{
    /// <summary>
    /// Posts messages to window.parent (the Next.js page embedding this build).
    /// Outside a WebGL player the messages are only logged.
    /// </summary>
    public static class HostBridge
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")] static extern void AD_PostToParent(string json);
#endif
        static float lastProgress = -1f;

        public static void Ready() => Post("{\"type\":\"ready\"}");

        /// <summary>Throttled to ~1% steps so the host is not flooded.</summary>
        public static void Progress(float value)
        {
            value = Mathf.Clamp01(value);
            if (value < 1f && value > 0f && Mathf.Abs(value - lastProgress) < 0.01f) return;
            lastProgress = value;
            Post("{\"type\":\"progress\",\"value\":" + value.ToString("0.###", CultureInfo.InvariantCulture) + "}");
        }

        public static void ResetProgress() => lastProgress = -1f;

        public static void Error(string message) =>
            Post("{\"type\":\"error\",\"message\":" + Quote(message) + "}");

        public static void BuildingSelected(int id, float heightM) =>
            Post("{\"type\":\"buildingSelected\",\"id\":" + id.ToString(CultureInfo.InvariantCulture) +
                 ",\"height_m\":" + heightM.ToString("0.###", CultureInfo.InvariantCulture) + "}");

        /// <summary>The user clicked the terrain while a scenario was waiting for a point (fractions of the world size, u = east, v = north).</summary>
        public static void Picked(float u, float v) =>
            Post("{\"type\":\"picked\",\"u\":" + u.ToString("0.#####", CultureInfo.InvariantCulture) +
                 ",\"v\":" + v.ToString("0.#####", CultureInfo.InvariantCulture) + "}");

        static void Post(string json)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            AD_PostToParent(json);
#else
            Debug.Log("[HostBridge] " + json);
#endif
        }

        static string Quote(string s)
        {
            var sb = new StringBuilder(s == null ? 2 : s.Length + 2);
            sb.Append('"');
            if (s != null)
            {
                foreach (char c in s)
                {
                    switch (c)
                    {
                        case '"': sb.Append("\\\""); break;
                        case '\\': sb.Append("\\\\"); break;
                        case '\n': sb.Append("\\n"); break;
                        case '\r': sb.Append("\\r"); break;
                        case '\t': sb.Append("\\t"); break;
                        default:
                            if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                            else sb.Append(c);
                            break;
                    }
                }
            }
            sb.Append('"');
            return sb.ToString();
        }
    }
}
