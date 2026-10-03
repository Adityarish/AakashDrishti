using System;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.InputSystem;

namespace AakashDrishti.Viewer.Cameras
{
    public enum CameraMode { Orbit, Fly }

    /// <summary>Switches between the orbit and first-person controllers that share one Camera.</summary>
    public sealed class CameraRig : MonoBehaviour
    {
        public event Action<CameraMode> ModeChanged;

        public Camera Cam { get; private set; }
        public CameraMode Mode { get; private set; } = CameraMode.Orbit;
        /// <summary>Touch devices get the orbit camera only (no keyboard / pointer lock).</summary>
        public bool TouchOnly { get; private set; }

        TerrainView terrain;
        FlyCameraController fly;
        OrbitCameraController orbit;

        public void Init(Camera cam, TerrainView terrainView)
        {
            Cam = cam;
            terrain = terrainView;
            TouchOnly = Application.isMobilePlatform;
            fly = cam.gameObject.AddComponent<FlyCameraController>();
            orbit = cam.gameObject.AddComponent<OrbitCameraController>();
            fly.Terrain = orbit.Terrain = terrainView;
            fly.enabled = false;
            orbit.enabled = false; // enabled by Frame() once there is a terrain
        }

        /// <summary>Places the camera above the terrain corner-on and resets both controllers.</summary>
        public void Frame(HeightField f)
        {
            float size = Mathf.Max(f.SizeX, f.SizeZ);
            Cam.nearClipPlane = Mathf.Max(0.3f, size * 0.0006f);
            Cam.farClipPlane = size * 10f;
            fly.BaseSpeed = size * 0.08f;
            orbit.MinDistance = Mathf.Max(3f, size * 0.006f);
            orbit.MaxDistance = size * 3f;

            Vector3 center = new Vector3(f.SizeX * 0.5f, 0f, f.SizeZ * 0.5f);
            orbit.SetPose(center, size * 1.1f, 25f, 40f);
            Mode = CameraMode.Orbit; // a reload starts from the framed orbit view, not the old fly pose
            SetMode(CameraMode.Orbit);
        }

        /// <summary>Flies the orbit camera to a point (switching back from the fly camera if needed).</summary>
        public void FocusOn(Vector3 target, float distance)
        {
            if (terrain == null || terrain.Field == null) return;
            if (Mode == CameraMode.Fly) SetMode(CameraMode.Orbit);
            orbit.FocusOn(target, distance);
        }

        public void Toggle() => SetMode(Mode == CameraMode.Orbit ? CameraMode.Fly : CameraMode.Orbit);

        public void SetMode(CameraMode mode)
        {
            if (TouchOnly) mode = CameraMode.Orbit;
            if (terrain == null || terrain.Field == null) return;

            if (mode == CameraMode.Fly)
            {
                orbit.enabled = false;
                fly.enabled = true;
                fly.SyncAnglesFromTransform();
                fly.ClampToWorld();
            }
            else
            {
                fly.enabled = false; // releases the pointer
                orbit.enabled = true;
                if (Mode == CameraMode.Fly) orbit.SyncFromTransform();
            }
            Mode = mode;
            ModeChanged?.Invoke(mode);
        }

        public bool PointerLocked => Mode == CameraMode.Fly && fly.PointerLocked;

        void Update()
        {
            if (Keyboard.current != null && Keyboard.current.cKey.wasPressedThisFrame && !TouchOnly) Toggle();
        }
    }
}
