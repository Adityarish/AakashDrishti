using System.Collections;
using System.IO;
using AakashDrishti.Viewer.Loading;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AakashDrishti.Viewer.Editor
{
    /// <summary>
    /// Renders each scenario animation of the mock scene to PNG files so the effects can be reviewed without a browser.
    /// Batch: Unity -batchmode -projectPath unity -executeMethod AakashDrishti.Viewer.Editor.ScenarioPreview.Run
    /// Output folder: environment variable AD_PREVIEW_OUT (default Builds/Preview).
    /// </summary>
    public static class ScenarioPreview
    {
        public static void Run()
        {
            EditorSceneManager.OpenScene(ViewerSetup.ScenePath);
            EditorApplication.playModeStateChanged += OnPlayMode;
            EditorApplication.isPlaying = true;
        }

        static void OnPlayMode(PlayModeStateChange change)
        {
            if (change != PlayModeStateChange.EnteredPlayMode) return;
            EditorApplication.playModeStateChanged -= OnPlayMode;
            new GameObject("PreviewCapture").AddComponent<PreviewCapture>();
        }
    }

    public sealed class PreviewCapture : MonoBehaviour
    {
        const int W = 1280, H = 720;
        string outDir;
        ViewerBootstrap bootstrap;
        Camera cam;

        IEnumerator Start()
        {
            outDir = System.Environment.GetEnvironmentVariable("AD_PREVIEW_OUT");
            if (string.IsNullOrEmpty(outDir)) outDir = "Builds/Preview";
            Directory.CreateDirectory(outDir);

            // wait for the mock scene to finish loading
            for (int i = 0; i < 600; i++) yield return null;
            bootstrap = FindFirstObjectByType<ViewerBootstrap>();
            cam = Camera.main;
            if (bootstrap == null || cam == null) { Debug.LogError("[Preview] no viewer or camera"); EditorApplication.Exit(2); yield break; }
            yield return Shot("00_plain");

            // ---- flood: water rising
            Cmd("{\"cmd\":\"focus\",\"u\":0.5,\"v\":0.5,\"distance\":0.9}");
            yield return Wait(1.8f);
            foreach (float level in new[] { 4f, 12f, 24f })
            {
                Cmd("{\"cmd\":\"water\",\"level\":" + level.ToString(System.Globalization.CultureInfo.InvariantCulture) + "}");
                yield return Wait(0.5f);
                yield return Shot("10_flood_" + level);
            }
            Cmd("{\"cmd\":\"water\"}");

            // ---- explosion
            Cmd("{\"cmd\":\"pin\",\"u\":0.45,\"v\":0.5}");
            Cmd("{\"cmd\":\"focus\",\"u\":0.45,\"v\":0.5,\"distance\":0.45}");
            yield return Wait(1.8f);
            yield return Shot("20_pin");
            Cmd("{\"cmd\":\"explosion\",\"u\":0.45,\"v\":0.5,\"radii\":[80,40,20]}");
            foreach (float t in new[] { 0.25f, 0.6f, 1.2f, 2.2f, 4.0f, 7.0f })
            {
                yield return Wait(t - last);
                yield return Shot("21_blast_" + t.ToString("0.0"));
            }
            Cmd("{\"cmd\":\"clear\"}");

            // ---- wildfire: ignite, then drop
            Cmd("{\"cmd\":\"fire\",\"u\":0.55,\"v\":0.45}");
            Cmd("{\"cmd\":\"focus\",\"u\":0.55,\"v\":0.45,\"distance\":0.3}");
            foreach (float t in new[] { 0.6f, 1.6f, 3.2f, 5.0f })
            {
                yield return Wait(t - last);
                yield return Shot("30_fire_" + t.ToString("0.0"));
            }
            Cmd("{\"cmd\":\"drop\",\"u\":0.55,\"v\":0.45,\"hover\":30,\"reach\":49}");
            Cmd("{\"cmd\":\"focus\",\"u\":0.55,\"v\":0.45,\"distance\":0.42}");
            foreach (float t in new[] { 1.5f, 3.0f, 5.0f, 7.0f, 9.5f, 12.0f, 15.0f })
            {
                yield return Wait(t - last);
                yield return Shot("31_drop_" + t.ToString("0.0"));
            }
            Cmd("{\"cmd\":\"clear\"}");

            // ---- landing
            foreach (string kind in new[] { "helicopter", "drone", "plane" })
            {
                Cmd("{\"cmd\":\"landing\",\"kind\":\"" + kind + "\",\"u\":0.4,\"v\":0.4,\"radius\":20,\"bearing\":60,\"fits\":" + (kind == "plane" ? "false" : "true") + "}");
                Cmd("{\"cmd\":\"focus\",\"u\":0.4,\"v\":0.4,\"distance\":0.3}");
                foreach (float t in new[] { 1.5f, 3.5f, 5.5f, 8.5f })
                {
                    yield return Wait(t - last);
                    yield return Shot("40_" + kind + "_" + t.ToString("0.0"));
                }
                Cmd("{\"cmd\":\"clear\"}");
            }

            Debug.Log("[Preview] done -> " + Path.GetFullPath(outDir));
            EditorApplication.Exit(0);
        }

        float last;

        void Cmd(string json)
        {
            if (json.Contains("\"explosion\"") || json.Contains("\"fire\"") || json.Contains("\"drop\"") || json.Contains("\"landing\"")) last = 0f;
            bootstrap.RunScenario(json);
        }

        IEnumerator Wait(float seconds)
        {
            if (seconds <= 0f) yield break;
            float t = 0f;
            while (t < seconds) { t += Time.deltaTime; yield return null; }
            last += seconds;
        }

        IEnumerator Shot(string name)
        {
            yield return new WaitForEndOfFrame();
            var rt = new RenderTexture(W, H, 24);
            RenderTexture prev = cam.targetTexture;
            cam.targetTexture = rt;
            cam.Render();
            cam.targetTexture = prev;
            RenderTexture.active = rt;
            var tex = new Texture2D(W, H, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, W, H), 0, 0);
            tex.Apply();
            RenderTexture.active = null;
            File.WriteAllBytes(Path.Combine(outDir, name + ".png"), tex.EncodeToPNG());
            Destroy(tex);
            rt.Release();
            Destroy(rt);
        }
    }
}
