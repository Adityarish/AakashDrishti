using AakashDrishti.Viewer.Terrains;
using AakashDrishti.Viewer.Ui;
using UnityEngine;
using UnityEngine.InputSystem;

namespace AakashDrishti.Viewer.Cameras
{
    /// <summary>
    /// Orbit camera. Mouse: left-drag rotate, right/middle-drag (or Shift+left) pan, wheel zoom towards the cursor.
    /// Touch: one finger rotates, two fingers pinch-zoom and pan.
    ///
    /// Input only moves *goals* (yaw, pitch, distance, target); the camera eases towards them every frame, so
    /// rotating, panning and zooming glide instead of stepping, whatever the frame rate or wheel resolution.
    /// </summary>
    public sealed class OrbitCameraController : MonoBehaviour
    {
        const float Smoothing = 14f;          // higher = snappier (per second)
        const float ZoomPerNotch = 0.14f;     // fraction of the distance per wheel notch (~100 units)
        const float RotateDegreesPerPixel = 0.22f;

        public TerrainView Terrain;
        public Vector3 Target;
        public float Distance = 400f;
        public float MinDistance = 3f;
        public float MaxDistance = 5000f;

        float yaw = 30f, pitch = 45f;
        float goalYaw = 30f, goalPitch = 45f, goalDistance = 400f;
        Vector3 goalTarget;
        bool dragBlockedByUi;
        int lastTouchCount;
        float lastPinchDistance;

        void OnEnable() => Apply(0f);

        /// <summary>Adopts the current camera pose so switching from the fly camera does not jump.</summary>
        public void SyncFromTransform()
        {
            Vector3 e = transform.eulerAngles;
            yaw = goalYaw = e.y;
            pitch = goalPitch = Mathf.Clamp(e.x > 180f ? e.x - 360f : e.x, 5f, 89f);

            // Orbit around where the view ray meets the ground so the picture stays roughly the same.
            HeightField f = Terrain != null ? Terrain.Field : null;
            Vector3 pos = transform.position, fwd = transform.forward;
            if (f != null)
            {
                float maxT = Mathf.Max(f.SizeX, f.SizeZ) * 3f, step = maxT / 300f;
                for (float t = step; t <= maxT; t += step)
                {
                    Vector3 q = pos + fwd * t;
                    if (q.y <= f.Sample(q.x, q.z) * Terrain.Exaggeration)
                    {
                        Distance = Mathf.Clamp(t, MinDistance, MaxDistance);
                        break;
                    }
                }
            }
            goalDistance = Distance;
            Target = goalTarget = pos + fwd * Distance;
            Apply(0f);
        }

        public void SetPose(Vector3 target, float distance, float yawDeg, float pitchDeg)
        {
            Target = goalTarget = target;
            Distance = goalDistance = distance;
            yaw = goalYaw = yawDeg;
            pitch = goalPitch = pitchDeg;
            Apply(0f);
        }

        /// <summary>Glides the camera to look at a point from a given distance.</summary>
        public void FocusOn(Vector3 target, float distance)
        {
            goalTarget = target;
            goalDistance = Mathf.Clamp(distance, MinDistance, MaxDistance);
            goalPitch = Mathf.Max(goalPitch, 28f);
        }

        void Update()
        {
            if (Terrain == null || Terrain.Field == null) return;

            Touchscreen ts = Touchscreen.current;
            int touches = CountTouches(ts, out Vector2 a, out Vector2 b, out Vector2 da, out Vector2 db, out int idA);
            if (touches > 0) HandleTouch(touches, a, b, da, db, idA);
            else
            {
                lastTouchCount = 0;
                HandleMouse();
            }
            Apply(Time.unscaledDeltaTime);
        }

        void HandleMouse()
        {
            Mouse m = Mouse.current;
            if (m == null) return;

            bool pressed = m.leftButton.wasPressedThisFrame || m.rightButton.wasPressedThisFrame || m.middleButton.wasPressedThisFrame;
            if (pressed) dragBlockedByUi = UiBlocker.IsPointerOverUi();

            Vector2 d = m.delta.ReadValue();
            bool shift = Keyboard.current != null && Keyboard.current.shiftKey.isPressed;
            bool panning = m.rightButton.isPressed || m.middleButton.isPressed || (m.leftButton.isPressed && shift);

            if (!dragBlockedByUi)
            {
                if (panning) Pan(d);
                else if (m.leftButton.isPressed) Rotate(d, RotateDegreesPerPixel);
            }

            float scroll = m.scroll.ReadValue().y;
            if (Mathf.Abs(scroll) > 0.01f && !UiBlocker.IsPointerOverUi())
                ZoomAt(scroll, m.position.ReadValue());
        }

        /// <summary>Wheel zoom that keeps the point under the cursor roughly in place (like a map).</summary>
        void ZoomAt(float scroll, Vector2 screenPos)
        {
            // Browsers report ~100 per notch, some pads and platforms report 1 or 120; normalise to notches.
            float notches = Mathf.Clamp(scroll / (Mathf.Abs(scroll) > 20f ? 100f : 1f), -4f, 4f);
            float before = goalDistance;
            goalDistance = Mathf.Clamp(before * Mathf.Exp(-notches * ZoomPerNotch), MinDistance, MaxDistance);

            if (goalDistance < before)
            {
                Camera cam = GetComponent<Camera>();
                if (cam != null && Physics.Raycast(cam.ScreenPointToRay(screenPos), out RaycastHit hit, cam.farClipPlane))
                {
                    float k = 1f - goalDistance / before; // how much closer we got
                    Vector3 toward = hit.point - goalTarget;
                    toward.y = 0f;
                    goalTarget += toward * (k * 0.85f);
                }
            }
        }

        void HandleTouch(int touches, Vector2 a, Vector2 b, Vector2 da, Vector2 db, int idA)
        {
            if (touches != lastTouchCount)
            {
                // A finger went down or up: restart gestures and decide whether they began over UI.
                dragBlockedByUi = UiBlocker.IsPointerOverUi(idA);
                lastPinchDistance = touches > 1 ? Vector2.Distance(a, b) : 0f;
                lastTouchCount = touches;
                return;
            }
            if (dragBlockedByUi) return;

            if (touches == 1) Rotate(da, RotateDegreesPerPixel * 1.2f);
            else
            {
                float dist = Vector2.Distance(a, b);
                if (lastPinchDistance > 1f && dist > 1f)
                    goalDistance = Mathf.Clamp(goalDistance * (lastPinchDistance / dist), MinDistance, MaxDistance);
                lastPinchDistance = dist;
                Pan((da + db) * 0.5f);
            }
        }

        void Rotate(Vector2 delta, float degreesPerPixel)
        {
            goalYaw += delta.x * degreesPerPixel;
            goalPitch = Mathf.Clamp(goalPitch - delta.y * degreesPerPixel, 5f, 89f);
        }

        void Pan(Vector2 delta)
        {
            // "Grab the map" panning on the ground plane, scaled by distance so it feels constant on screen.
            Vector3 right = transform.right;
            Vector3 forward = transform.forward; forward.y = 0f;
            if (forward.sqrMagnitude < 1e-6f) forward = transform.up;
            forward.Normalize();
            float k = goalDistance * 0.0016f;
            goalTarget -= right * (delta.x * k) + forward * (delta.y * k);
        }

        /// <summary>Eases the current pose towards the goals (dt = 0 snaps) and places the camera.</summary>
        void Apply(float dt)
        {
            HeightField f = Terrain != null ? Terrain.Field : null;
            if (f != null)
            {
                goalTarget.x = Mathf.Clamp(goalTarget.x, 0f, f.SizeX);
                goalTarget.z = Mathf.Clamp(goalTarget.z, 0f, f.SizeZ);
            }

            float t = dt <= 0f ? 1f : 1f - Mathf.Exp(-Smoothing * dt);
            yaw = Mathf.Lerp(yaw, goalYaw, t);
            pitch = Mathf.Lerp(pitch, goalPitch, t);
            Distance = Mathf.Exp(Mathf.Lerp(Mathf.Log(Distance), Mathf.Log(goalDistance), t)); // ease in log space so zoom feels even
            Target = Vector3.Lerp(Target, goalTarget, t);

            if (f != null)
            {
                Target.x = Mathf.Clamp(Target.x, 0f, f.SizeX);
                Target.z = Mathf.Clamp(Target.z, 0f, f.SizeZ);
                Target.y = f.Sample(Target.x, Target.z) * Terrain.Exaggeration;
            }
            Quaternion rot = Quaternion.Euler(pitch, yaw, 0f);
            Vector3 pos = Target - rot * Vector3.forward * Distance;
            if (f != null)
                pos.y = Mathf.Max(pos.y, f.Sample(pos.x, pos.z) * Terrain.Exaggeration + 1.5f);
            transform.SetPositionAndRotation(pos, rot);
        }

        /// <summary>Allocation-free scan of active touches; reports up to two.</summary>
        static int CountTouches(Touchscreen ts, out Vector2 a, out Vector2 b, out Vector2 da, out Vector2 db, out int idA)
        {
            a = b = da = db = default;
            idA = -1;
            if (ts == null) return 0;
            int n = 0;
            var touches = ts.touches;
            for (int i = 0; i < touches.Count; i++)
            {
                var t = touches[i];
                if (!t.isInProgress) continue;
                if (n == 0) { a = t.position.ReadValue(); da = t.delta.ReadValue(); idA = t.touchId.ReadValue(); }
                else if (n == 1) { b = t.position.ReadValue(); db = t.delta.ReadValue(); }
                n++;
            }
            return Mathf.Min(n, 2);
        }
    }
}
