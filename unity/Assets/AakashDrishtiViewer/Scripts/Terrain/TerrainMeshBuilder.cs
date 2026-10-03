using UnityEngine;
using UnityEngine.Rendering;

namespace AakashDrishti.Viewer.Terrains
{
    public static class TerrainMeshBuilder
    {
        /// <summary>Render mesh: one vertex per height sample, UInt32 indices, recalculated normals.</summary>
        public static Mesh BuildRender(HeightField hf)
        {
            int nx = hf.Width, nz = hf.Height;
            var verts = new Vector3[nx * nz];
            for (int j = 0; j < nz; j++)
            {
                float z = (float)j / (nz - 1) * hf.SizeZ;
                for (int i = 0; i < nx; i++)
                    verts[j * nx + i] = new Vector3((float)i / (nx - 1) * hf.SizeX, hf.Heights[j * nx + i], z);
            }
            var mesh = Create("Terrain", verts, nx, nz, hf);
            mesh.RecalculateNormals();
            mesh.UploadMeshData(true); // render-only: free the CPU copy
            return mesh;
        }

        /// <summary>
        /// Coarser mesh for the MeshCollider. Cooking a 500k-triangle collider is slow and memory hungry in
        /// WebGL, and raycasts only need the coarse shape; exact heights come from HeightField.Sample.
        /// </summary>
        public static Mesh BuildCollider(HeightField hf, int maxDim = 128)
        {
            int nx = Mathf.Min(hf.Width, maxDim), nz = Mathf.Min(hf.Height, maxDim);
            var verts = new Vector3[nx * nz];
            for (int j = 0; j < nz; j++)
            {
                float z = (float)j / (nz - 1) * hf.SizeZ;
                for (int i = 0; i < nx; i++)
                {
                    float x = (float)i / (nx - 1) * hf.SizeX;
                    verts[j * nx + i] = new Vector3(x, hf.Sample(x, z), z);
                }
            }
            return Create("TerrainCollider", verts, nx, nz, hf);
        }

        static Mesh Create(string name, Vector3[] verts, int nx, int nz, HeightField hf)
        {
            var uvs = new Vector2[verts.Length];
            for (int j = 0; j < nz; j++)
                for (int i = 0; i < nx; i++)
                    uvs[j * nx + i] = new Vector2((float)i / (nx - 1), (float)j / (nz - 1));

            // Two triangles per cell, clockwise seen from above (+Y) with x = east, z = north.
            var tris = new int[(nx - 1) * (nz - 1) * 6];
            int t = 0;
            for (int j = 0; j < nz - 1; j++)
            {
                for (int i = 0; i < nx - 1; i++)
                {
                    int a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
                    tris[t++] = a; tris[t++] = c; tris[t++] = b;
                    tris[t++] = b; tris[t++] = c; tris[t++] = d;
                }
            }

            var mesh = new Mesh { name = name, indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(verts);
            mesh.SetUVs(0, uvs);
            mesh.SetIndices(tris, MeshTopology.Triangles, 0);
            mesh.RecalculateBounds();
            return mesh;
        }
    }
}
