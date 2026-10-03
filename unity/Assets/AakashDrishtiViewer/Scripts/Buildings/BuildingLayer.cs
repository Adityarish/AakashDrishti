using System;
using AakashDrishti.Viewer.Loading;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Buildings
{
    /// <summary>Scene objects for the combined building mesh, ray picking and the selection highlight.</summary>
    public sealed class BuildingLayer : MonoBehaviour
    {
        const float HighlightInflate = 0.35f;

        public event Action<BuildingData> SelectionChanged;
        public BuildingData Selected { get; private set; }

        Material buildingMat, highlightMat;
        GameObject buildingsGo, highlightGo;
        BuildingSet set;
        MeshCollider buildingCollider;
        Transform parent;
        HeightField field;

        void Awake()
        {
            buildingMat = new Material(Resources.Load<Material>("AakashDrishtiViewer/Building"));
            highlightMat = new Material(Resources.Load<Material>("AakashDrishtiViewer/BuildingHighlight"));
        }

        /// <param name="imagery">The scene photo; roofs sample it so each building shows its real rooftop. Null = flat colours.</param>
        public void Show(BuildingSet buildings, Transform worldRoot, HeightField hf, Texture imagery = null)
        {
            Clear();
            buildingMat.SetFloat("_UseVertexColor", 1f);
            buildingMat.SetColor("_BaseColor", Color.white); // colour now comes from the vertices / imagery
            if (imagery != null) buildingMat.SetTexture("_BaseMap", imagery);
            set = buildings;
            parent = worldRoot;
            field = hf;
            if (buildings.Buildings.Length == 0) return;

            buildingsGo = new GameObject("Buildings");
            buildingsGo.transform.SetParent(worldRoot, false);
            buildingsGo.AddComponent<MeshFilter>().sharedMesh = buildings.Mesh;
            var mr = buildingsGo.AddComponent<MeshRenderer>();
            mr.sharedMaterial = buildingMat;
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
            buildingCollider = buildingsGo.AddComponent<MeshCollider>();
            buildingCollider.sharedMesh = buildings.Mesh;
        }

        /// <summary>Picks the building under the ray; clears the selection when the ray hits anything else.</summary>
        public void PickAt(Ray ray, float maxDistance)
        {
            BuildingData hit = null;
            if (buildingCollider != null && Physics.Raycast(ray, out RaycastHit h, maxDistance) && h.collider == buildingCollider)
                hit = set.FromTriangle(h.triangleIndex);
            Select(hit);
        }

        public void Select(BuildingData b)
        {
            if (b == Selected) return;
            Selected = b;
            if (highlightGo != null)
            {
                Destroy(highlightGo.GetComponent<MeshFilter>().sharedMesh);
                Destroy(highlightGo);
                highlightGo = null;
            }
            if (b != null) BuildHighlight(b);
            SelectionChanged?.Invoke(b);
        }

        void BuildHighlight(BuildingData b)
        {
            // A slightly inflated copy of just this building, drawn in the highlight colour.
            var builder = new BuildingMeshBuilder(field, HighlightInflate, BuildingLook.Plain);
            if (!builder.Add(b)) return;
            highlightGo = new GameObject("SelectedBuilding");
            highlightGo.transform.SetParent(parent, false);
            highlightGo.AddComponent<MeshFilter>().sharedMesh = builder.Finish(false).Mesh;
            var mr = highlightGo.AddComponent<MeshRenderer>();
            mr.sharedMaterial = highlightMat;
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
        }

        public void Clear()
        {
            Selected = null;
            if (highlightGo != null)
            {
                Destroy(highlightGo.GetComponent<MeshFilter>().sharedMesh);
                Destroy(highlightGo);
            }
            if (buildingsGo != null) Destroy(buildingsGo);
            if (set != null && set.Mesh != null) Destroy(set.Mesh);
            highlightGo = buildingsGo = null;
            buildingCollider = null;
            set = null;
        }

        void OnDestroy()
        {
            if (buildingMat != null) Destroy(buildingMat);
            if (highlightMat != null) Destroy(highlightMat);
        }
    }
}
