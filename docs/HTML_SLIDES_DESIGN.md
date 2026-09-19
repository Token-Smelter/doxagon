# HTML Slides Design

> **Note**: This is the original design document. The implemented system differs in four ways:
> 1. **Unified Bundle UI + Display Bundle Selector** — image bundles visible for both layout types; `is_primary` field for display bundle selection (see `docs/HTML_SLIDES_REVISIONS.md`)
> 2. **HTML Slide Build** — headless Playwright rendering of HTML slides to PNG during compilation (see `docs/HTML_SLIDES_REVISIONS.md`)
> 3. **Iframe rendering** — all HTML slides render in `<iframe srcdoc>` (not inline injection as originally designed). The `dox.slide` API is bridged via `postMessage`. This provides complete JS/CSS/event isolation — slide scripts cannot conflict with presenter navigation or UI.
> 4. **Global HTML Styles** — a shared `styles/html/global.css` file injected into every HTML slide (web UI and build). See `docs/HTML_SLIDES_REVISIONS.md`.

## Problem

Slides are currently static images. Some slides need animated, interactive content — data visualizations, architectural diagrams that build up, flow animations. The HTML should be able to reference multiple generated images and compose them into an animated scene.

The current UI only renders the first image bundle (`images[0]`), even though the schema and backend already support N bundles per slide. HTML slides make this gap critical: animated compositions routinely need 3–5 distinct generated images layered together. So multi-image management is prerequisite infrastructure.

## Goals

1. UI supports N image bundles per slide (create, edit, delete, generate, select independently)
2. Slides can optionally render as inline HTML instead of a static image
3. HTML references generated images by bundle ID
4. Animations can be automatic (play on entry) or manual (step-through from presenter)
5. Presenter view shows step controls for manual-trigger slides
6. Editor shows live preview of HTML slides

## Non-Goals

- Full reveal.js fragment system
- HTML rendering in PPTX (uses fallback image)
- Hot module reloading in editor
- Step rewind (previous always goes to previous slide)

---

## 1. Filesystem

### Image slide (unchanged)

```
slides/meet-delphi/
├── slide.md
└── images/
    └── main/
        ├── definition.md
        ├── sources/
        └── outputs/
```

### HTML slide with multiple image bundles

```
slides/search-architecture/
├── slide.md
├── slide.html
└── images/
    ├── main/                    # fallback for PPTX + thumbnail
    │   ├── definition.md
    │   ├── sources/
    │   └── outputs/
    ├── flow-diagram/
    │   ├── definition.md
    │   ├── sources/
    │   └── outputs/
    └── query-result/
        ├── definition.md
        ├── sources/
        └── outputs/
```

Each bundle has its own `definition.md` (prompt, styles, config), its own `sources/`, and its own `outputs/`. Each bundle is independently assembled, generated, and has its own `selected` candidate.

### slide.md changes

Two new optional frontmatter fields. Existing slides are unaffected.

```yaml
---
layout: html              # "image" (default) | "html"
animation: manual          # "auto" (default) | "manual"

text:
  title: "Search Architecture"
speaker_notes: |
  Walk through the search flow step by step...

images:
  - id: main
    is_primary: true
    selected: outputs/generated_20260314_2.png
    placement: full-bleed
    purpose: "PPTX fallback + overview"
  - id: flow-diagram
    selected: outputs/generated_20260314_1.png
    purpose: "Animated query flow path"
  - id: query-result
    selected: outputs/generated_20260314_3.png
    purpose: "Result panel overlay"
---
```

One `selected` per image bundle. Not per slide.

---

## 2. slide.html Convention

Self-contained HTML fragment. Not a full document. Rendered inline (no iframe).

```html
<style>
  .slide-search-architecture .node {
    opacity: 0;
    transition: opacity 0.5s ease;
  }
  .slide-search-architecture .node.visible { opacity: 1; }
  .slide-search-architecture .connection {
    stroke-dasharray: 100;
    stroke-dashoffset: 100;
    transition: stroke-dashoffset 1s ease;
  }
  .slide-search-architecture .connection.active { stroke-dashoffset: 0; }
</style>

<div class="slide-search-architecture">
  <!-- Images referenced by bundle ID -->
  <img data-image-id="main" class="bg-layer" />
  <img data-image-id="flow-diagram" class="diagram-layer" />

  <div class="node node-1">Retrieval</div>
  <div class="node node-2">Extraction</div>
  <div class="node node-3">Query</div>

  <svg class="connections-overlay">
    <path class="connection c1" d="M100,50 L200,50" />
    <path class="connection c2" d="M200,50 L300,50" />
  </svg>
</div>

<script>
  const slide = dox.slide;

  slide.steps(3);

  slide.onStep(1, () => {
    document.querySelector('.node-1').classList.add('visible');
  });

  slide.onStep(2, () => {
    document.querySelector('.node-2').classList.add('visible');
    document.querySelector('.c1').classList.add('active');
  });

  slide.onStep(3, () => {
    document.querySelector('.node-3').classList.add('visible');
    document.querySelector('.c2').classList.add('active');
  });

  slide.onExit(() => {
    document.querySelectorAll('.visible').forEach(el => el.classList.remove('visible'));
    document.querySelectorAll('.active').forEach(el => el.classList.remove('active'));
  });
</script>
```

### Conventions

- **Style scoping**: Prefix all selectors with `.slide-{slug}`. Convention-enforced, not rewritten. This is a personal authoring tool, not user-generated content.
- **Image references**: `<img data-image-id="{bundle-id}" />` or `slide.imageUrl("{bundle-id}")` in scripts. The runtime resolves these to full asset URLs.
- **Scripts**: Executed in order after HTML injection. Trusted — no sandboxing.

---

## 3. Slide Controller API

`window.dox.slide` is injected before the HTML is mounted. Each slide gets a fresh instance.

```typescript
interface SlideController {
  // Declare total manual steps (ignored in auto mode)
  steps(count: number): void;

  // Register callback for step N (1-indexed)
  onStep(step: number, callback: () => void): void;

  // Called when slide becomes active
  onEnter(callback: () => void): void;

  // Called when navigating away
  onExit(callback: () => void): void;

  // Resolve image URL by bundle ID
  imageUrl(imageId: string): string;

  // Read-only state
  readonly currentStep: number;
  readonly totalSteps: number;
}
```

### Lifecycle

```
Navigate to HTML slide
  │
  ├─ Create SlideController, set window.dox.slide
  ├─ Set htmlContainer.innerHTML = resolved HTML
  ├─ Extract <script> tags, execute in order
  ├─ Resolve data-image-id attributes → asset URLs
  ├─ Fire onEnter callbacks
  │
  ├─ AUTO mode: fire steps sequentially (1s delay each)
  ├─ MANUAL mode: wait for presenter advance
  │     └─ Each "next" fires the next onStep callback
  │     └─ After last step, next "next" goes to next slide
  │
  └─ Navigate away
       ├─ Fire onExit callbacks
       └─ Clear container, dispose controller
```

### Navigation interaction with steps

In manual mode, the existing navigation flow is intercepted:

| Action | Steps remaining? | Result |
|--------|-----------------|--------|
| Next (arrow right / click) | Yes | Advance to next step |
| Next | No | Go to next slide |
| Previous (arrow left) | Any | Go to previous slide (no step rewind) |

---

## 4. Data Model Changes

### `SlideDetail` (models.py)

Three new fields. All optional with backward-compatible defaults.

```python
class SlideDetail(BaseModel):
    number: int
    slug: str
    title: str
    body: str
    speaker_notes: str = ""
    images: list[SlideImage] = []
    doxai: list[str] = []
    layout: str = "image"            # NEW
    animation: str = "auto"          # NEW
    html_content: str | None = None  # NEW: contents of slide.html
```

### `SlideListItem` (models.py)

Two new fields for the slide list sidebar.

```python
class SlideListItem(BaseModel):
    # ... existing fields ...
    layout: str = "image"            # NEW
    image_count: int = 1             # NEW
```

### Frontend types (`api.ts`)

```typescript
export interface SlideDetail {
    // ... existing fields ...
    layout: 'image' | 'html';
    animation: 'auto' | 'manual';
    html_content: string | null;
}

export interface SlideListItem {
    // ... existing fields ...
    layout: 'image' | 'html';
    image_count: number;
}
```

---

## 5. Backend Changes

### Existing endpoints (already multi-image capable)

These endpoints already accept `image_id` as a path parameter. No changes needed:

| Endpoint | Status |
|----------|--------|
| `PUT /slides/{slide}/images/{id}/selected` | ✅ Works for any bundle |
| `PUT /slides/{slide}/images/{id}/definition` | ✅ Works for any bundle |
| `PUT /slides/{slide}/images/{id}/styles` | ✅ Works for any bundle |
| `POST /slides/{slide}/images/{id}/assemble-prompt` | ✅ Works for any bundle |
| `POST /slides/{slide}/images/{id}/generate` | ✅ Works for any bundle |

### Modified endpoints

**`GET /slides/{slide}`** — Read `layout`, `animation` from frontmatter. If `layout == "html"` and `slide.html` exists, read and return it as `html_content`.

**`GET /slides`** — Include `layout` and `image_count` in each list item.

### New endpoints

**`POST /{slug}/slides/{slide_slug}/images`** — Create image bundle

```python
class ImageBundleCreateRequest(BaseModel):
    id: str           # e.g., "flow-diagram"
    purpose: str = ""

class ImageBundleCreateResponse(BaseModel):
    success: bool
    id: str
```

Creates the directory structure:
```
images/{id}/
├── definition.md     # starter template
├── sources/
└── outputs/
```

Appends to `slide.md` images array:
```yaml
- id: flow-diagram
  purpose: ""
```

Validates: ID must be `[a-z0-9-]+`, must not already exist, must not be empty.

**`DELETE /{slug}/slides/{slide_slug}/images/{image_id}`** — Delete image bundle

Removes the `images/{id}/` directory and its entry from `slide.md`. Refuses to delete the last remaining bundle (always need at least one for PPTX fallback).

**`PUT /{slug}/slides/{slide_slug}/html`** — Save HTML content

```python
class HtmlContentRequest(BaseModel):
    content: str

class HtmlContentResponse(BaseModel):
    success: bool
```

Writes `content` to `slide.html`. Creates the file if it doesn't exist.

**`PUT /{slug}/slides/{slide_slug}/layout`** — Update layout and animation

```python
class LayoutUpdateRequest(BaseModel):
    layout: str | None = None       # "image" | "html"
    animation: str | None = None    # "auto" | "manual"
```

Updates frontmatter fields in `slide.md`. When setting `layout: html` for the first time and no `slide.html` exists, creates one with a starter template:

```html
<style>
  .slide-{slug} {
    width: 100%;
    height: 100%;
    position: relative;
  }
</style>

<div class="slide-{slug}">
  <img data-image-id="main" />
</div>

<script>
  const slide = dox.slide;
  // slide.steps(N);
  // slide.onStep(1, () => { ... });
</script>
```

---

## 6. Frontend Changes

### 6a. Multi-Image UI (`SlideDetailView.svelte`)

Replace the single `mainImage = detail.images[0]` pattern with iteration over all bundles.

**New component: `ImageBundleEditor.svelte`**

Extract the existing image editing UI (candidate grid, style picker, constraints editor, visual description editor, assemble button, generate button) into a self-contained component that accepts a single `SlideImage` and renders the full editor for it.

```svelte
<!-- ImageBundleEditor.svelte -->
<script lang="ts">
  export let image: SlideImage;
  export let thesisSlug: string;
  export let slideSlug: string;
  export let canDelete: boolean;
  export let onDelete: () => void;
</script>

<div class="image-bundle">
  <div class="bundle-header">
    <span class="bundle-id">{image.id}</span>
    <span class="bundle-purpose">{image.purpose}</span>
    {#if canDelete}
      <button class="delete-btn" on:click={onDelete}>×</button>
    {/if}
  </div>
  <!-- selected preview, candidates, style picker, definition editor, generate -->
</div>
```

**Updated `SlideDetailView.svelte`**

```svelte
<section class="images-section">
  <div class="section-header">
    <h3>Image Bundles ({detail.images.length})</h3>
    <button class="add-btn" on:click={handleAddBundle}>+</button>
  </div>

  {#each detail.images as image (image.id)}
    <ImageBundleEditor
      {image}
      {thesisSlug}
      slideSlug={detail.slug}
      canDelete={detail.images.length > 1}
      onDelete={() => handleDeleteBundle(image.id)}
    />
  {/each}
</section>
```

The "+" button opens a small popover/inline form asking for bundle ID and purpose, then calls `POST /images`.

### 6b. Layout Toggle

Above the image bundles section, a toggle to switch between image and HTML layout:

```svelte
<div class="layout-toggle">
  <button class:active={detail.layout === 'image'}
    on:click={() => updateLayout('image')}>
    Image
  </button>
  <button class:active={detail.layout === 'html'}
    on:click={() => updateLayout('html')}>
    HTML
  </button>
  {#if detail.layout === 'html'}
    <select bind:value={detail.animation} on:change={handleAnimationChange}>
      <option value="auto">Auto</option>
      <option value="manual">Manual</option>
    </select>
  {/if}
</div>
```

### 6c. HTML Editor + Live Preview

Visible when `layout === 'html'`. Side-by-side code editor and preview.

```svelte
{#if detail.layout === 'html'}
  <section class="html-section">
    <h3>HTML Content</h3>
    <div class="html-editor-preview">
      <div class="editor-pane">
        <EditableField
          value={detail.html_content || ''}
          label="slide.html"
          monospace
          multiline
          onSave={handleSaveHtml}
        />
      </div>
      <div class="preview-pane">
        <div class="preview-frame" bind:this={previewContainer}></div>
      </div>
    </div>
  </section>
{/if}
```

The preview pane renders the HTML inline using the same injection logic as `AudienceDisplay` — image refs resolved, scripts executed, controller provided. Updates on save.

### 6d. AudienceDisplay — HTML Slide Rendering

`AudienceDisplay.svelte` currently has a single `<img>` tag in its slide container. Add a conditional branch:

```svelte
<div class="slide-container" bind:this={slideContainer}>
  {#if currentSlideLayout === 'html' && currentSlideHtml}
    <div class="html-slide-root" bind:this={htmlSlideContainer}></div>
  {:else}
    <img class="slide-image" src={slideImageUrl} ... />
  {/if}
</div>
```

**HTML injection logic** (in `<script>`):

```typescript
import { SlideController } from '$lib/utils/slideController';

let controller: SlideController | null = null;
let htmlSlideContainer: HTMLElement;

// Reactive: when current slide changes to an HTML slide
$: if (currentSlideLayout === 'html' && currentSlideHtml && htmlSlideContainer) {
  mountHtmlSlide(currentSlideHtml, currentSlideImages);
}

function mountHtmlSlide(html: string, images: SlideImage[]) {
  // Dispose previous
  if (controller) {
    controller.exit();
    controller = null;
  }
  htmlSlideContainer.innerHTML = '';

  // Create controller
  controller = new SlideController(images, thesisSlug, slideSlug);
  window.dox = { slide: controller };

  // Inject HTML (without scripts)
  const template = document.createElement('template');
  template.innerHTML = html;
  const scripts: HTMLScriptElement[] = [];

  template.content.querySelectorAll('script').forEach(script => {
    scripts.push(script);
    script.remove();
  });

  htmlSlideContainer.appendChild(template.content);

  // Resolve image references
  resolveImageRefs(htmlSlideContainer, images, thesisSlug, slideSlug);

  // Execute scripts in order
  scripts.forEach(original => {
    const exec = document.createElement('script');
    exec.textContent = original.textContent;
    htmlSlideContainer.appendChild(exec);
  });

  // Enter
  controller.enter();
}
```

**Step-aware navigation override**:

```typescript
// In AudienceDisplay click/keydown handler:
function handleNext() {
  if (controller && currentSlideAnimation === 'manual' && controller.hasMoreSteps()) {
    controller.advanceStep();
    broadcastStepState(controller.currentStep, controller.totalSteps);
  } else {
    navigatePresentSlide('next');
  }
}
```

### 6e. Presenter View — Step Controls

`present/[thesis]/+page.svelte` shows step state for HTML slides with manual animation:

```svelte
{#if currentSlideLayout === 'html' && currentSlideAnimation === 'manual' && totalSteps > 0}
  <div class="step-controls">
    <span class="step-label">Step</span>
    <span class="step-counter">{currentStep} / {totalSteps}</span>
    <div class="step-dots">
      {#each Array(totalSteps) as _, i}
        <span class="step-dot" class:completed={i < currentStep}></span>
      {/each}
    </div>
  </div>
{/if}
```

The presenter receives `STEP_STATE` broadcasts from the audience display and updates its local state. The presenter's "Next" button sends `STEP_ADVANCE` when steps remain.

---

## 7. Broadcast Sync Protocol

New message types added to `broadcastSync.ts`:

```typescript
export type SyncMessageType =
    // existing...
    | 'STEP_ADVANCE'    // Presenter → Audience: advance one step
    | 'STEP_STATE';     // Audience → Presenter: current step state

export interface StepAdvancePayload {
    // empty — just a signal
}

export interface StepStatePayload {
    current: number;    // 0 = no steps triggered
    total: number;
}
```

Flow:
1. Audience display mounts HTML slide → broadcasts `STEP_STATE { current: 0, total: 3 }`
2. Presenter shows "Step 0 / 3" with empty dots
3. User clicks Next in presenter → broadcasts `STEP_ADVANCE`
4. Audience fires step 1, broadcasts `STEP_STATE { current: 1, total: 3 }`
5. Presenter shows "Step 1 / 3" with one filled dot
6. After step 3, next "Next" advances to next slide (audience broadcasts `SLIDE_CHANGE`)

---

## 8. SlideController Implementation

New file: `apps/web/frontend/src/lib/utils/slideController.ts`

```typescript
import { getThesisAssetUrl } from '$lib/api';
import type { SlideImage } from '$lib/api';

export class SlideController {
  private _totalSteps = 0;
  private _currentStep = 0;
  private _stepCallbacks = new Map<number, () => void>();
  private _enterCallbacks: (() => void)[] = [];
  private _exitCallbacks: (() => void)[] = [];
  private _images: SlideImage[];
  private _thesisSlug: string;
  private _slideSlug: string;

  constructor(images: SlideImage[], thesisSlug: string, slideSlug: string) {
    this._images = images;
    this._thesisSlug = thesisSlug;
    this._slideSlug = slideSlug;
  }

  steps(count: number): void {
    this._totalSteps = count;
  }

  onStep(step: number, callback: () => void): void {
    this._stepCallbacks.set(step, callback);
  }

  onEnter(callback: () => void): void {
    this._enterCallbacks.push(callback);
  }

  onExit(callback: () => void): void {
    this._exitCallbacks.push(callback);
  }

  imageUrl(imageId: string): string {
    const image = this._images.find(img => img.id === imageId);
    if (image?.selected) {
      return getThesisAssetUrl(
        this._thesisSlug,
        `${this._slideSlug}/images/${imageId}/${image.selected}`
      );
    }
    return '';
  }

  get currentStep(): number { return this._currentStep; }
  get totalSteps(): number { return this._totalSteps; }

  hasMoreSteps(): boolean {
    return this._currentStep < this._totalSteps;
  }

  advanceStep(): boolean {
    if (!this.hasMoreSteps()) return false;
    this._currentStep++;
    const cb = this._stepCallbacks.get(this._currentStep);
    if (cb) cb();
    return true;
  }

  enter(): void {
    this._currentStep = 0;
    this._enterCallbacks.forEach(cb => cb());
  }

  exit(): void {
    this._exitCallbacks.forEach(cb => cb());
    this._stepCallbacks.clear();
    this._enterCallbacks = [];
    this._exitCallbacks = [];
  }

  /** Auto-play all steps with delay between each. */
  async autoPlay(delayMs: number = 1000): Promise<void> {
    for (let i = 1; i <= this._totalSteps; i++) {
      await new Promise(resolve => setTimeout(resolve, delayMs));
      this.advanceStep();
    }
  }

  dispose(): void {
    this.exit();
    this._images = [];
  }
}
```

---

## 9. Image Reference Resolution

Standalone utility function used by both AudienceDisplay and the editor preview.

```typescript
// apps/web/frontend/src/lib/utils/imageResolver.ts

import { getThesisAssetUrl } from '$lib/api';
import type { SlideImage } from '$lib/api';

export function resolveImageRefs(
  container: HTMLElement,
  images: SlideImage[],
  thesisSlug: string,
  slideSlug: string
): void {
  container.querySelectorAll<HTMLImageElement>('[data-image-id]').forEach(el => {
    const imageId = el.dataset.imageId;
    if (!imageId) return;

    const image = images.find(img => img.id === imageId);
    if (image?.selected) {
      el.src = getThesisAssetUrl(
        thesisSlug,
        `${slideSlug}/images/${imageId}/${image.selected}`
      );
    }
  });
}
```

---

## 10. Compile Changes

> **Updated**: See `docs/HTML_SLIDES_REVISIONS.md` Change 2 for the implemented build behavior.

### Markdown output (`compile.py`)

HTML slides use their first image bundle's selected image as fallback, same as image slides. Add a marker:

```markdown
## Slide 7: Search Architecture
*[Animated HTML slide — 3 image bundles]*

![Search Architecture](img/standard/slide-7.png)

> Speaker notes...
```

### PPTX output

HTML slides are rendered to PNG via headless Playwright (`render_html_slide.py`). The script:
1. Resolves `data-image-id` references to local `file://` paths
2. Injects a stub `dox.slide` API (captures initial state, step 0)
3. Screenshots the HTML at 1920×1080

Falls back to `find_slide_image()` (display bundle via `is_primary`, then `images[0]`) if Playwright is unavailable.

---

## 11. Implementation Phases

### Phase 1: Multi-Image UI

Unlock the N-bundle model that the backend already supports.

| Task | Layer | Files |
|------|-------|-------|
| Extract `ImageBundleEditor.svelte` from `SlideDetailView` | Frontend | New component |
| Render all images in `SlideDetailView` | Frontend | `SlideDetailView.svelte` |
| `POST /images` endpoint (create bundle) | Backend | `theses.py` |
| `DELETE /images/{id}` endpoint | Backend | `theses.py` |
| "+" button and delete button in UI | Frontend | `SlideDetailView.svelte` |
| Add `image_count` to `SlideListItem` | Backend + Frontend | `models.py`, `api.ts` |
| Add `image_count` to `list_slides()` | Backend | `theses.py` |

### Phase 2: HTML Slide Schema + Backend

| Task | Layer | Files |
|------|-------|-------|
| Add `layout`, `animation`, `html_content` to `SlideDetail` | Backend | `models.py` |
| Add `layout` to `SlideListItem` | Backend | `models.py` |
| Read new fields in `get_slide()` | Backend | `theses.py` |
| Read `layout` in `list_slides()` | Backend | `theses.py` |
| `PUT /html` endpoint | Backend | `theses.py` |
| `PUT /layout` endpoint | Backend | `theses.py` |
| Update TypeScript types | Frontend | `api.ts` |
| Add API functions for new endpoints | Frontend | `api.ts` |

### Phase 3: Slide Controller + Audience Display

| Task | Layer | Files |
|------|-------|-------|
| Implement `SlideController` class | Frontend | New: `slideController.ts` |
| Implement `resolveImageRefs` utility | Frontend | New: `imageResolver.ts` |
| HTML injection in `AudienceDisplay` | Frontend | `AudienceDisplay.svelte` |
| Step-aware navigation override | Frontend | `AudienceDisplay.svelte` |
| Update `presentMode.ts` for step state | Frontend | `presentMode.ts` |
| Preload `html_content` in slide cache | Frontend | `presentMode.ts` |

### Phase 4: Presenter Integration

| Task | Layer | Files |
|------|-------|-------|
| Add `STEP_ADVANCE`, `STEP_STATE` to sync protocol | Frontend | `broadcastSync.ts` |
| Step controls in presenter view | Frontend | `present/[thesis]/+page.svelte` |
| Sync handler for step state in presenter | Frontend | `present/[thesis]/+page.svelte` |
| Sync handler for step advance in audience | Frontend | `AudienceDisplay.svelte` |

### Phase 5: Editor Preview

| Task | Layer | Files |
|------|-------|-------|
| Layout toggle in `SlideDetailView` | Frontend | `SlideDetailView.svelte` |
| HTML editor pane | Frontend | `SlideDetailView.svelte` |
| Live preview with inline rendering | Frontend | `SlideDetailView.svelte` |
| Starter template on first switch to HTML | Backend | `PUT /layout` endpoint |
| Store actions for layout/html updates | Frontend | `presentation.ts` |

---

## 10. Global HTML Styles

> **Implemented**: See `docs/HTML_SLIDES_REVISIONS.md` Change 3.

One `global.css` file per presentation at `styles/html/global.css` is injected into every HTML slide:

- **Web UI**: Injected as a `<style id="dox-global-styles">` tag into every iframe at mount time
- **Build time**: Injected by `render_html_slide.py` during Playwright render
- **Purpose**: Define CSS custom properties, fonts, base classes shared across all HTML slides
- **Overrides**: Individual slides override with local `<style>` blocks (cascade order: global → local)
- **Editing**: From the slide editor UI (Global HTML Styles collapsible section) or directly on disk

### File Location

```
theses/{name}/
└── outputs/
    └── presentation/
        └── styles/
            └── html/
                └── global.css    # Shared CSS for all HTML slides
```

### Example

```css
:root {
  --accent: #f4a261;
  --bg: #0a0a0a;
  --text: #e8e8e8;
}

body {
  font-family: 'Inter', sans-serif;
  background: var(--bg);
  color: var(--text);
}
```

### API

- `GET /{slug}/html-styles` — returns `{ content: string }`
- `PUT /{slug}/html-styles` — accepts `{ content: string }`
