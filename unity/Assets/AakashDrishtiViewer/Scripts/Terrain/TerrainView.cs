using AakashDrishti.Viewer.Loading;
using UnityEngine;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Terrains
{
    public enum OverlayMode { Rgb, Elevation, Zones }

    /// <summary>
    /// Owns the terrain GameObjects. Everything spatial (terrain, zones, buildings) hangs under WorldRoot,
    /// whose Y scale is the vertical exaggeration, so one slider moves all of it consistently.
    /// </summary>
    public sealed class TerrainView : MonoBehaviour
    {
        const string MaterialFolder = "AakashDrishtiViewer/";
        static readonly int BaseMapId = Shader.PropertyToID("_BaseMap");
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");
        static readonly int StrengthId = Shader.PropertyToID("_Strength");

        public Transform WorldRoot { get; private set; }
        public HeightField Field { get; private set; }
        public Collider TerrainCollider { get; private set; }
        public float Exaggeration { get; private set; } = 1f;
        public OverlayMode Mode { get; private set; } = OverlayMode.Rgb;
        public bool ZonesVisible { get; private set; } = false; // off by default; the UI toggle (also off) turns it on
        public bool HasZones => zoneTex != null;

        Material terrainMat, zoneMat;
        Texture2D rgbTex, elevationTex, zoneTex;
        GameObject terrainGo, overlayGo;
        Mesh renderMesh, colliderMesh;
        MeshRenderer overlayRenderer;

        void Awake()
        {
            WorldRoot = new GameObject("World").transform;
            WorldRoot.SetParent(transform, false);
            terrainMat = new Material(LoadMaterial("Terrain"));
            zoneMat = new Material(LoadMaterial("ZoneOverlay"));
        }

        static Material LoadMaterial(string name)
        {
            var m = Resources.Load<Material>(MaterialFolder + name);
            if (m == null)
                throw new ViewerLoadException($"Material 'Resources/{MaterialFolder}{name}' is missing. Run the menu AakashDrishti > Setup Viewer.");
            return m;
        }

        public void Build(HeightField hf, Texture2D rgb)
        {
            Clear();
            Field = hf;
            rgbTex = rgb;
            elevationTex = ElevationColormap.BuildTexture(hf);
            renderMesh = TerrainMeshBuilder.BuildRender(hf);
            colliderMesh = TerrainMeshBuilder.BuildCollider(hf);

            terrainGo = new GameObject("Terrain");
            terrainGo.transform.SetParent(WorldRoot, false);
            // The collider goes first: added after a MeshFilter it would grab the (non-readable) render mesh.
            var mc = terrainGo.AddComponent<MeshCollider>();
            mc.sharedMesh = colliderMesh;
            TerrainCollider = mc;
            terrainGo.AddComponent<MeshFilter>().sharedMesh = renderMesh;
            var mr = terrainGo.AddComponent<MeshRenderer>();
            mr.sharedMaterial = terrainMat;
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;

            ApplyExaggeration();
            ApplyMode();
        }

        public void SetZoneTexture(Texture2D tex)
        {
            if (overlayGo != null) Destroy(overlayGo);
            if (zoneTex != null) Destroy(zoneTex);
            overlayGo = null; overlayRenderer = null;
            zoneTex = tex;
            if (tex != null && renderMesh != null)
            {
                overlayGo = new GameObject("DisasterZones");
                overlayGo.transform.SetParent(WorldRoot, false);
                overlayGo.AddComponent<MeshFilter>().sharedMesh = renderMesh;
                overlayRenderer = overlayGo.AddComponent<MeshRenderer>();
                overlayRenderer.sharedMaterial = zoneMat;
                overlayRenderer.shadowCastingMode = ShadowCastingMode.Off;
                overlayRenderer.receiveShadows = false;
                zoneMat.SetTexture(BaseMapId, tex);
            }
            ApplyMode();
        }

        public void SetMode(OverlayMode mode) { Mode = mode; ApplyMode(); }
        public void SetZonesVisible(bool visible) { ZonesVisible = visible; ApplyMode(); }

        public void SetExaggeration(float value)
        {
            Exaggeration = Mathf.Clamp(value, 1f, 5f);
            ApplyExaggeration();
        }

        void ApplyExaggeration() => WorldRoot.localScale = new Vector3(1f, Exaggeration, 1f);

        void ApplyMode()
        {
            if (terrainGo == null) return;
            Texture baseTex = Mode == OverlayMode.Elevation || rgbTex == null ? elevationTex : rgbTex;
            terrainMat.SetTexture(BaseMapId, baseTex);
            // In zones mode the imagery is dimmed so the coloured zones dominate.
            terrainMat.SetColor(BaseColorId, Mode == OverlayMode.Zones ? new Color(0.55f, 0.55f, 0.55f, 1f) : Color.white);

            if (overlayRenderer != null)
            {
                overlayRenderer.enabled = Mode == OverlayMode.Zones || ZonesVisible;
                zoneMat.SetFloat(StrengthId, Mode == OverlayMode.Zones ? 0.9f : 0.5f);
            }
        }

        public void Clear()
        {
            if (terrainGo != null) Destroy(terrainGo);
            if (overlayGo != null) Destroy(overlayGo);
            if (renderMesh != null) Destroy(renderMesh);
            if (colliderMesh != null) Destroy(colliderMesh);
            if (rgbTex != null) Destroy(rgbTex);
            if (elevationTex != null) Destroy(elevationTex);
            if (zoneTex != null) Destroy(zoneTex);
            terrainGo = overlayGo = null;
            renderMesh = colliderMesh = null;
            rgbTex = elevationTex = zoneTex = null;
            overlayRenderer = null;
            TerrainCollider = null;
            Field = null;
        }

        void OnDestroy()
        {
            if (terrainMat != null) Destroy(terrainMat);
            if (zoneMat != null) Destroy(zoneMat);
        }
    }
}
