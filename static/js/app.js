/**
 * VidSense — general UI helpers
 */
(function () {
  'use strict';

  // Ensure Alpine's x-cloak elements start hidden
  document.addEventListener('alpine:init', function () {
    // Register a global magic for formatted timestamps
    Alpine.magic('mmss', function () {
      return function (seconds) {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        const h = Math.floor(m / 60);
        if (h > 0) {
          return `${h}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }
        return `${m}:${String(s).padStart(2, '0')}`;
      };
    });
  });

  // HTMX event: when the status partial swaps in, expose youtubeId to player
  document.addEventListener('htmx:afterSwap', function (evt) {
    if (evt.detail.target && evt.detail.target.id === 'content-area') {
      // If processing is complete, stop the polling trigger
      if (window.__vsProcessingComplete) {
        const area = document.getElementById('content-area');
        if (area) {
          area.removeAttribute('hx-trigger');
          htmx.process(area);
        }
      }
    }
  });

  // Expose youtubeId for the player from the Alpine component
  document.addEventListener('alpine:initialized', function () {
    const root = document.querySelector('[x-data*="videoPage"]');
    if (root && root._x_dataStack) {
      const data = root._x_dataStack[0];
      if (data && data.youtubeId) {
        window.__vsYoutubeId = data.youtubeId;
      }
    }
  });
})();
