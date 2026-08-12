# History delete + iframe load speed

Date: 2026-08-12
Scope: webapp (Flask on port 9997) + history persistence

## Problem

Two UX issues in the webapp sidebar/preview:

1. **No delete button on history entries.** Once a preview is generated, the only way to remove it from history is to delete the file by hand or reset the `_data/history.json` — awkward for the user.

2. **Clicking a history entry is slow to load on the right.** Each `/api/history/<id>` returns ~1.7 MB of JSON (HTML with base64-embedded images). The browser must parse the JSON, render the iframe srcdoc, and base64-decode 3 images. First-click is ~1–2 s; rerenders are tainted by the same cost.

## Goal

- Add a delete control per history entry (with `confirm()` gate).
- Make history clicks near-instant by serving the iframe HTML from a real URL with HTTP caching, instead of stuffing 1.7 MB of base64 into `frame.srcdoc`.

## Approach

### 1. New endpoints

```
GET    /api/history/<id>/html          text/html — themed HTML with relative image paths
GET    /api/history/<id>/images/<name> image bytes (Content-Type derived from extension)
DELETE /api/history/<id>               → {ok: true, deleted: <id>}
```

- `/api/history/<id>/html` reads `workdir/article.html`, injects the bootstrap CSS (the `data-ws-bootstrap` block already in `render.py`), and returns it. Image tags in the HTML stay as `<img src="images/cover.jpg">` so they resolve relative to `/api/history/<id>/html`.
- `/api/history/<id>/images/<name>` streams the file from `workdir/images/<name>` with the right MIME type. Used by the iframe in parallel with the HTML.

### 2. Stop stuffing HTML into history.json

- `history.add()` no longer writes an `html` field. The history JSON keeps `id, created_at, topic_*, theme, workdir, image_mode` — roughly 1 KB per entry instead of 1.7 MB.
- `api_preview` no longer returns `html` in its response. It returns `{ok, history_id, html_url, image_mode, topic, theme}` where `html_url = "/api/history/<id>/html"`.
- `api_history_get` returns `{ok, entry: <metadata>, html_url}` (no html).
- `api_history_list` already strips html — no change.

The existing `_embed_images_as_data_uris` path in `render.py` is kept (still needed by publish? no — publish reads from disk) **actually removed**. Inline data-URI embedding is no longer needed for the iframe path. The publish path (`cli.py publish`) already reads from disk, so it doesn't need data URIs. We can delete the embedding function.

Wait — re-check: does `cli.py publish` actually need data URIs? No, it reads `article.md` from disk and uploads from disk. So we can drop the embedding entirely.

### 3. Frontend — switch iframe to `src`-based loading

```javascript
function setPreview(htmlUrl, restoreScroll) {
  frame.style.display = 'block';
  empty.style.display = 'none';
  frame.src = htmlUrl;          // was: frame.srcdoc = html
  // restore-scroll logic unchanged (same-origin so contentDocument still readable)
}
```

Both `loadHistoryEntry` and `doPreview` call `setPreview(data.html_url, restoreOrUndefined)`. The previous save/restore-scroll-on-same-history behavior carries over unchanged.

### 4. Delete button

- Each `.history-item` gets a small `×` button at the top right.
- Click → `confirm("确认删除历史 #N ？")` → `DELETE /api/history/<id>`.
- On success: `refreshHistory()`. If the deleted entry was the active preview, call `clearPreview()` and disable publish.
- Server-side: `history.delete(entry_id)` removes the entry from `_entries` and the JSON file. Also deletes the workdir at `workdir` to free disk. If the directory is already gone, ignore the error.

### 5. Cache headers

- `/api/history/<id>/html`: `Cache-Control: private, max-age=3600` (the HTML for a history entry is immutable — it never changes).
- `/api/history/<id>/images/<name>`: `Cache-Control: private, max-age=86400` (images are even more stable).
- Since the URLs include the history_id, no cache-busting needed.

## Data flow

### Preview (immediate)

```
[POST /api/preview {topic_id, theme}]
  → write_article → 写 workdir/article.md
  → generate_images → 写 workdir/images/{cover,inline-1,inline-2}.jpg
  → render_preview_html → 写 workdir/article.html (full themed HTML with relative paths)
  → history.add({topic_*, theme, workdir, image_mode})  # no html
  → 200 {history_id, html_url, image_mode, topic, theme}
```

Frontend: `frame.src = html_url`.

### History click

```
[GET /api/history/<id>]
  → history.get(id)
  → 200 {entry: <metadata>, html_url}
```

Frontend: `frame.src = html_url`.

### iframe loads from URL

```
[/api/history/<id>/html]  →  text/html (~50 KB)
[/api/history/<id>/images/cover.jpg]    →  image/jpeg (parallel)
[/api/history/<id>/images/inline-1.jpg] →  image/jpeg (parallel)
[/api/history/<id>/images/inline-2.jpg] →  image/jpeg (parallel)
```

Browser fetches HTML first, then issues parallel image requests. HTTP cache makes repeat clicks instant.

### Delete

```
[DELETE /api/history/<id>]
  → history.delete(id)            # removes from _entries + JSON
  → shutil.rmtree(workdir)        # frees disk
  → 200 {ok: true, deleted: id}
```

Frontend: `refreshHistory()` then maybe `clearPreview()`.

## Files changed

- `webapp/history.py` — add `delete(entry_id)`; remove `html` from `add()` payload.
- `webapp/app.py` — change `api_preview` response shape; add `api_history_html`, `api_history_image`, `api_history_delete`; cache headers.
- `webapp/render.py` — drop `_embed_images_as_data_uris` (no longer needed); keep `_inject_iframe_bootstrap` (called from new `api_history_html`).
- `webapp/templates/index.html` — `setPreview` takes a URL; add delete button per history item; render `.delete-btn` with hover style.

## Out of scope

- Cross-history scroll persistence (remember where the user was in history A when they click B). Same-history restore stays.
- Bulk delete (select-multiple). One-at-a-time is enough for now.
- Image size optimization (cover.jpg is already 1024px wide; further downscale is a separate concern).
- Publish-path changes — `cli.py publish` is unchanged; it already reads from disk.

## Success criteria

- First click on a history entry: iframe shows text within ~200 ms; images stream in over the next ~500 ms.
- Repeat click on the same entry: iframe shows content within ~50 ms (browser cache).
- Delete: clicking × + confirm removes the entry from the sidebar within ~200 ms; the workdir is gone from disk.
- `webapp/_data/history.json` stays under ~10 KB regardless of how many previews exist.
- All existing 29 unit tests still pass.
