using AakashDrishti.Viewer.Terrains;
using AakashDrishti.Viewer.Ui;
using UnityEngine;
using UnityEngine.InputSystem;

namespace AakashDrishti.Viewer.Cameras
{
    /// <summary>First-person flythrough: WASD + mouse look (pointer lock), Shift faster, Q/E down/up.</summary>
    public sealed class FlyCameraController : MonoBehaviour
    {
        const float LookDegreesPerPixel = 0.12f;
        const float MinClearance = 2f;

        public TerrainView Terrain;
        public float BaseSpeed = 30f;

        float yaw, pitch;

        public bool PointerLocked => Cursor.lockState == CursorLockMode.Locked;

        void OnEnable() => SyncAnglesFromTransform();

        void OnDisable() => ReleasePointer();

        public void SyncAnglesFromTransform()
        {
            Vector3 e = transform.eulerAngles;
            yaw = e.y;
            pitch = e.x > 180f ? e.x - 360f : e.x;
        }

        public void ReleasePointer()
        {
            if (Cursor.lockState != CursorLockMode.None) Cursor.lockState = CursorLockMode.None;
            Cursor.visible = true;
        }

        void Update()
        {
            Keyboard kb = Keyboard.current;
            Mouse mouse = Mouse.current;
            if (kb == null || mouse == null || Terrain == null || Terrain.Field == null) return;

            // Browsers require a user gesture to start pointer lock, so it is requested on click.
            if (!PointerLocked && mouse.leftButton.wasPressedThisFrame && !UiBlocker.IsPointerOverUi())
            {
                Cursor.lockState = CursorLockMode.Locked;
                Cursor.visible = false;
            }
            // The browser releases the lock itself on Esc; do it explicitly for the editor as well.
            if (PointerLocked && kb.escapeKey.wasPressedThisFrame) ReleasePointer();
            if (!PointerLocked && !Cursor.visible) Cursor.visible = true;

            if (PointerLocked)
            {
                Vector2 d = mouse.delta.ReadValue();
                yaw += d.x * LookDegreesPerPixel;
                pitch = Mathf.Clamp(pitch - d.y * LookDegreesPerPixel, -89f, 89f);
                transform.rotation = Quaternion.Euler(pitch, yaw, 0f);
            }

            Vector3 move = Vector3.zero;
            if (kb.wKey.isPressed || kb.upArrowKey.isPressed) move += transform.forward;
            if (kb.sKey.isPressed || kb.downArrowKey.isPressed) move -= transform.forward;
            if (kb.dKey.isPressed || kb.rightArrowKey.isPressed) move += transform.right;
            if (kb.aKey.isPressed || kb.leftArrowKey.isPressed) move -= transform.right;
            if (kb.eKey.isPressed) move += Vector3.up;
            if (kb.qKey.isPressed) move -= Vector3.up;

            if (move.sqrMagnitude > 0f)
            {
                float speed = BaseSpeed * (kb.leftShiftKey.isPressed || kb.rightShiftKey.isPressed ? 4f : 1f);
                // Clamp dt so a backgrounded tab does not teleport the camera on return.
                transform.position += move.normalized * (speed * Mathf.Min(Time.unscaledDeltaTime, 0.1f));
            }
            ClampToWorld();
        }

        public void ClampToWorld()
        {
            HeightField f = Terrain.Field;
            if (f == null) return;
            Vector3 p = transform.position;
            float marginX = f.SizeX * 0.25f, marginZ = f.SizeZ * 0.25f;
            p.x = Mathf.Clamp(p.x, -marginX, f.SizeX + marginX);
            p.z = Mathf.Clamp(p.z, -marginZ, f.SizeZ + marginZ);
            float ground = f.Sample(p.x, p.z) * Terrain.Exaggeration;
            float ceiling = f.MaxM * Terrain.Exaggeration + Mathf.Max(f.SizeX, f.SizeZ) * 1.5f;
            p.y = Mathf.Clamp(p.y, ground + MinClearance, ceiling);
            transform.position = p;
        }
    }
}
