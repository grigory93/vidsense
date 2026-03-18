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

  // Track the last element scrolled to so we only call scrollIntoView on
  // transition (inactive→active), never on every tick.
  let lastActiveCard   = null;
  let lastActiveBullet = null;
  /** Bumped on seek/pause to drop stale deferred scrolls; bumped when scheduling so newer work wins */
  let scrollGen = 0;

  function bumpScrollGen() {
    scrollGen += 1;
  }

  /**
   * After switching to Detailed tab, Alpine applies x-show on microtasks + layout on rAF.
   * Run fn after that so scrollIntoView sees real geometry.
   */
  function runAfterDetailedTabLayout(tabJustSwitched, fn) {
    const gen = ++scrollGen;
    const run = function () {
      if (gen !== scrollGen) return;
      fn();
    };
    if (tabJustSwitched) {
      queueMicrotask(function () {
        requestAnimationFrame(function () {
          requestAnimationFrame(run);
        });
      });
    } else {
      run();
    }
  }

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
      bumpScrollGen();
      // Reset trackers so the next play/seek fires scroll immediately.
      lastActiveCard   = null;
      lastActiveBullet = null;
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

    // --- Bullets first: they are the finest-grained active element ---
    // If a bullet is active, it handles scrolling; chapter-card scroll
    // is suppressed to prevent the two from fighting each other.
    let activeBulletFound = false;
    const bullets = document.querySelectorAll('.outline-point');

    bullets.forEach(function (bullet) {
      const start    = parseInt(bullet.dataset.start, 10);
      const end      = parseInt(bullet.dataset.end, 10);
      const isActive = currentTime >= start && currentTime < end;

      if (isActive) {
        activeBulletFound = true;
        bullet.classList.add('is-active-bullet');
        // Scroll only on transition (bullet changed), not on every tick.
        if (isPlaying && bullet !== lastActiveBullet) {
          lastActiveBullet = bullet;
          if (!isCardVisible(bullet)) {
            bullet.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        }
      } else {
        bullet.classList.remove('is-active-bullet');
      }
    });

    // --- Chapter cards ---
    const cards    = document.querySelectorAll('.chapter-card');
    const segments = document.querySelectorAll('.vs-timeline-segment');

    cards.forEach(function (card, idx) {
      const start    = parseInt(card.dataset.start, 10);
      const end      = parseInt(card.dataset.end, 10);
      const isActive = currentTime >= start && currentTime < end;

      if (isActive) {
        card.classList.add('is-active-chapter');
        // Only scroll to the chapter card when:
        //  - playback is active
        //  - no bullet is already scrolling (bullets are finer-grained)
        //  - this is a new active card (transition, not every tick)
        if (isPlaying && !activeBulletFound && card !== lastActiveCard) {
          var switched =
            typeof window.vsEnsureDetailedTab === 'function' &&
            window.vsEnsureDetailedTab();
          runAfterDetailedTabLayout(switched, function () {
            lastActiveCard = card;
            if (!isCardVisible(card)) {
              card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
          });
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
      const vh = window.innerHeight || document.documentElement.clientHeight;
      const overlap = Math.min(rect.bottom, vh) - Math.max(rect.top, 0);
      return overlap >= Math.max(40, Math.min(rect.height, vh) * 0.35);
    }
    const parentRect = scrollParent.getBoundingClientRect();
    const elRect     = el.getBoundingClientRect();
    const overlap = Math.min(elRect.bottom, parentRect.bottom) - Math.max(elRect.top, parentRect.top);
    return overlap >= Math.max(40, Math.min(elRect.height, parentRect.height) * 0.35);
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
      bumpScrollGen();
      // Reset trackers so the next poll tick scrolls to the new position.
      lastActiveCard   = null;
      lastActiveBullet = null;
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
