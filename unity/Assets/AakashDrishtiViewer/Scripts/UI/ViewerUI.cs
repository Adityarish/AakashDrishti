using System;
using AakashDrishti.Viewer.Cameras;
using AakashDrishti.Viewer.Loading;
using AakashDrishti.Viewer.Terrains;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.UI;
using UnityEngine.UI;

namespace AakashDrishti.Viewer.Ui
{
    /// <summary>uGUI overlay built entirely from code, so the scene only needs one GameObject.</summary>
    public sealed class ViewerUI : MonoBehaviour
    {
        static readonly Color PanelColor = new Color(0.07f, 0.09f, 0.12f, 0.82f);
        static readonly Color ButtonColor = new Color(0.22f, 0.27f, 0.34f, 1f);
        static readonly Color AccentColor = new Color(0.16f, 0.52f, 0.90f, 1f);
        static readonly Color DisabledColor = new Color(0.14f, 0.16f, 0.2f, 1f);
        static readonly Color TextColor = new Color(0.93f, 0.95f, 0.98f, 1f);
        static readonly Color MutedText = new Color(0.62f, 0.68f, 0.76f, 1f);

        public event Action<OverlayMode> OverlayChanged;
        public event Action<bool> ZonesToggled;
        public event Action<float> ExaggerationChanged;
        public event Action CameraToggleClicked;
        public event Action RetryClicked;

        public CameraRig Rig;
        bool showFps;
        public bool ShowFps
        {
            get => showFps;
            set { showFps = value; if (fpsText != null) fpsText.gameObject.SetActive(value); }
        }

        Font font;
        Canvas canvas;

        // controls panel
        Image[] overlayButtons;
        Button zonesButton, zonesToggle, cameraButton;
        Text zonesToggleLabel, exaggerationLabel, cameraLabel;
        Slider exaggerationSlider;
        // overlays
        GameObject badge, loadingPanel, errorPanel, selectionCard;
        Text readoutText, hintText, fpsText, selectionText, loadingStatus, errorText;
        RectTransform loadingFill;

        OverlayMode mode = OverlayMode.Rgb;
        // Off by default: even correctly-sized zones tint the base imagery, so the terrain should be
        // recognizable on first load. The zones toggle button still switches it on.
        bool zonesOn = false, hasZones, sceneReady;
        string lastHint;

        // FPS
        float fpsTime;
        int fpsFrames;

        void Awake()
        {
            font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            EnsureEventSystem();
            BuildCanvas();
        }

        static void EnsureEventSystem()
        {
            if (FindAnyObjectByType<EventSystem>() != null) return;
            var go = new GameObject("EventSystem");
            go.AddComponent<EventSystem>();
            go.AddComponent<InputSystemUIInputModule>().AssignDefaultActions();
        }

        // ------------------------------------------------------------------ public API

        public void ShowLoading(string status, float progress)
        {
            errorPanel.SetActive(false);
            loadingPanel.SetActive(true);
            loadingStatus.text = status;
            loadingFill.anchorMax = new Vector2(Mathf.Clamp01(progress), 1f);
        }

        public void HideLoading() => loadingPanel.SetActive(false);

        public void ShowError(string message)
        {
            loadingPanel.SetActive(false);
            errorText.text = message;
            errorPanel.SetActive(true);
        }

        public void ConfigureForScene(bool isMetric, bool zonesAvailable, bool touchOnly)
        {
            sceneReady = true;
            hasZones = zonesAvailable;
            badge.SetActive(!isMetric);
            cameraButton.gameObject.SetActive(!touchOnly);
            if (!zonesAvailable && mode == OverlayMode.Zones) SetOverlay(OverlayMode.Rgb);
            RefreshControls();
            SetHeightReadout("Height: -");
        }

        public void SetHeightReadout(string text) => readoutText.text = text;

        public void SetSelection(BuildingData b, bool isMetric)
        {
            selectionCard.SetActive(b != null);
            if (b != null)
                selectionText.text = $"Building #{b.Id}\nHeight: {b.HeightM:0.#} m" + (isMetric ? "" : " (relative)");
        }

        public void ClearSelection() => selectionCard.SetActive(false);

        // ------------------------------------------------------------------ per-frame

        void Update()
        {
            // Keep keyboard focus off the widgets: with a slider selected, the arrow keys would change it.
            var es = EventSystem.current;
            if (es != null && es.currentSelectedGameObject != null && (Mouse.current == null || !Mouse.current.leftButton.isPressed))
                es.SetSelectedGameObject(null);

            UpdateHint();

            if (ShowFps)
            {
                fpsFrames++;
                fpsTime += Time.unscaledDeltaTime;
                if (fpsTime >= 0.5f)
                {
                    fpsText.text = "FPS " + Mathf.RoundToInt(fpsFrames / fpsTime);
                    fpsFrames = 0; fpsTime = 0f;
                }
            }
        }

        void UpdateHint()
        {
            string hint = "";
            if (sceneReady && Rig != null)
            {
                if (Rig.TouchOnly)
                    hint = "Drag: rotate  |  Pinch: zoom  |  Two fingers: pan  |  Tap a building for details";
                else if (Rig.Mode == CameraMode.Orbit)
                    hint = "Drag: rotate  |  Right-drag or Shift+drag: pan  |  Wheel: zoom  |  C: first-person camera";
                else if (Rig.PointerLocked)
                    hint = "Esc: release mouse  |  WASD: move  |  Q/E: down/up  |  Shift: faster  |  Click a building for details";
                else
                    hint = "Click the view to capture the mouse  |  WASD: move  |  Q/E: down/up  |  Shift: faster  |  C: orbit camera";
            }
            if (hint != lastHint) { lastHint = hint; hintText.text = hint; }
        }

        // ------------------------------------------------------------------ control handlers

        void SetOverlay(OverlayMode m, bool silent = false)
        {
            mode = m;
            RefreshControls();
            if (!silent) OverlayChanged?.Invoke(m);
        }

        void RefreshControls()
        {
            for (int i = 0; i < overlayButtons.Length; i++)
                overlayButtons[i].color = i == (int)mode ? AccentColor : ButtonColor;

            zonesButton.interactable = hasZones;
            if (!hasZones) overlayButtons[(int)OverlayMode.Zones].color = DisabledColor;

            bool zonesForced = mode == OverlayMode.Zones;
            zonesToggle.interactable = hasZones && !zonesForced;
            zonesToggleLabel.text = "Zones overlay: " + (hasZones ? (zonesOn || zonesForced ? "on" : "off") : "none in this job");
            zonesToggle.GetComponent<Image>().color = !hasZones || zonesForced ? DisabledColor : (zonesOn ? AccentColor : ButtonColor);

            if (Rig != null) cameraLabel.text = Rig.Mode == CameraMode.Orbit ? "Camera: Orbit  (C to switch)" : "Camera: First-person  (C to switch)";
        }

        public void RefreshCameraLabel() => RefreshControls();

        // ------------------------------------------------------------------ construction

        void BuildCanvas()
        {
            var cgo = new GameObject("Canvas");
            cgo.transform.SetParent(transform, false);
            canvas = cgo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            var scaler = cgo.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1280f, 720f);
            scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight = 0.5f;
            cgo.AddComponent<GraphicRaycaster>();
            Transform root = cgo.transform;

            BuildControlsPanel(root);
            BuildReadout(root);
            BuildBadgeAndFps(root);
            BuildHint(root);
            BuildSelectionCard(root);
            BuildLoading(root);
            BuildError(root);

            selectionCard.SetActive(false);
            badge.SetActive(false);
            errorPanel.SetActive(false);
            fpsText.gameObject.SetActive(ShowFps);
        }

        void BuildControlsPanel(Transform root)
        {
            RectTransform panel = Corner(NewImage("Controls", root, PanelColor).rectTransform, new Vector2(0, 1), new Vector2(12, -12), new Vector2(292, 206));

            Label(panel, "OVERLAY", 12, 10, 268, 18, MutedText, 12);
            string[] names = { "RGB", "Elevation", "Zones" };
            overlayButtons = new Image[3];
            for (int i = 0; i < 3; i++)
            {
                int index = i;
                Button b = NewButton(panel, names[i], 12 + i * 91, 32, 86, 30, () => SetOverlay((OverlayMode)index));
                overlayButtons[i] = b.GetComponent<Image>();
                if (i == (int)OverlayMode.Zones) zonesButton = b;
            }

            zonesToggle = NewButton(panel, "Zones overlay: on", 12, 72, 268, 28, () =>
            {
                zonesOn = !zonesOn;
                RefreshControls();
                ZonesToggled?.Invoke(zonesOn);
            });
            zonesToggleLabel = zonesToggle.GetComponentInChildren<Text>();

            exaggerationLabel = Label(panel, "Vertical exaggeration: 1.0x", 12, 110, 268, 18, TextColor, 13);
            exaggerationSlider = NewSlider(panel, 12, 132, 268, 20, 1f, 5f, 1f, v =>
            {
                exaggerationLabel.text = $"Vertical exaggeration: {v:0.0}x";
                ExaggerationChanged?.Invoke(v);
            });

            cameraButton = NewButton(panel, "Camera", 12, 164, 268, 30, () =>
            {
                CameraToggleClicked?.Invoke();
                RefreshControls();
            });
            cameraLabel = cameraButton.GetComponentInChildren<Text>();
            overlayButtons[0].color = AccentColor;
        }

        void BuildReadout(Transform root)
        {
            RectTransform p = Corner(NewImage("Readout", root, PanelColor).rectTransform, new Vector2(0, 0), new Vector2(12, 48), new Vector2(300, 34)); // sits above the hint strip
            readoutText = Label(p, "Height: -", 12, 7, 276, 22, TextColor, 15);
        }

        void BuildBadgeAndFps(Transform root)
        {
            Image b = NewImage("RelativeBadge", root, new Color(0.85f, 0.45f, 0.08f, 0.95f));
            Corner(b.rectTransform, new Vector2(1, 1), new Vector2(-12, -12), new Vector2(190, 28));
            Label(b.rectTransform, "RELATIVE SCALE", 0, 4, 190, 20, Color.white, 13).alignment = TextAnchor.MiddleCenter;
            badge = b.gameObject;

            fpsText = Label(root, "FPS", 0, 0, 120, 22, Color.green, 14);
            Corner(fpsText.rectTransform, new Vector2(1, 1), new Vector2(-12, -46), new Vector2(120, 22));
            fpsText.alignment = TextAnchor.MiddleRight;
        }

        void BuildHint(Transform root)
        {
            RectTransform strip = NewImage("HintStrip", root, new Color(0f, 0f, 0f, 0.45f)).rectTransform;
            strip.anchorMin = new Vector2(0.5f, 0f);
            strip.anchorMax = new Vector2(0.5f, 0f);
            strip.pivot = new Vector2(0.5f, 0f);
            strip.anchoredPosition = new Vector2(0, 12);
            strip.sizeDelta = new Vector2(760, 26);
            hintText = Label(strip, "", 0, 3, 760, 20, TextColor, 13);
            hintText.alignment = TextAnchor.MiddleCenter;
            strip.GetComponent<Image>().raycastTarget = false;
        }

        void BuildSelectionCard(Transform root)
        {
            Image card = NewImage("SelectionCard", root, PanelColor);
            Corner(card.rectTransform, new Vector2(1, 0), new Vector2(-12, 12), new Vector2(220, 62));
            selectionText = Label(card.rectTransform, "", 12, 8, 196, 48, TextColor, 15);
            selectionCard = card.gameObject;
        }

        void BuildLoading(Transform root)
        {
            Image dim = NewImage("Loading", root, new Color(0.04f, 0.05f, 0.08f, 0.94f));
            Stretch(dim.rectTransform);
            Text title = Label(dim.rectTransform, "Loading terrain", 0, 0, 480, 30, TextColor, 22);
            Center(title.rectTransform, new Vector2(0, 40), new Vector2(480, 30));
            title.alignment = TextAnchor.MiddleCenter;

            loadingStatus = Label(dim.rectTransform, "", 0, 0, 480, 22, MutedText, 14);
            Center(loadingStatus.rectTransform, new Vector2(0, 6), new Vector2(480, 22));
            loadingStatus.alignment = TextAnchor.MiddleCenter;

            Image barBg = NewImage("Bar", dim.rectTransform, new Color(1f, 1f, 1f, 0.12f));
            Center(barBg.rectTransform, new Vector2(0, -26), new Vector2(420, 12));
            Image fill = NewImage("Fill", barBg.rectTransform, AccentColor);
            loadingFill = fill.rectTransform;
            loadingFill.anchorMin = Vector2.zero;
            loadingFill.anchorMax = new Vector2(0f, 1f);
            loadingFill.offsetMin = loadingFill.offsetMax = Vector2.zero;
            loadingPanel = dim.gameObject;
        }

        void BuildError(Transform root)
        {
            Image dim = NewImage("Error", root, new Color(0.04f, 0.05f, 0.08f, 0.94f));
            Stretch(dim.rectTransform);
            Image card = NewImage("Card", dim.rectTransform, new Color(0.13f, 0.09f, 0.1f, 1f));
            Center(card.rectTransform, Vector2.zero, new Vector2(560, 250));

            Text title = Label(card.rectTransform, "Could not load the scene", 20, 16, 520, 28, new Color(1f, 0.45f, 0.4f), 20);
            title.fontStyle = FontStyle.Bold;
            errorText = Label(card.rectTransform, "", 20, 54, 520, 130, TextColor, 15);
            errorText.horizontalOverflow = HorizontalWrapMode.Wrap;
            errorText.verticalOverflow = VerticalWrapMode.Truncate;
            NewButton(card.rectTransform, "Retry", 20, 196, 120, 36, () => RetryClicked?.Invoke());
            errorPanel = dim.gameObject;
        }

        // ------------------------------------------------------------------ widget helpers

        Image NewImage(string name, Transform parent, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(CanvasRenderer), typeof(Image));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.color = color;
            return img;
        }

        Text Label(Transform parent, string text, float x, float y, float w, float h, Color color, int size)
        {
            var go = new GameObject("Text", typeof(RectTransform), typeof(CanvasRenderer), typeof(Text));
            go.transform.SetParent(parent, false);
            var rt = (RectTransform)go.transform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0, 1);
            rt.anchoredPosition = new Vector2(x, -y);
            rt.sizeDelta = new Vector2(w, h);
            var t = go.GetComponent<Text>();
            t.font = font;
            t.text = text;
            t.fontSize = size;
            t.color = color;
            t.alignment = TextAnchor.UpperLeft;
            t.horizontalOverflow = HorizontalWrapMode.Overflow;
            t.verticalOverflow = VerticalWrapMode.Overflow;
            t.raycastTarget = false;
            return t;
        }

        Button NewButton(Transform parent, string label, float x, float y, float w, float h, Action onClick)
        {
            Image img = NewImage(label, parent, ButtonColor);
            var rt = img.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0, 1);
            rt.anchoredPosition = new Vector2(x, -y);
            rt.sizeDelta = new Vector2(w, h);

            var b = img.gameObject.AddComponent<Button>();
            b.targetGraphic = img;
            b.navigation = new Navigation { mode = Navigation.Mode.None };
            var colors = b.colors;
            colors.highlightedColor = new Color(1.15f, 1.15f, 1.15f, 1f);
            colors.pressedColor = new Color(0.8f, 0.8f, 0.8f, 1f);
            colors.disabledColor = new Color(0.7f, 0.7f, 0.7f, 1f);
            b.colors = colors;
            b.onClick.AddListener(() => onClick());

            Text t = Label(rt, label, 0, 0, w, h, TextColor, 14);
            t.rectTransform.anchorMin = Vector2.zero;
            t.rectTransform.anchorMax = Vector2.one;
            t.rectTransform.offsetMin = t.rectTransform.offsetMax = Vector2.zero;
            t.alignment = TextAnchor.MiddleCenter;
            return b;
        }

        Slider NewSlider(Transform parent, float x, float y, float w, float h, float min, float max, float value, Action<float> onChanged)
        {
            var go = new GameObject("Slider", typeof(RectTransform));
            go.transform.SetParent(parent, false);
            var rt = (RectTransform)go.transform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0, 1);
            rt.anchoredPosition = new Vector2(x, -y);
            rt.sizeDelta = new Vector2(w, h);

            Image bg = NewImage("Background", rt, new Color(1f, 1f, 1f, 0.18f));
            bg.rectTransform.anchorMin = new Vector2(0, 0.25f);
            bg.rectTransform.anchorMax = new Vector2(1, 0.75f);
            bg.rectTransform.offsetMin = bg.rectTransform.offsetMax = Vector2.zero;

            var fillArea = new GameObject("Fill Area", typeof(RectTransform)).GetComponent<RectTransform>();
            fillArea.SetParent(rt, false);
            fillArea.anchorMin = new Vector2(0, 0.25f);
            fillArea.anchorMax = new Vector2(1, 0.75f);
            fillArea.anchoredPosition = new Vector2(-5, 0);
            fillArea.sizeDelta = new Vector2(-20, 0);
            Image fill = NewImage("Fill", fillArea, AccentColor);
            fill.rectTransform.sizeDelta = new Vector2(10, 0);

            var handleArea = new GameObject("Handle Slide Area", typeof(RectTransform)).GetComponent<RectTransform>();
            handleArea.SetParent(rt, false);
            handleArea.anchorMin = Vector2.zero;
            handleArea.anchorMax = Vector2.one;
            handleArea.anchoredPosition = Vector2.zero;
            handleArea.sizeDelta = new Vector2(-20, 0);
            Image handle = NewImage("Handle", handleArea, Color.white);
            handle.rectTransform.sizeDelta = new Vector2(20, 0);

            var s = go.AddComponent<Slider>();
            s.fillRect = fill.rectTransform;
            s.handleRect = handle.rectTransform;
            s.targetGraphic = handle;
            s.direction = Slider.Direction.LeftToRight;
            s.navigation = new Navigation { mode = Navigation.Mode.None };
            s.minValue = min;
            s.maxValue = max;
            s.SetValueWithoutNotify(value);
            s.onValueChanged.AddListener(v => onChanged(v));
            return s;
        }

        static RectTransform Corner(RectTransform rt, Vector2 corner, Vector2 offset, Vector2 size)
        {
            rt.anchorMin = rt.anchorMax = rt.pivot = corner;
            rt.anchoredPosition = offset;
            rt.sizeDelta = size;
            return rt;
        }

        static void Center(RectTransform rt, Vector2 offset, Vector2 size)
        {
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
            rt.anchoredPosition = offset;
            rt.sizeDelta = size;
        }

        static void Stretch(RectTransform rt)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = rt.offsetMax = Vector2.zero;
        }
    }
}
