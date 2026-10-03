using UnityEngine.EventSystems;

namespace AakashDrishti.Viewer.Ui
{
    public static class UiBlocker
    {
        /// <summary>True when the pointer (mouse: -1, or a touch finger id) is over a uGUI element.</summary>
        public static bool IsPointerOverUi(int pointerId = -1) =>
            EventSystem.current != null && EventSystem.current.IsPointerOverGameObject(pointerId);
    }
}
