/**
 * VidSense — shell-level UI helpers
 * Player-specific logic lives in player.js
 */
(function () {
  'use strict';

  // ----------------------------------------------------------------
  // Toast container (created once, reused)
  // ----------------------------------------------------------------

  function getToastContainer() {
    let c = document.getElementById('vs-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'vs-toast-container';
      document.body.appendChild(c);
    }
    return c;
  }

  // ----------------------------------------------------------------
  // Toast notification system
  // ----------------------------------------------------------------

  const TOAST_ICONS = {
    success: '<svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>',
    error:   '<svg class="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>',
    info:    '<svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  };

  window.vsShowToast = function (message, type) {
    type = type || 'success';
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = 'vs-toast vs-toast-' + type;
    toast.innerHTML = (TOAST_ICONS[type] || '') + '<span>' + message + '</span>';
    container.appendChild(toast);

    setTimeout(function () {
      toast.style.animation = 'toastFadeOut 0.25s ease forwards';
      setTimeout(function () { toast.remove(); }, 260);
    }, 2800);
  };

  // ----------------------------------------------------------------
  // Copy to clipboard
  // ----------------------------------------------------------------

  window.vsCopyToClipboard = function (text, label) {
    navigator.clipboard.writeText(text).then(function () {
      window.vsShowToast(label ? label + ' copied' : 'Copied to clipboard', 'success');
    }).catch(function () {
      window.vsShowToast('Copy failed — please copy manually', 'error');
    });
  };

  // ----------------------------------------------------------------
  // Alpine.js helpers
  // ----------------------------------------------------------------

  document.addEventListener('alpine:init', function () {
    Alpine.magic('mmss', function () {
      return function (seconds) {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        const h = Math.floor(m / 60);
        if (h > 0) {
          return h + ':' + String(m % 60).padStart(2, '0') + ':' + String(s).padStart(2, '0');
        }
        return m + ':' + String(s).padStart(2, '0');
      };
    });
  });

  // ----------------------------------------------------------------
  // HTMX: stop polling, fade in results, notify Alpine
  // ----------------------------------------------------------------

  document.addEventListener('htmx:afterSwap', function (evt) {
    if (evt.detail.target && evt.detail.target.id === 'content-area') {
      if (window.__vsProcessingComplete) {
        const area = document.getElementById('content-area');
        if (area) {
          area.removeAttribute('hx-trigger');
          htmx.process(area);
          area.classList.add('vs-fade-in');
        }
        // Notify Alpine videoPage component that results loaded
        const root = document.querySelector('[x-data*="videoPage"]');
        if (root && root._x_dataStack) {
          const data = root._x_dataStack[0];
          if (data && typeof data.onResultsLoaded === 'function') {
            data.onResultsLoaded();
          }
        }
      }
    }
  });

  // ----------------------------------------------------------------
  // Alpine: expose youtubeId for player.js bootstrap
  // ----------------------------------------------------------------

  document.addEventListener('alpine:initialized', function () {
    const root = document.querySelector('[x-data*="videoPage"]');
    if (root && root._x_dataStack) {
      const data = root._x_dataStack[0];
      if (data && data.youtubeId) {
        window.__vsYoutubeId = data.youtubeId;
      }
    }
  });

  // ----------------------------------------------------------------
  // Keyboard shortcuts (read screen only, disabled while typing)
  // ----------------------------------------------------------------

  document.addEventListener('keydown', function (e) {
    // Only on the video/read page
    if (!document.querySelector('[x-data*="videoPage"]')) return;

    // Disabled while typing in inputs, textareas, or contentEditable
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;

    // Don't intercept browser/OS shortcuts
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    switch (e.key) {
      case 'j': {
        e.preventDefault();
        navigateChapter(1);
        break;
      }
      case 'k': {
        e.preventDefault();
        navigateChapter(-1);
        break;
      }
      case 'p': {
        e.preventDefault();
        togglePlayPause();
        break;
      }
      case 'Escape': {
        window.location.href = '/';
        break;
      }
    }
  });

  function navigateChapter(direction) {
    const cards = Array.from(document.querySelectorAll('.chapter-card'));
    if (!cards.length) return;

    // Ensure the Detailed Outline tab is active so chapter cards are visible
    ensureDetailedTabActive();

    const activeIdx = cards.findIndex(function (c) {
      return c.classList.contains('is-active-chapter');
    });
    let nextIdx = (activeIdx === -1 ? 0 : activeIdx + direction);
    nextIdx = Math.max(0, Math.min(nextIdx, cards.length - 1));

    const next = cards[nextIdx];
    if (!next) return;

    const start = parseInt(next.dataset.start, 10);
    if (!isNaN(start) && window.seekVideo) {
      window.seekVideo(start);
    }
    next.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /**
   * Switch the summary tab to 'detailed' if the chapter explorer lives there
   * and the current tab is something else. This ensures j/k navigation is
   * meaningful — the user can see the card that gets highlighted.
   */
  function ensureDetailedTabActive() {
    const summaryRoot = document.querySelector('[x-data*="activeTab"]');
    if (!summaryRoot) return;
    const data = summaryRoot._x_dataStack && summaryRoot._x_dataStack[0];
    if (data && typeof data.activeTab !== 'undefined' && data.activeTab !== 'detailed') {
      data.activeTab = 'detailed';
    }
  }

  function togglePlayPause() {
    if (window.__vsPlayer && typeof window.__vsPlayer === 'function') {
      const p = window.__vsPlayer();
      if (!p) return;
      const state = typeof p.getPlayerState === 'function' ? p.getPlayerState() : -1;
      if (state === 1) {
        p.pauseVideo();
      } else {
        p.playVideo();
      }
    }
  }

  // ----------------------------------------------------------------
  // Timeline segment click (delegated from document)
  // ----------------------------------------------------------------

  function activateTimelineSegment(seg) {
    if (!seg) return;
    const start = parseInt(seg.dataset.start, 10);
    if (!isNaN(start) && window.seekVideo) {
      window.seekVideo(start);
    }

    const chapterId = seg.dataset.chapterId;
    if (chapterId) {
      const card = document.getElementById('chapter-' + chapterId);
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }

  /**
   * Expose tab-switcher globally so player.js can call it when
   * auto-scrolling to an active chapter that lives inside the detailed tab.
   */
  window.vsEnsureDetailedTab = function () {
    ensureDetailedTabActive();
  };

  document.addEventListener('click', function (e) {
    const seg = e.target.closest('.vs-timeline-segment');
    if (!seg) return;
    activateTimelineSegment(seg);
  });

  document.addEventListener('keydown', function (e) {
    const seg = e.target.closest('.vs-timeline-segment');
    if (!seg) return;
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    activateTimelineSegment(seg);
  });

})();
