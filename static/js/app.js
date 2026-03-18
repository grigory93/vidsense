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

    const tabSwitched = ensureDetailedTabActive();

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
    function scrollToCard() {
      next.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    if (tabSwitched) {
      queueMicrotask(function () {
        requestAnimationFrame(function () {
          requestAnimationFrame(scrollToCard);
        });
      });
    } else {
      scrollToCard();
    }
  }

  /**
   * Switch the summary tab to 'detailed' if the chapter explorer lives there
   * and the current tab is something else. This ensures j/k navigation is
   * meaningful — the user can see the card that gets highlighted.
   */
  /**
   * @returns {boolean} true if the tab was switched to detailed (DOM not yet updated — Alpine batches)
   */
  function ensureDetailedTabActive() {
    const summaryRoot = document.querySelector('[x-data*="activeTab"]');
    if (!summaryRoot) return false;
    const data = summaryRoot._x_dataStack && summaryRoot._x_dataStack[0];
    if (data && typeof data.activeTab !== 'undefined' && data.activeTab !== 'detailed') {
      data.activeTab = 'detailed';
      return true;
    }
    return false;
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
   * @returns {boolean} true if tab was just switched (caller should defer until layout)
   */
  window.vsEnsureDetailedTab = function () {
    return ensureDetailedTabActive();
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

// ------------------------------------------------------------------
// V2 Alpine components (global scope — must be defined before Alpine
// processes HTMX-swapped content)
// ------------------------------------------------------------------

function vsGlossary() {
  return {
    terms: [],
    search: '',
    categories: [],
    activeCategories: [],
    init() {
      var el = document.getElementById('vs-glossary-data');
      if (el) {
        try { this.terms = JSON.parse(el.textContent); } catch (e) { /* ignore */ }
      }
      var cats = [];
      var seen = {};
      for (var i = 0; i < this.terms.length; i++) {
        var c = this.terms[i].category;
        if (c && !seen[c]) { seen[c] = true; cats.push(c); }
      }
      this.categories = cats.sort();
    },
    toggleCategory(cat) {
      var idx = this.activeCategories.indexOf(cat);
      if (idx >= 0) this.activeCategories.splice(idx, 1);
      else this.activeCategories.push(cat);
    },
    filtered() {
      var result = this.terms;
      if (this.search.trim()) {
        var q = this.search.toLowerCase();
        result = result.filter(function (t) {
          return t.term.toLowerCase().indexOf(q) !== -1 ||
                 t.definition.toLowerCase().indexOf(q) !== -1;
        });
      }
      if (this.activeCategories.length) {
        var ac = this.activeCategories;
        result = result.filter(function (t) { return ac.indexOf(t.category) !== -1; });
      }
      return result;
    }
  };
}

/** Escape user Q&A text for safe display (line breaks preserved). */
function vsQaEscapeUserText(text) {
  if (!text) return '';
  var div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML.replace(/\n/g, '<br>');
}

/** Markdown → sanitized HTML for assistant answers. */
function vsQaMarkdownToHtml(md) {
  if (!md) return '';
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    return vsQaEscapeUserText(md);
  }
  try {
    var raw = marked.parse(String(md), { breaks: true, gfm: true });
  } catch (e) {
    return vsQaEscapeUserText(md);
  }
  var clean = DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'b', 'i', 'del', 's', 'ul', 'ol', 'li',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'code', 'pre', 'blockquote',
      'a', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span'
    ],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
  });
  var tmp = document.createElement('div');
  tmp.innerHTML = clean;
  var links = tmp.querySelectorAll('a[href]');
  for (var i = 0; i < links.length; i++) {
    links[i].setAttribute('target', '_blank');
    links[i].setAttribute('rel', 'noopener noreferrer');
  }
  return tmp.innerHTML;
}

function vsQA(videoId) {
  return {
    videoId: videoId,
    question: '',
    messages: [],
    loading: false,
    conversationId: null,
    suggestedQuestions: [
      'What are the main topics covered?',
      'Summarize the key arguments',
      'What conclusions are drawn?'
    ],
    qaMessageHtml(msg) {
      if (!msg) return '';
      if (msg.role === 'user') return vsQaEscapeUserText(msg.content);
      return vsQaMarkdownToHtml(msg.content);
    },
    async sendQuestion() {
      var q = this.question.trim();
      if (!q || this.loading) return;
      this.messages.push({ role: 'user', content: q, citations: [] });
      this.question = '';
      this.loading = true;
      this.$nextTick(() => {
        if (this.$refs.messageList) this.$refs.messageList.scrollTop = this.$refs.messageList.scrollHeight;
      });
      try {
        var resp = await fetch('/api/video/' + this.videoId + '/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: q, conversation_id: this.conversationId })
        });
        var data = await resp.json();
        if (resp.ok) {
          this.conversationId = data.conversation_id;
          this.messages.push({ role: 'assistant', content: data.answer, citations: data.citations || [] });
        } else {
          this.messages.push({ role: 'assistant', content: (data.detail && data.detail.message) || 'Sorry, something went wrong.', citations: [] });
        }
      } catch (e) {
        this.messages.push({ role: 'assistant', content: 'Network error. Please try again.', citations: [] });
      } finally {
        this.loading = false;
        this.$nextTick(() => {
          if (this.$refs.messageList) this.$refs.messageList.scrollTop = this.$refs.messageList.scrollHeight;
        });
      }
    }
  };
}

function vsMindMap() {
  return {
    cy: null,
    init() {
      window.__vsMindMapRender = () => this._renderMindMap();
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          if (window.__vsActiveView === 'mind_map') this._renderMindMap();
        });
      });
    },
    _renderMindMap() {
      var self = this;
      var maxAttempts = 40;
      var tick = function (attempt) {
        if (typeof cytoscape === 'undefined') {
          if (attempt < maxAttempts) setTimeout(function () { tick(attempt + 1); }, 50);
          return;
        }
        var container = document.getElementById('vs-mind-map-container');
        var dataEl = document.getElementById('vs-mind-map-data');
        if (!container || !dataEl) return;
        if (container.clientWidth < 20 || container.clientHeight < 20) {
          if (attempt < maxAttempts) setTimeout(function () { tick(attempt + 1); }, 50);
          return;
        }
        var data;
        try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }

        var typeColors = {
          concept: '#2563eb', person: '#16a34a', technology: '#9333ea',
          event: '#ea580c', theory: '#0891b2', methodology: '#d946ef'
        };

        var elements = [];
        (data.nodes || []).forEach(function (n) {
          var id = n.node_id || n.id;
          if (!id) return;
          elements.push({
            data: {
              id: String(id),
              label: n.label || id,
              type: n.type || 'concept',
              description: n.description || '',
              chapter_ids: n.chapter_ids || [],
              color: typeColors[n.type] || '#64748b'
            }
          });
        });
        (data.edges || []).forEach(function (e) {
          elements.push({
            data: {
              source: String(e.source),
              target: String(e.target),
              label: e.relationship || ''
            }
          });
        });

        if (!elements.length) return;

        if (self.cy) {
          self.cy.resize();
          self.cy.fit(undefined, 48);
          return;
        }

        self.cy = cytoscape({
          container: container,
          elements: elements,
          style: [
            { selector: 'node', style: {
              'label': 'data(label)', 'background-color': 'data(color)',
              'color': '#334155', 'font-size': '11px', 'text-valign': 'bottom',
              'text-margin-y': 6, 'width': 32, 'height': 32,
              'border-width': 2, 'border-color': '#e2e8f0',
              'cursor': 'pointer'
            }},
            { selector: 'edge', style: {
              'label': 'data(label)', 'font-size': '9px', 'color': '#94a3b8',
              'line-color': '#cbd5e1', 'target-arrow-color': '#cbd5e1',
              'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
              'width': 1.5
            }},
            { selector: 'node:selected', style: {
              'border-color': '#2563eb', 'border-width': 3
            }}
          ],
          layout: { name: 'cose', animate: true, animationDuration: 500, nodeRepulsion: 8000 }
        });
        self.cy.fit(undefined, 48);

        // Build chapter lookup: chapter_id → {title, start_time_sec, start_display}
        var chapterIndex = {};
        try {
          var chIndexEl = document.getElementById('vs-chapters-index');
          if (chIndexEl) {
            (JSON.parse(chIndexEl.textContent) || []).forEach(function (ch) {
              if (ch.chapter_id) chapterIndex[ch.chapter_id] = ch;
            });
          }
        } catch (e) {}

        self.cy.on('tap', 'node', function (evt) {
          var d = evt.target.data();
          var detail = document.getElementById('vs-mind-map-detail');
          document.getElementById('vs-mm-detail-label').textContent = d.label || '';
          document.getElementById('vs-mm-detail-type').textContent = d.type || '';
          document.getElementById('vs-mm-detail-desc').textContent = d.description || '';

          var chipsEl = document.getElementById('vs-mm-detail-chapters');
          chipsEl.innerHTML = '';
          var ids = d.chapter_ids || [];
          if (ids.length) {
            var heading = document.createElement('span');
            heading.className = 'w-full text-xs text-slate-400 mb-1';
            heading.textContent = 'Appears in:';
            chipsEl.appendChild(heading);
            ids.forEach(function (cid) {
              var ch = chapterIndex[cid];
              var btn = document.createElement('button');
              btn.className = 'inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md bg-brand-50 border border-brand-200 text-brand-700 hover:bg-brand-100 transition-colors';
              if (ch) {
                btn.textContent = ch.start_display + ' ' + ch.title;
                btn.onclick = function () {
                  if (window.__vsSetActiveView) window.__vsSetActiveView('read');
                  if (window.seekVideo) window.seekVideo(ch.start_time_sec);
                };
              } else {
                btn.textContent = cid;
                btn.disabled = true;
              }
              chipsEl.appendChild(btn);
            });
          }
          detail.classList.remove('hidden');
        });

        self.cy.on('tap', function (evt) {
          if (evt.target === self.cy) {
            document.getElementById('vs-mind-map-detail').classList.add('hidden');
          }
        });
      };
      tick(0);
    }
  };
}
