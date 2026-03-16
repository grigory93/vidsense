/**
 * VidSense YouTube Player
 *
 * Manages the YouTube IFrame API player:
 *  - Initialises the player once the API is ready
 *  - Exposes seekVideo(seconds) for timestamp clicks
 *  - Polls getCurrentTime() to highlight the active chapter card
 */

(function () {
  'use strict';

  let player = null;
  let highlightInterval = null;

  // Called by the YouTube IFrame API once it loads
  window.onYouTubeIframeAPIReady = function () {
    const container = document.getElementById('yt-player');
    if (!container) return;

    // Read video ID from nearest data attribute (set by video.html via Alpine scope)
    const youtubeId = window.__vsYoutubeId;
    if (!youtubeId) return;

    player = new YT.Player('yt-player', {
      videoId: youtubeId,
      playerVars: {
        autoplay: 0,
        modestbranding: 1,
        rel: 0,
        enablejsapi: 1,
        origin: window.location.origin,
      },
      events: {
        onReady: onPlayerReady,
        onStateChange: onPlayerStateChange,
      },
    });
  };

  function onPlayerReady() {
    // Start the chapter-highlight loop
    startHighlightLoop();
  }

  function onPlayerStateChange(event) {
    // YT.PlayerState.PLAYING = 1, PAUSED = 2, ENDED = 0
    if (event.data === YT.PlayerState.PLAYING) {
      startHighlightLoop();
    } else {
      stopHighlightLoop();
    }
  }

  // ------------------------------------------------------------------
  // Chapter active-state highlighting
  // ------------------------------------------------------------------

  function startHighlightLoop() {
    if (highlightInterval) return;
    highlightInterval = setInterval(updateActiveChapter, 1000);
  }

  function stopHighlightLoop() {
    if (highlightInterval) {
      clearInterval(highlightInterval);
      highlightInterval = null;
    }
  }

  function updateActiveChapter() {
    if (!player || typeof player.getCurrentTime !== 'function') return;
    const currentTime = player.getCurrentTime();
    const cards = document.querySelectorAll('.chapter-card');

    cards.forEach(function (card) {
      const start = parseInt(card.dataset.start, 10);
      const end = parseInt(card.dataset.end, 10);
      const isActive = currentTime >= start && currentTime < end;

      if (isActive) {
        card.classList.add('ring-2', 'ring-brand-400', 'border-brand-400', 'bg-brand-50/40');
        // Scroll into view if not visible
        if (!isInViewport(card)) {
          card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      } else {
        card.classList.remove('ring-2', 'ring-brand-400', 'border-brand-400', 'bg-brand-50/40');
      }
    });
  }

  function isInViewport(el) {
    const rect = el.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= (window.innerHeight || document.documentElement.clientHeight);
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  /**
   * Seek the player to a given timestamp in seconds.
   * Called by chapter timestamp buttons.
   */
  window.seekVideo = function (seconds) {
    if (player && typeof player.seekTo === 'function') {
      player.seekTo(seconds, true);
      player.playVideo();
    }
  };

  // Expose player for debugging
  window.__vsPlayer = function () { return player; };

  // ------------------------------------------------------------------
  // Bootstrap: read youtubeId from Alpine data on the page root
  // ------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', function () {
    // The Alpine component on video.html exposes youtubeId via a global
    // we set it when Alpine initialises the videoPage() component.
    // Fallback: read from the data attribute on the player container.
    const container = document.getElementById('yt-player');
    if (container && container.dataset.youtubeId) {
      window.__vsYoutubeId = container.dataset.youtubeId;
    }
  });
})();
