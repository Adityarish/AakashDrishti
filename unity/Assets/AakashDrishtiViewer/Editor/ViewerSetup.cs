using System.IO;
using AakashDrishti.Viewer.Loading;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Editor
{
    /// <summary>
    /// One-click project setup and WebGL build: materials, the single-object scene, and Player Settings.
    /// Menu: AakashDrishti > Setup Viewer / Build WebGL. Batch: -executeMethod ...ViewerSetup.BuildWebGL
    /// </summary>
    public static class ViewerSetup
    {
        const string Root = "Assets/AakashDrishtiViewer";
        const string MaterialFolder = Root + "/Resources/AakashDrishtiViewer";
        public const string ScenePath = Root + "/Scenes/Viewer.unity";
        const string BuildPath = "Builds/WebGL";

        [MenuItem("AakashDrishti/Setup Viewer")]
        public static void SetupAll()
        {
            CreateMaterials();
            CreateScene();
            ConfigureWebGL();
            AssetDatabase.SaveAssets();
            Debug.Log("[ViewerSetup] Done. Scene: " + ScenePath);
        }

        [MenuItem("AakashDrishti/Build WebGL")]
        public static void BuildWebGL()
        {
            SetupAll();
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = BuildPath,
                target = BuildTarget.WebGL,
                targetGroup = BuildTargetGroup.WebGL,
                options = BuildOptions.None,
            };
            var report = BuildPipeline.BuildPlayer(options);
            Debug.Log($"[ViewerSetup] WebGL build {report.summary.result}, {report.summary.totalSize / (1024 * 1024)} MB -> {BuildPath}");
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
                throw new BuildFailedException("WebGL build failed: " + report.summary.result);
        }

        // ------------------------------------------------------------------ materials

        static void CreateMaterials()
        {
            EnsureFolder(Root + "/Resources");
            EnsureFolder(MaterialFolder);

            // Custom single-variant shader instead of URP/Lit: see SimpleLit.shader.
            const string lit = "AakashDrishti/SimpleLit";
            GetOrCreate("Terrain", lit).SetColor("_BaseColor", Color.white);
            GetOrCreate("Building", lit).SetColor("_BaseColor", new Color(0.86f, 0.84f, 0.80f, 1f));

            Material highlight = GetOrCreate("BuildingHighlight", lit);
            highlight.SetColor("_BaseColor", new Color(1f, 0.80f, 0.12f, 1f));
            highlight.SetColor("_EmissionColor", new Color(0.55f, 0.38f, 0f, 1f));

            GetOrCreate("ZoneOverlay", "AakashDrishti/ZoneOverlay");
            // Scenario effects (fire, explosion, flood water, aircraft). Kept as assets in Resources so their
            // shaders are always included in the WebGL build.
            GetOrCreate("FxAdd", "AakashDrishti/FxAdd");
            GetOrCreate("FxAlpha", "AakashDrishti/FxAlpha");
            GetOrCreate("Water", "AakashDrishti/Water");
            AssetDatabase.SaveAssets();
        }

        static Material GetOrCreate(string name, string shaderName)
        {
            string path = $"{MaterialFolder}/{name}.mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            Shader shader = Shader.Find(shaderName);
            if (shader == null) throw new System.Exception("Shader not found: " + shaderName);
            if (m == null)
            {
                m = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(m, path);
            }
            else m.shader = shader;
            return m;
        }

        // ------------------------------------------------------------------ scene

        static void CreateScene()
        {
            EnsureFolder(Root + "/Scenes");
            // Additive + close: leaves whatever scene the user has open untouched.
            // In batch mode there is no open scene to preserve, and an unsaved untitled scene blocks additive creation.
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, Application.isBatchMode ? NewSceneMode.Single : NewSceneMode.Additive);
            var go = new GameObject("ViewerBootstrap");
            go.AddComponent<ViewerBootstrap>();
            EditorSceneManager.SaveScene(scene, ScenePath);
            if (!Application.isBatchMode) EditorSceneManager.CloseScene(scene, true);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        }

        // ------------------------------------------------------------------ player settings

        static void ConfigureWebGL()
        {
            PlayerSettings.productName = "AakashDrishti Viewer";
            PlayerSettings.WebGL.template = "PROJECT:AakashDrishti";
            PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Gzip;
            PlayerSettings.WebGL.decompressionFallback = true;   // works on hosts that cannot send Content-Encoding
            PlayerSettings.WebGL.initialMemorySize = 512;        // MB
            PlayerSettings.WebGL.maximumMemorySize = 2048;       // MB, memory may grow up to this
            PlayerSettings.WebGL.memoryGrowthMode = WebGLMemoryGrowthMode.Geometric;
            PlayerSettings.WebGL.exceptionSupport = WebGLExceptionSupport.ExplicitlyThrownExceptionsOnly;
            PlayerSettings.WebGL.threadsSupport = false;
            PlayerSettings.WebGL.dataCaching = true;
            PlayerSettings.WebGL.nameFilesAsHashes = false;
            PlayerSettings.runInBackground = true;
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.WebGL, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.WebGL, new[] { GraphicsDeviceType.OpenGLES3 });
        }

        static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            string parent = Path.GetDirectoryName(path).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
        }
    }
}
