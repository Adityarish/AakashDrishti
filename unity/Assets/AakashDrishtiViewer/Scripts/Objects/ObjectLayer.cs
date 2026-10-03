using UnityEngine;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Objects
{
    /// <summary>
    /// Scene object for the combined vehicle/tank/pool/tree mesh. It has no collider on purpose: picking stays
    /// with buildings and terrain, and small props never swallow a click meant for the ground or a roof.
    /// </summary>
    public sealed class ObjectLayer : MonoBehaviour
    {
        Material material;
        GameObject go;
        Mesh mesh;

        void Awake()
        {
            material = new Material(Resources.Load<Material>("AakashDrishtiViewer/Building"));
            material.SetFloat("_UseVertexColor", 1f);
            material.SetColor("_BaseColor", Color.white);
        }

        public void Show(Mesh objectMesh, Transform worldRoot)
        {
            Clear();
            mesh = objectMesh;
            go = new GameObject("Objects");
            go.transform.SetParent(worldRoot, false);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterial = material;
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
        }

        public void SetVisible(bool visible)
        {
            if (go != null) go.SetActive(visible);
        }

        public void Clear()
        {
            if (go != null) Destroy(go);
            if (mesh != null) Destroy(mesh);
            go = null;
            mesh = null;
        }

        void OnDestroy()
        {
            if (material != null) Destroy(material);
        }
    }
}
