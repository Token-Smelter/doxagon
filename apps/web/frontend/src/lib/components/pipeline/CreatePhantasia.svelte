<script lang="ts">
  import { createEventDispatcher, onMount, tick } from "svelte";
  import { createPhantasia } from "../../api";

  const dispatch = createEventDispatcher<{
    close: void;
    created: { slug: string };
  }>();
  let source = "";
  let title = "";
  let channel = "";
  let sharedBy = "";
  let tags = "";
  let content = "";
  let submitting = false;
  let error: string | null = null;
  let sourceInput: HTMLInputElement;
  let dialog: HTMLDivElement;
  let opener: HTMLElement | null = null;

  onMount(() => {
    opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusFrame = window.requestAnimationFrame(() => sourceInput.focus());

    return () => {
      window.cancelAnimationFrame(focusFrame);
      restoreOpenerFocus();
    };
  });

  function restoreOpenerFocus() {
    window.setTimeout(() => opener?.focus());
  }

  function close() {
    dispatch("close");
    restoreOpenerFocus();
  }

  async function handleSubmit() {
    if (!source.trim()) {
      error = "Source is required";
      await tick();
      sourceInput.focus();
      return;
    }
    submitting = true;
    error = null;
    try {
      const result = await createPhantasia({
        source: source.trim(),
        title: title.trim() || undefined,
        channel: channel.trim() || undefined,
        shared_by: sharedBy.trim() || undefined,
        tags: tags.trim()
          ? tags
              .split(",")
              .map((t) => t.trim())
              .filter(Boolean)
          : undefined,
        content: content.trim() || undefined,
      });
      dispatch("created", { slug: result.slug });
      close();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to create phantasia";
    } finally {
      submitting = false;
    }
  }
  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key !== "Tab") return;

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => element.offsetParent !== null);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;

    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />
<div
  class="modal-backdrop"
  on:click={close}
  role="presentation"
>
  <div
    class="modal"
    bind:this={dialog}
    on:click|stopPropagation
    role="dialog"
    aria-modal="true"
    aria-labelledby="modal-title"
  >
    <div class="modal-header">
      <div>
        <p class="eyebrow">Intake / phantasia</p>
        <h2 id="modal-title">New Phantasia</h2>
      </div>
      <button
        class="close-btn"
        on:click={close}
        aria-label="Close new phantasia form">×</button
      >
    </div>
    <form on:submit|preventDefault={handleSubmit}>
      {#if error}<div class="error" role="alert">
          <span aria-hidden="true">!</span>{error}
        </div>{/if}
      <div class="form-group">
        <label for="source"
          >Source <span class="required">(required)</span></label
        ><input
          bind:this={sourceInput}
          type="text"
          id="source"
          bind:value={source}
          aria-required="true"
          placeholder="URL, file path, or description"
        />
      </div>
      <div class="form-group">
        <label for="title">Title</label><input
          type="text"
          id="title"
          bind:value={title}
          placeholder="Auto-generated from source if empty"
        />
      </div>
      <div class="form-row">
        <div class="form-group">
          <label for="channel">Channel</label><input
            type="text"
            id="channel"
            bind:value={channel}
            placeholder="e.g., twitter, rss, email"
          />
        </div>
        <div class="form-group">
          <label for="shared-by">Shared by</label><input
            type="text"
            id="shared-by"
            bind:value={sharedBy}
            placeholder="Person who shared this"
          />
        </div>
      </div>
      <div class="form-group">
        <label for="tags">Tags</label><input
          type="text"
          id="tags"
          bind:value={tags}
          placeholder="Comma-separated tags"
        />
      </div>
      <div class="form-group">
        <label for="content">Content</label><textarea
          id="content"
          bind:value={content}
          placeholder="Optional notes or content..."
          rows="6"
        ></textarea>
      </div>
      <div class="form-actions">
        <button
          type="button"
          class="cancel-btn"
          on:click={close}>Cancel</button
        ><button type="submit" class="submit-btn" disabled={submitting}
          >{submitting ? "Creating…" : "Create phantasia"}</button
        >
      </div>
    </form>
  </div>
</div>

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: var(--z-bottom-sheet);
    display: grid;
    place-items: center;
    padding: 1rem;
    background: color-mix(in srgb, var(--dox-ink-950) 65%, transparent);
  }
  .modal {
    width: min(100%, 34rem);
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    background: var(--dox-surface);
    border: 1px solid var(--dox-rule-strong);
    border-radius: var(--dox-radius);
    box-shadow: var(--dox-shadow);
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--dox-rule);
  }
  .eyebrow {
    margin: 0 0 0.25rem;
    color: var(--dox-text-muted);
    font: 0.65rem var(--dox-font-mono);
    letter-spacing: var(--dox-tracking-caps);
    text-transform: uppercase;
  }
  h2 {
    margin: 0;
    color: var(--dox-text-primary);
    font: 600 1.15rem var(--dox-font-display);
  }
  button,
  input,
  textarea {
    font: inherit;
  }
  .close-btn {
    width: 36px;
    min-height: 36px;
    background: transparent;
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-primary);
    cursor: pointer;
    font-size: 1.3rem;
  }
  .close-btn:hover {
    background: var(--dox-surface-raised);
  }
  form {
    padding: 1.25rem;
  }
  .error {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1rem;
    padding: 0.75rem;
    background: var(--dox-status-running);
    border: 1px solid var(--dox-status-running);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-on-running);
    font-size: 0.85rem;
  }
  .error span {
    display: grid;
    place-items: center;
    width: 1rem;
    height: 1rem;
    border: 1px solid currentColor;
    border-radius: 50%;
    font-weight: 700;
  }
  .form-group {
    margin-bottom: 1rem;
  }
  .form-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }
  label {
    display: block;
    margin-bottom: 0.35rem;
    color: var(--dox-text-secondary);
    font: 0.78rem var(--dox-font-mono);
  }
  .required {
    color: var(--dox-text-secondary);
    font-weight: 700;
  }
  input,
  textarea {
    width: 100%;
    padding: 0.65rem 0.75rem;
    background: var(--dox-ground);
    border: 1px solid var(--dox-rule-strong);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-primary);
    font-size: 0.9rem;
  }
  input:focus,
  textarea:focus {
    border-color: var(--dox-focus);
    outline: 2px solid var(--dox-focus);
    outline-offset: 2px;
  }
  input::placeholder,
  textarea::placeholder {
    color: var(--dox-text-muted);
    opacity: 1;
  }
  textarea {
    min-height: 7rem;
    resize: vertical;
  }
  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-top: 1.5rem;
    padding-top: 1rem;
    border-top: 1px solid var(--dox-rule);
  }
  .cancel-btn,
  .submit-btn {
    min-height: 38px;
    padding: 0.5rem 1rem;
    border-radius: var(--dox-radius-sm);
    cursor: pointer;
    font: 600 0.8rem var(--dox-font-mono);
  }
  .cancel-btn {
    background: transparent;
    border: 1px solid var(--dox-rule-strong);
    color: var(--dox-text-secondary);
  }
  .cancel-btn:hover {
    background: var(--dox-surface-raised);
  }
  .submit-btn {
    background: var(--dox-status-running);
    border: 1px solid var(--dox-status-running);
    color: var(--dox-text-on-running);
  }
  .submit-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  @media (max-width: 768px) {
    .modal-backdrop {
      align-items: end;
      padding: 0;
    }
    .modal {
      width: 100%;
      max-height: min(88vh, 46rem);
      border-radius: var(--dox-radius) var(--dox-radius) 0 0;
    }
    .close-btn,
    .cancel-btn,
    .submit-btn,
    input {
      min-height: var(--touch-target-min);
    }
    .close-btn {
      min-width: var(--touch-target-min);
    }
    .form-row {
      grid-template-columns: 1fr;
      gap: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    * {
      scroll-behavior: auto;
    }
  }
</style>
