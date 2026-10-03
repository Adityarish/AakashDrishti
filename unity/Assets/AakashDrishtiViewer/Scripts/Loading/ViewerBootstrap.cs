using System;
using System.Collections;
using System.Collections.Generic;
using AakashDrishti.Viewer.Bridge;
using AakashDrishti.Viewer.Buildings;
using AakashDrishti.Viewer.Cameras;
using AakashDrishti.Viewer.Objects;
using AakashDrishti.Viewer.Scenarios;
using AakashDrishti.Viewer.Terrains;
using AakashDrishti.Viewer.Ui;
using AakashDrishti.Viewer.Zones;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Loading
{
    /// <summary>
    /// Entry point. The scene holds a single GameObject named "ViewerBootstrap" with this component;
    /// everything else (camera, light, UI, terrain) is created here. The host page can also call
    /// SendMessage("ViewerBootstrap", "LoadJob", json) to load another job at runtime.
    /// </summary>
    public sealed class ViewerBootstrap : MonoBehaviour
    {
#if UNITY_EDITOR
        [Tooltip("Editor only: simulates the page query string, e.g. ?job=abc123&api=http://localhost:8000")]
        [SerializeField] string editorQuery = "";
#endif

        // progress budget of the loading bar
        const float ProgressScene = 0.05f, ProgressHeightmap = 0.35f, ProgressTexture = 0.70f,
                    ProgressTerrain = 0.80f, ProgressBuildings = 0.95f;

        ViewerParams prm;
        TerrainView terrain;
        BuildingLayer buildings;
        ObjectLayer props;
        CameraRig rig;
        ViewerUI ui;
        ViewerInteraction interaction;
        ScenarioController scenarios;
        Camera cam;
        Coroutine loading;
        string lastBaseUrl;
        SceneData scene;

        sealed class Download
        {
            public byte[] Data;
            public string Text;
            public string Error;
        }

        // ------------------------------------------------------------------ lifecycle

        void Awake()
        {
            string url = Application.absoluteURL;
#if UNITY_EDITOR
            url += editorQuery;
#endif
            prm = ViewerParams.FromUrl(url);

            CreateCameraAndLight();

            terrain = NewChild<TerrainView>("TerrainView");
            buildings = NewChild<BuildingLayer>("BuildingLayer");
            props = NewChild<ObjectLayer>("ObjectLayer");
            ui = NewChild<ViewerUI>("ViewerUI");
            ui.ShowFps = prm.Debug || Debug.isDebugBuild;
            rig = NewChild<CameraRig>("CameraRig");
            rig.Init(cam, terrain);
            ui.Rig = rig;
            interaction = NewChild<ViewerInteraction>("Interaction");
            interaction.Cam = cam; interaction.Terrain = terrain; interaction.Buildings = buildings;
            interaction.Rig = rig; interaction.Ui = ui;
            scenarios = NewChild<ScenarioController>("Scenarios");
            scenarios.Init(terrain, rig, cam);
            interaction.Scenarios = scenarios;

            ui.OverlayChanged += terrain.SetMode;
            ui.ZonesToggled += terrain.SetZonesVisible;
            ui.ExaggerationChanged += terrain.SetExaggeration;
            ui.CameraToggleClicked += rig.Toggle;
            ui.RetryClicked += Reload;
            rig.ModeChanged += _ => ui.RefreshCameraLabel();
            buildings.SelectionChanged += OnBuildingSelected;
        }

        void Start()
        {
            HostBridge.Ready();
            if (prm.Job != null && !prm.ForceMock)
                StartLoad(JobBaseUrl(prm.Api ?? ViewerParams.DefaultApiBase, prm.Job));
            else
                StartLoad(MockBaseUrl());
        }

        T NewChild<T>(string name) where T : Component
        {
            var go = new GameObject(name);
            go.transform.SetParent(transform, false);
            return go.AddComponent<T>();
        }

        void CreateCameraAndLight()
        {
            var camGo = new GameObject("Main Camera") { tag = "MainCamera" };
            camGo.transform.SetParent(transform, false);
            cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.62f, 0.76f, 0.92f);
            cam.fieldOfView = 60f;

            var lightGo = new GameObject("Sun");
            lightGo.transform.SetParent(transform, false);
            lightGo.transform.rotation = Quaternion.Euler(52f, -35f, 0f);
            var light = lightGo.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.15f;
            light.color = new Color(1f, 0.96f, 0.9f);
            light.shadows = LightShadows.None; // shadows would need a URP shadow distance covering the whole terrain

            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.72f, 0.78f, 0.88f);
            RenderSettings.ambientEquatorColor = new Color(0.5f, 0.5f, 0.5f);
            RenderSettings.ambientGroundColor = new Color(0.3f, 0.28f, 0.25f);
        }

        // ------------------------------------------------------------------ host API

        /// <summary>
        /// Called by the host page via SendMessage. Accepts {"api":"http://...","job":"abc123"}
        /// (also apiBase / jobId) or a bare job id string. A missing api falls back to the page's api param.
        /// </summary>
        public void LoadJob(string json)
        {
            string api = null, job = null;
            string t = json == null ? "" : json.Trim();
            if (t.StartsWith("{", StringComparison.Ordinal))
            {
                try
                {
                    var d = MiniJson.Parse(t) as Dictionary<string, object>;
                    api = Str(d, "api") ?? Str(d, "apiBase");
                    job = Str(d, "job") ?? Str(d, "jobId");
                }
                catch (FormatException e) { Fail("LoadJob received invalid JSON: " + e.Message); return; }
            }
            else if (t.Length > 0) job = t;

            if (job == null) { Fail("LoadJob needs a job id, e.g. {\"api\":\"http://localhost:8000\",\"job\":\"abc123\"}."); return; }
            StartLoad(JobBaseUrl(api ?? prm.Api ?? ViewerParams.DefaultApiBase, job));
        }

        /// <summary>
        /// Called by the host page via SendMessage with one JSON command: water, pin, explosion, fire, drop, landing,
        /// focus, pick or clear (see ScenarioController). Positions are fractions of the world width/depth.
        /// </summary>
        public void RunScenario(string json) => scenarios.Run(json);

        static string Str(Dictionary<string, object> d, string key) =>
            d != null && d.TryGetValue(key, out object v) && v is string s && s.Length > 0 ? s : null;

        // ------------------------------------------------------------------ URLs

        static string JobBaseUrl(string api, string job) =>
            api.TrimEnd('/') + "/api/pipeline/output/" + Uri.EscapeDataString(job) + "/";

        static string MockBaseUrl()
        {
            string p = Application.streamingAssetsPath;
            if (!p.Contains("://")) p = new Uri(p).AbsoluteUri; // editor / standalone: file:///...
            return p.TrimEnd('/') + "/mock/";
        }

        static string FileUrl(string baseUrl, string file) =>
            baseUrl + Uri.EscapeDataString(file).Replace("%2F", "/");

        // ------------------------------------------------------------------ loading

        void Reload()
        {
            if (lastBaseUrl != null) StartLoad(lastBaseUrl);
        }

        void StartLoad(string baseUrl)
        {
            if (loading != null) StopCoroutine(loading);
            lastBaseUrl = baseUrl;
            loading = StartCoroutine(LoadRoutine(baseUrl));
        }

        IEnumerator LoadRoutine(string baseUrl)
        {
            HostBridge.ResetProgress();
            scenarios.Clear();
            scene = null;
            buildings.Clear();
            props.Clear();
            terrain.Clear();
            ui.ClearSelection();
            Report("Contacting server...", 0f);

            // 1. scene description
            var sceneDl = new Download();
            yield return Fetch(FileUrl(baseUrl, "unity_scene.json"), sceneDl, false, p => Report("Loading scene description...", ProgressScene * p));
            if (sceneDl.Error != null) { Fail(sceneDl.Error); yield break; }

            SceneData data;
            try { data = SceneData.Parse(sceneDl.Text); }
            catch (ViewerLoadException e) { Fail(e.Message); yield break; }

            // 2. heightmap (raw bytes; decoded ourselves to keep 16-bit precision)
            var hmDl = new Download();
            yield return Fetch(FileUrl(baseUrl, data.HeightmapFile), hmDl, true,
                p => Report("Downloading heightmap...", Mathf.Lerp(ProgressScene, ProgressHeightmap, p)));
            if (hmDl.Error != null) { Fail(hmDl.Error); yield break; }

            Report("Decoding heightmap...", ProgressHeightmap);
            yield return null; // let the bar repaint before the blocking decode
            HeightField field;
            try { field = HeightField.FromR16(hmDl.Data, data); }
            catch (ViewerLoadException e) { Fail(e.Message); yield break; }
            hmDl.Data = null;

            // 3. texture
            Texture2D texture = null;
            if (!string.IsNullOrEmpty(data.TextureFile))
            {
                var texDl = new Download();
                yield return Fetch(FileUrl(baseUrl, data.TextureFile), texDl, true,
                    p => Report("Downloading texture...", Mathf.Lerp(ProgressHeightmap, ProgressTexture, p)));
                if (texDl.Error != null) { Fail(texDl.Error); yield break; }

                texture = new Texture2D(2, 2, TextureFormat.RGBA32, true, false)
                {
                    name = "Imagery",
                    wrapMode = TextureWrapMode.Clamp,
                    filterMode = FilterMode.Trilinear,
                    anisoLevel = 4,
                };
                // markNonReadable: we never read pixels back, so keep only the GPU copy.
                if (!texture.LoadImage(texDl.Data, true))
                {
                    Destroy(texture);
                    Fail($"'{data.TextureFile}' could not be decoded as an image.");
                    yield break;
                }
            }

            // 4. terrain
            Report("Building terrain...", ProgressTexture);
            yield return null;
            string error = null;
            try { terrain.Build(field, texture); }
            catch (Exception e) { error = "Could not build the terrain mesh: " + e.Message; }
            if (error != null) { Fail(error); yield break; }

            // 5. buildings, in slices so the loading bar keeps moving
            Report("Building structures...", ProgressTerrain);
            // With imagery each roof shows its real photo; without it, the sampled roof colour as a flat colour.
            var builder = new BuildingMeshBuilder(field, 0f, texture != null ? BuildingLook.Imagery : BuildingLook.FlatColour);
            int total = data.Buildings.Count, skipped = data.SkippedBuildings;
            for (int i = 0; i < total; i++)
            {
                if (!builder.Add(data.Buildings[i])) skipped++;
                if ((i & 127) == 127)
                {
                    Report("Building structures...", Mathf.Lerp(ProgressTerrain, ProgressBuildings, (float)i / total));
                    yield return null;
                }
            }
            try { buildings.Show(builder.Finish(true), terrain.WorldRoot, field, texture); }
            catch (Exception e) { error = "Could not build the building meshes: " + e.Message; }
            if (error != null) { Fail(error); yield break; }
            if (skipped > 0) Debug.LogWarning($"[Viewer] skipped {skipped} building(s) with degenerate footprints.");

            // 5b. detected vehicles / tanks / pools and trees (optional: older scenes have neither)
            if (data.Objects.Count + data.Trees.Count > 0)
            {
                Report("Placing vehicles and trees...", ProgressBuildings);
                yield return null;
                var propBuilder = new ObjectMeshBuilder(field);
                try
                {
                    foreach (ObjectData o in data.Objects) propBuilder.AddObject(o);
                    for (int i = 0; i < data.Trees.Count; i++) propBuilder.AddTree(data.Trees[i], i + 1);
                    props.Show(propBuilder.Finish(), terrain.WorldRoot);
                }
                catch (Exception e) { error = "Could not build the vehicle and tree meshes: " + e.Message; }
                if (error != null) { Fail(error); yield break; }
            }

            // 6. zones
            Report("Painting disaster zones...", ProgressBuildings);
            yield return null;
            try
            {
                terrain.SetZoneTexture(data.Zones.Count > 0
                    ? ZoneRasterizer.Rasterize(data.Zones, data.WorldSizeX, data.WorldSizeZ)
                    : null);
            }
            catch (Exception e) { error = "Could not paint the disaster zones: " + e.Message; }
            if (error != null) { Fail(error); yield break; }

            // 7. done
            scene = data;
            interaction.SetMetric(data.IsMetric);
            rig.Frame(field);
            ui.ConfigureForScene(data.IsMetric, terrain.HasZones, rig.TouchOnly);
            ui.RefreshCameraLabel();
            ui.HideLoading();
            HostBridge.Progress(1f);
            loading = null;
        }

        void Report(string status, float progress)
        {
            ui.ShowLoading(status, progress);
            HostBridge.Progress(progress);
        }

        void OnBuildingSelected(BuildingData b)
        {
            ui.SetSelection(b, scene != null && scene.IsMetric);
            if (b != null) HostBridge.BuildingSelected(b.Id, b.HeightM);
        }

        void Fail(string message)
        {
            Debug.LogError("[Viewer] " + message);
            loading = null;
            ui.ShowError(message);
            HostBridge.Error(message);
        }

        // ------------------------------------------------------------------ networking

        IEnumerator Fetch(string url, Download result, bool binary, Action<float> progress)
        {
            using (UnityWebRequest req = UnityWebRequest.Get(url))
            {
                UnityWebRequestAsyncOperation op = req.SendWebRequest();
                while (!op.isDone)
                {
                    progress?.Invoke(req.downloadProgress);
                    yield return null;
                }
                progress?.Invoke(1f);

                if (req.result == UnityWebRequest.Result.Success)
                {
                    if (binary) result.Data = req.downloadHandler.data;
                    else result.Text = req.downloadHandler.text;
                    yield break;
                }
                result.Error = Describe(req, url);
            }
        }

        static string Describe(UnityWebRequest req, string url)
        {
            long code = req.responseCode;
            if (code == 404)
                return $"Not found (404): {url}\nCheck the job id, and that the backend has produced this file for the job.";
            if (code >= 400)
                return $"The server answered HTTP {code} for {url}\n{req.error}";
            if (req.result == UnityWebRequest.Result.ConnectionError || code == 0)
            {
                string origin = "";
                try { if (!string.IsNullOrEmpty(Application.absoluteURL)) origin = new Uri(Application.absoluteURL).GetLeftPart(UriPartial.Authority); }
                catch (UriFormatException) { }
                return $"Could not reach {url}\nThe backend may be offline, or the browser blocked the request (CORS): " +
                       $"the backend must allow the page origin{(origin.Length > 0 ? " " + origin : "")}.\n({req.error})";
            }
            return $"Downloading {url} failed: {req.error}";
        }
    }
}
