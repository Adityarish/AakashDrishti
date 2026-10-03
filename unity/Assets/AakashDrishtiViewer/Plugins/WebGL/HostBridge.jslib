mergeInto(LibraryManager.library, {
  // Forwards a JSON message to the page that embeds this build in an iframe.
  // The payloads carry no secrets, so the target origin is "*"; hosts must validate event.source themselves.
  AD_PostToParent: function (jsonPtr) {
    var json = UTF8ToString(jsonPtr);
    try {
      var msg = JSON.parse(json);
      if (window.parent && window.parent !== window) {
        window.parent.postMessage(msg, "*");
      }
    } catch (e) {
      console.warn("[AakashDrishtiViewer] postMessage failed", e);
    }
  }
});
