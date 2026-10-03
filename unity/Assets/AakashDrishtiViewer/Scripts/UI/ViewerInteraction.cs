using AakashDrishti.Viewer.Buildings;
using AakashDrishti.Viewer.Cameras;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.InputSystem;

namespace AakashDrishti.Viewer.Ui
{
    /// <summary>Height readout under the cursor and click-to-select for buildings.</summary>
    public sealed class ViewerInteraction : MonoBehaviour
    {
        const float ClickDragTolerancePixels = 8f;

        public Camera Cam;
        public TerrainView Terrain;
        public BuildingLayer Buildings;
        public CameraRig Rig;
        public ViewerUI Ui;
        /// <summary>While a scenario is waiting for a point, the next click on the terrain goes here instead of selecting a building.</summary>
        public AakashDrishti.Viewer.Scenarios.ScenarioController Scenarios;

        bool isMetric;
        int lastTenths = int.MinValue;
        bool tracking, pressBlocked;
        float dragAccum;

        public void SetMetric(bool metric)
        {
            isMetric = metric;
            lastTenths = int.MinValue;
        }

        void Update()
        {
            if (Terrain == null || Terrain.Field == null || Cam == null) return;
            UpdateReadout();
            UpdateClick();
        }

        /// <summary>Screen centre while the pointer is locked (fly camera); otherwise the mouse or active touch.</summary>
        bool TryGetPointer(out Vector2 pos)
        {
            if (Rig.PointerLocked) { pos = new Vector2(Screen.width * 0.5f, Screen.height * 0.5f); return true; }
            Touchscreen ts = Touchscreen.current;
            if (ts != null && ts.primaryTouch.press.isPressed) { pos = ts.primaryTouch.position.ReadValue(); return true; }
            Mouse m = Mouse.current;
            if (m != null) { pos = m.position.ReadValue(); return true; }
            pos = default;
            return false;
        }

        void UpdateReadout()
        {
            int tenths = int.MinValue;
            if (TryGetPointer(out Vector2 pos) && !(Mouse.current != null && !Rig.PointerLocked && UiBlocker.IsPointerOverUi())
                && Physics.Raycast(Cam.ScreenPointToRay(pos), out RaycastHit hit, Cam.farClipPlane))
            {
                Vector3 local = Terrain.WorldRoot.InverseTransformPoint(hit.point);
                float h = Terrain.Field.Sample(local.x, local.z);
                tenths = Mathf.RoundToInt(h * 10f);
                if (tenths != lastTenths)
                    Ui.SetHeightReadout("Height: " + h.ToString("0.0") + " m" + (isMetric ? "" : " (relative)"));
            }
            else if (lastTenths != int.MinValue)
            {
                Ui.SetHeightReadout("Height: -");
            }
            lastTenths = tenths;
        }

        void UpdateClick()
        {
            bool pressed, released;
            Vector2 pos, delta;
            int id = -1;

            Touchscreen ts = Touchscreen.current;
            Mouse m = Mouse.current;
            bool touch = ts != null && (ts.primaryTouch.press.isPressed || ts.primaryTouch.press.wasReleasedThisFrame);
            if (touch)
            {
                var t = ts.primaryTouch;
                pressed = t.press.wasPressedThisFrame;
                released = t.press.wasReleasedThisFrame;
                pos = t.position.ReadValue();
                delta = t.delta.ReadValue();
                id = t.touchId.ReadValue();
            }
            else if (m != null)
            {
                pressed = m.leftButton.wasPressedThisFrame;
                released = m.leftButton.wasReleasedThisFrame;
                pos = m.position.ReadValue();
                delta = m.delta.ReadValue();
            }
            else return;

            if (pressed)
            {
                // The first click in fly mode only captures the mouse; it should not also select.
                pressBlocked = UiBlocker.IsPointerOverUi(id) || (!touch && Rig.Mode == CameraMode.Fly && !Rig.PointerLocked);
                dragAccum = 0f;
                tracking = true;
            }
            if (tracking) dragAccum += delta.magnitude;
            if (released && tracking)
            {
                tracking = false;
                if (!pressBlocked && dragAccum < ClickDragTolerancePixels)
                {
                    Vector2 p = Rig.PointerLocked ? new Vector2(Screen.width * 0.5f, Screen.height * 0.5f) : pos;
                    if (Scenarios != null && Scenarios.Picking)
                    {
                        if (Physics.Raycast(Cam.ScreenPointToRay(p), out RaycastHit ph, Cam.farClipPlane)) Scenarios.TryPick(ph.point);
                        return;
                    }
                    Buildings.PickAt(Cam.ScreenPointToRay(p), Cam.farClipPlane);
                }
            }
        }
    }
}
