---
name: VidSense UX Redesign
overview: Comprehensive UI/UX redesign of VidSense to transform it from a functional but generic interface into a polished, fluid knowledge-extraction experience that clearly differentiates from YouTube's built-in features through better information architecture, micro-interactions, and progressive disclosure.
todos:
  - id: layout-overhaul
    content: "Redesign video.html to two-panel layout: scrollable content on left, sticky player + metadata + regenerate widget on right. Mobile fallback with floating mini-player."
    status: completed
  - id: landing-page
    content: "Enhance index.html: instant thumbnail-first URL preview with optional lightweight title metadata when available, focus prompt suggestion chips, feature value strip below form, entrance animations, remove READ MODULE label."
    status: completed
  - id: summary-section
    content: "Redesign summary tabs in results.html: card-based depth selector with descriptions, reading-depth and use-case cues, copy-to-clipboard, crossfade transitions, better typography per level."
    status: completed
  - id: chapter-cards
    content: "Improve chapter UX: mini timeline bar, chapter numbering, larger timestamps with play icon + duration badge, stronger active state, better key points, staggered entrance."
    status: completed
  - id: processing-state
    content: Replace spinner with skeleton loading layout, better stepper bar with icons, estimated completion time hint.
    status: completed
  - id: state-consistency
    content: Unify complete, partial, empty, warning, and failure states across results.html and error.html so processing, quality-warning, missing-component, and retry flows share one visual language.
    status: completed
  - id: animations-css
    content: "Add app.css animations: fadeInUp for content, skeleton shimmer, hover lift on cards, smooth transitions, timeline bar styles, toast styles."
    status: completed
  - id: js-polish
    content: "Add shell-level UI behavior in app.js: copy-to-clipboard, scoped keyboard shortcuts, toast notification system, timeline click interaction, scroll sync, and non-blocking feedback. Keep player-specific controls/sync logic in player.js."
    status: completed
  - id: regeneration-ux
    content: "Refine regeneration UX in video.html: prefill active focus prompt, preserve user-entered prompt on failure, replace alert() with inline/toast feedback, and keep current context visible while new results load."
    status: completed
  - id: shell-nav-polish
    content: "Update base.html shell: remove READ MODULE, add back-nav on video pages, breadcrumb support, and SVG favicon."
    status: completed
isProject: false
---

# VidSense UI/UX Redesign

## Current State Assessment

After reviewing all 9 templates, 3 static asset files, the live app across multiple states (landing, read screen, partial results), and the PRD requirements, here are the **critical UX problems** ranked by impact:

### High-Priority Issues

1. **Video player is NOT sticky** -- Despite the PRD mandating a "sticky player", the current layout (`video.html`) places the player at the top of a single scrollable column. Once the user scrolls to read summaries/chapters, the player disappears entirely. This defeats the core value of clickable timestamps.
2. **Single-column layout kills the reading experience** -- Summaries and chapters are stacked below a full-width video player. The user must choose: watch the video OR read the content. They cannot do both simultaneously. This is the opposite of what a "text-first reading experience" should be.
3. **No URL preview on the landing page** -- When a user pastes a URL, there is zero visual feedback before committing to analysis. A thumbnail + title preview would build confidence and reduce wasted API calls.
4. **Summary tabs are visually weak** -- The three-level summary system (Quick Take / Executive / Detailed) is VidSense's primary differentiator over YouTube, but the tabs are tiny pills with no description. Users do not understand what each level offers.
5. **Chapter cards lack visual timeline context** -- Chapters are a vertical list of cards with no visual indication of where they fall in the video's timeline. There is no sense of progress, position, or relative duration.
6. **Regenerate UI competes with the content** -- The focus prompt + regenerate button sit in the title bar, making the header feel crowded and burying the regeneration feature.
7. **No content animations** -- Content appears instantly with zero transition. No fade-in, no stagger, no skeleton loading. The experience feels static and unpolished.
8. **"READ MODULE" nav label** -- Internal jargon visible to users. Should be removed or replaced with user-facing content.

### Medium-Priority Issues

1. No back navigation from the read screen to the landing page.
2. No copy-to-clipboard for summaries.
3. Processing spinner is generic -- no skeleton preview, no time estimate.
4. No keyboard shortcuts (j/k for chapter nav, space for play/pause).
5. Focus prompt has no guided examples/suggestions.
6. Chapter timestamps are tiny (`text-xs` pills) and easy to miss.
7. No favicon (shows 404 in server logs).

---

## Redesign Strategy

### A. Read Screen -- Two-Panel Layout with Sticky Player ([app/templates/video.html](app/templates/video.html))

Replace the single-column layout with a responsive two-panel design:

- **Left panel (60% width):** Scrollable content area with summaries and chapters.
- **Right panel (40% width):** Sticky YouTube player + video metadata + regenerate widget, fixed in viewport as user scrolls content.
- **Mobile fallback:** Single column with a "picture-in-picture" mini-player that floats as the user scrolls past.

Key layout changes in `video.html`:

```html
<!-- Desktop: two-panel layout -->
<div class="flex h-[calc(100vh-3.5rem)]">
  <!-- Left: scrollable content -->
  <div class="flex-1 overflow-y-auto px-6 py-6">
    <!-- summaries + chapters here -->
  </div>
  <!-- Right: sticky sidebar with player -->
  <div class="w-[440px] shrink-0 border-l border-slate-200 overflow-y-auto bg-white">
    <div class="sticky top-0">
      <!-- player + metadata + regenerate -->
    </div>
  </div>
</div>
```

### B. Landing Page -- URL Preview and Guided Focus ([app/templates/index.html](app/templates/index.html))

- **Live URL preview:** When a valid YouTube URL is pasted, immediately display the video thumbnail inline using `https://img.youtube.com/vi/{id}/hqdefault.jpg`. If lightweight metadata is readily available without complicating the flow, also show the title; otherwise keep the preview thumbnail-first rather than introducing unnecessary backend work.
- **Focus prompt suggestions:** Replace the empty textarea with chip-based example prompts users can click to prefill (e.g., "Key takeaways", "Technical details", "Step-by-step instructions").
- **Feature value strip:** Below the form, show 3 icon+label cards highlighting what VidSense produces (Layered Summaries, Smart Chapters, Clickable Timestamps) to set expectations.
- **Remove "READ MODULE"** from the nav; replace with a subtle tagline or nothing.
- **Entrance animations:** Hero text and form card fade/slide in on page load.

### C. Summary Section -- Card-Based Depth Selector ([app/templates/partials/results.html](app/templates/partials/results.html))

Replace the tiny pill tabs with descriptive card-based selectors:

- Each tab becomes a small card with a title, a one-line description, and a depth icon (1 bar, 2 bars, 3 bars).
- Active tab has a prominent brand-color indicator and elevated shadow.
- Each depth selector explicitly communicates purpose, expected reading depth, and when to use it so the three summary levels feel intentionally different rather than cosmetic variants.
- Add a copy-to-clipboard icon on the active summary content.
- Thesis summary gets a visually distinct treatment: larger font, branded highlight card, quote-mark glyph.
- Executive summary: well-spaced paragraphs with a reading-time estimate.
- Detailed outline: numbered list with better visual grouping.
- Smooth crossfade animation between tab switches using Alpine.js transitions.

### D. Chapter Cards -- Timeline and Visual Hierarchy ([app/templates/partials/chapter_card.html](app/templates/partials/chapter_card.html), [app/templates/partials/results.html](app/templates/partials/results.html))

- **Mini timeline bar** above the chapter list: a horizontal bar showing the video's full duration with colored segments for each chapter. Clicking a segment scrolls to that chapter card and seeks the video.
- **Chapter numbering**: Add "Chapter 1", "Chapter 2" labels for scanability.
- **Larger timestamps**: Increase from `text-xs` to `text-sm`, with a play icon inside the button to signal clickability.
- **Duration badge**: Show duration per chapter (e.g., "2m 14s") alongside the timestamp.
- **Active chapter**: Strong left-border accent + subtle background gradient + "Now Playing" badge when the video is in that chapter's time range.
- **Key points**: Upgrade from tiny dots to checkmark-style items with slightly larger text.
- **Transcript accordion**: Smoother expand/collapse with Alpine.js transition and a line-count preview (e.g., "View transcript (24 lines)").
- **Staggered entrance animation**: Chapters fade in sequentially on initial load.

### E. Processing State -- Skeleton Loading ([app/templates/partials/processing.html](app/templates/partials/processing.html))

- Replace the centered spinner with a **skeleton layout** that previews the actual content structure: gray shimmer blocks where the summary tabs, summary text, and chapter cards will appear.
- Keep the progress step indicator but make it more prominent: a horizontal stepper bar with icons and labels.
- Add an **estimated completion time** hint based on video duration (short videos: ~30s, medium: ~1-2 min).
- Pulse animation on skeleton blocks to indicate loading.

### F. State Consistency -- Partial, Empty, Warning, and Failure Surfaces ([app/templates/partials/results.html](app/templates/partials/results.html), [app/templates/partials/error.html](app/templates/partials/error.html))

- Apply one visual language across processing, complete, partial, empty, recoverable failure, and non-recoverable failure states so the product feels cohesive instead of fragmentary.
- Explicitly cover these states in the redesign: no transcript, poor transcript quality warning, temporary/rate-limit issue, regeneration failure, missing chapters with available summaries, and no-results fallbacks.
- Preserve actionability: every state should give the user a clear next step such as retry, regenerate, revise focus, or try another video.
- Make partial-result messaging feel integrated with the surrounding content rather than like a disconnected alert banner.

### G. Regeneration UX and Focus Persistence ([app/templates/video.html](app/templates/video.html), [static/js/app.js](static/js/app.js))

- Move regeneration away from blocking browser alerts and into inline or toast-based feedback.
- Prefill the focus field from the active run when available, and preserve in-progress user edits during regeneration failures.
- Keep the current reading context visible while regeneration starts when possible, instead of blanking the page immediately.
- Make regeneration feedback explicit: starting, queued/in progress, succeeded, failed, and reused cached transcript.

### H. Micro-Interactions and Polish ([static/css/app.css](static/css/app.css), [static/js/app.js](static/js/app.js), [static/js/player.js](static/js/player.js))

- **Content fade-in:** All major content blocks use `@keyframes fadeInUp` when they appear (via HTMX `afterSwap` hook or Alpine.js `x-transition`).
- **Hover states:** Chapter cards elevate on hover with a subtle shadow lift. Timestamps pulse briefly on hover.
- **Toast notifications:** When copying summary text or starting regeneration, show a brief toast.
- **Keyboard shortcuts**: `j`/`k` to navigate chapters, `p` to toggle play/pause, `Escape` to go back. Shortcuts must be scoped to the read screen, disabled while the user is typing in inputs/textareas, and must not conflict with YouTube player focus.
- **Smooth scroll:** When clicking a chapter from the timeline bar, smooth-scroll to the card.
- **Better scrollbar styling** for the content panel with thin, brand-colored scrollbar.
- Keep shell-level interactions in `app.js`, while player-specific behavior and chapter sync remain in `player.js`.

### I. Navigation, Header, and Favicon ([app/templates/base.html](app/templates/base.html))

- Remove "READ MODULE" text from header.
- On the video page, show a back-arrow link next to the VidSense logo to return to home.
- Add a subtle breadcrumb: "VidSense > [Video Title]".
- Add a simple SVG favicon derived from the existing video-camera icon in the nav.

---

## Files Changed


| File                                       | Change                                                                                                                             |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `app/templates/base.html`                  | Shell polish: remove "READ MODULE", add back-nav, breadcrumb support, favicon                                                      |
| `app/templates/index.html`                 | Thumbnail-first URL preview, focus prompt chips, feature strip, entrance animations                                                |
| `app/templates/video.html`                 | Two-panel layout, sticky player sidebar, better title area, regeneration UX, focus persistence                                     |
| `app/templates/partials/results.html`      | Card-based summary tabs, copy button, clearer summary depth cues, timeline bar, chapter numbering, partial/empty-state consistency |
| `app/templates/partials/chapter_card.html` | Larger timestamps, duration badge, better key points, active state                                                                 |
| `app/templates/partials/processing.html`   | Skeleton loading layout, better stepper, time estimate                                                                             |
| `app/templates/partials/error.html`        | Unified error/warning/retry treatment consistent with the redesigned states                                                        |
| `static/css/app.css`                       | Animations (@keyframes), skeleton shimmer, timeline styles, transitions, toast styles                                              |
| `static/js/app.js`                         | Copy-to-clipboard, scoped shortcuts, toast system, non-blocking feedback, timeline interaction                                     |
| `static/js/player.js`                      | Player-specific controls and enhanced active-chapter sync with timeline                                                            |


---

## What Stays the Same

- Core FastAPI route structure, processing pipeline, and data model stay the same; this redesign remains primarily template/CSS/JS work.
- If preview metadata beyond the thumbnail is added, keep it lightweight and avoid turning the redesign into a backend-heavy feature.
- HTMX polling mechanism for processing status.
- Alpine.js for client-side state management.
- Tailwind CSS as the styling foundation.
- YouTube IFrame API integration.
- All Pydantic schemas and database models.

