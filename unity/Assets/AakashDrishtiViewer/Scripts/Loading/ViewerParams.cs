using System;
using System.Collections.Generic;

namespace AakashDrishti.Viewer.Loading
{
    /// <summary>Query-string parameters of the hosting page: ?api=...&amp;job=...&amp;mock=1&amp;debug=1</summary>
    public sealed class ViewerParams
    {
        public const string DefaultApiBase = "http://localhost:8000";

        public string Api;
        public string Job;
        public bool ForceMock;
        public bool Debug;

        public static ViewerParams FromUrl(string url)
        {
            var p = new ViewerParams();
            if (string.IsNullOrEmpty(url)) return p;

            int q = url.IndexOf('?');
            if (q < 0) return p;
            int hash = url.IndexOf('#', q);
            string query = hash < 0 ? url.Substring(q + 1) : url.Substring(q + 1, hash - q - 1);

            var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (string pair in query.Split('&'))
            {
                if (pair.Length == 0) continue;
                int eq = pair.IndexOf('=');
                string k = Decode(eq < 0 ? pair : pair.Substring(0, eq));
                string v = eq < 0 ? "" : Decode(pair.Substring(eq + 1));
                map[k] = v;
            }

            map.TryGetValue("api", out p.Api);
            map.TryGetValue("job", out p.Job);
            p.ForceMock = map.TryGetValue("mock", out string m) && IsTrue(m);
            p.Debug = map.TryGetValue("debug", out string d) && IsTrue(d);
            if (string.IsNullOrWhiteSpace(p.Job)) p.Job = null;
            return p;
        }

        static bool IsTrue(string v) => v == "" || v == "1" || v.Equals("true", StringComparison.OrdinalIgnoreCase);

        static string Decode(string s)
        {
            try { return Uri.UnescapeDataString(s.Replace('+', ' ')); }
            catch (UriFormatException) { return s; }
        }
    }
}
