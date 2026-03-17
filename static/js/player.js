/**
 * VidSense YouTube Player
 *
 * Manages the YouTube IFrame API player:
 *  - Initialises the player once the API is ready
 *  - Exposes seekVideo(seconds) for timestamp clicks
 *  - Polls getCurrentTime() to highlight the active chapter card and timeline segment
 */

(function () {
  'use strict';

  let player = null;
  let highlightInterval = null;
  let isPlaying = false;

  // Called by the YouTube IFrame API once it loads
  window.onYouTubeIframeAPIReady = function () {
    const container = document.getElementById('yt-player');
    if (!container) return;

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
    // Don't start the loop until playback begins — avoids auto-scrolling
    // the page before the user has interacted with the player.
  }

  function onPlayerStateChange(event) {
    isPlaying = event.data === YT.PlayerState.PLAYING;
    if (isPlaying) {
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

    const cards    = document.querySelectorAll('.chapter-card');
    const segments = document.querySelectorAll('.vs-timeline-segment');

    cards.forEach(function (card, idx) {
      const start   = parseInt(card.dataset.start, 10);
      const end     = parseInt(card.dataset.end, 10);
      const isActive = currentTime >= start && currentTime < end;

      if (isActive) {
        card.classList.add('is-active-chapter');
        // Auto-scroll only while playing and card is fully out of view
        if (isPlaying && !isCardVisible(card)) {
          card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        if (segments[idx]) segments[idx].classList.add('is-active-segment');
      } else {
        card.classList.remove('is-active-chapter');
        if (segments[idx]) segments[idx].classList.remove('is-active-segment');
      }
    });
  }

  /**
   * Returns true when the card is fully visible within its nearest
   * scrollable ancestor — the content panel in the two-panel layout.
   */
  function isCardVisible(el) {
    const scrollParent = document.getElementById('vs-content-panel') || getScrollParent(el);
    if (!scrollParent) {
      const rect = el.getBoundingClientRect();
      return rect.top >= 0 && rect.bottom <= (window.innerHeight || document.documentElement.clientHeight);
    }
    const parentRect = scrollParent.getBoundingClientRect();
    const elRect     = el.getBoundingClientRect();
    return elRect.top >= parentRect.top && elRect.bottom <= parentRect.bottom;
  }

  function getScrollParent(el) {
    if (!el || el === document.body) return null;
    const style = window.getComputedStyle(el);
    const oy    = style.overflowY;
    if (oy === 'auto' || oy === 'scroll') return el;
    return getScrollParent(el.parentElement);
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  /** Seek the player to a given timestamp in seconds. */
  window.seekVideo = function (seconds) {
    if (player && typeof player.seekTo === 'function') {
      player.seekTo(seconds, true);
      player.playVideo();
    }
  };

  /** Expose player instance for app.js keyboard shortcut handling. */
  window.__vsPlayer = function () { return player; };

  // ------------------------------------------------------------------
  // Bootstrap: read youtubeId from data attribute or Alpine component
  // ------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', function () {
    const container = document.getElementById('yt-player');
    if (container && container.dataset.youtubeId) {
      window.__vsYoutubeId = container.dataset.youtubeId;
    }
  });

})();
