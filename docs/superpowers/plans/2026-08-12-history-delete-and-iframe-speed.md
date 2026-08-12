# History Delete + Iframe Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the left-sidebar history clickable to load near-instantly, and add a delete button per history entry.

**Architecture:** Stop stuffing 1.7 MB of base64-embedded HTML into `frame.srcdoc`. Instead, serve the iframe via a real URL (`/api/history/<id>/html`) with images fetched in parallel from `/api/history/<id>/images/<name>`. Browser HTTP caching makes repeat clicks instant. History entries drop from ~1.7 MB to ~1 KB by removing the `html` field.

**Tech Stack:** Flask + gunicorn (existing), Python 3.11, no new dependencies.

## Global Constraints

- All code paths must keep the existing 29 unit tests passing (`pytest tests/`).
- `webapp/_data/history.json` is bind-mounted and persists across container restarts — never delete it casually.
- The bootstrap CSS rule (`img{max-width:100%;height:auto;display:block;margin:16px auto;border-radius:6px}`) must continue to apply to the iframe content.
- Sandbox attribute on the iframe stays `sandbox="allow-same-origin"` (we need same-origin read access to scrollTop).
- This is a single-component change (the webapp). No other packages or skills are touched.
- `webapp/_data/workdirs/<uuid>/` stores `article.md`, `article.html`, `images/{cover,inline-1,inline-2}.jpg` — these are the source of truth for the new HTML/image endpoints.

---

## File Structure

Files modified by this plan:

- `webapp/history.py` — add `delete(entry_id)`; drop `html` from `add()` payload.
- `webapp/app.py` — change `api_preview` and `api_history_get` responses; add three new endpoints (`api_history_html`, `api_history_image`, `api_history_delete`).
- `webapp/render.py` — drop `_embed_images_as_data_uris` (no longer needed); keep `_inject_iframe_bootstrap` (called from new endpoint).
- `webapp/templates/index.html` — `setPreview` takes a URL not HTML; add delete button per history item.
- `tests/test_webapp_history.py` (new) — unit tests for `history.delete()` and the slimmed `history.add()`.

---

## Task 1: `history.delete()` + slim `history.add()` (no html)

**Files:**
- Modify: `webapp/history.py:73-86` (replace `add` body) and append `delete`
- Create: `tests/test_webapp_history.py`

**Interfaces:**
- `history.add(entry: Dict[str, Any]) -> int` — no longer expects an `html` key (just metadata + workdir).
- `history.delete(entry_id: int) -> bool` — returns True if entry was deleted, False if not found.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_webapp_history.py
import json
import pytest
from pathlib import Path

from webapp import history


@pytest.fixture
def tmp_history_file(tmp_path, monkeypatch):
    """Point history module at a temp file so tests don't touch the real one."""
    f = tmp_path / "history.json"
    monkeypatch.setattr(history, "_HISTORY_FILE", f)
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    history._entries.clear()
    history._next_id = 1
    yield f
    history._entries.clear()
    history._next_id = 1


def test_add_does_not_persist_html_field(tmp_history_file):
    eid = history.add({
        "topic_id": "kb-001",
        "title": "幸存者偏差",
        "theme": "terracotta",
        "workdir": "/tmp/x",
        "image_mode": "real",
        "html": "<huge base64 blob>",  # caller might still pass it; add() must drop it
    })
    raw = json.loads(tmp_history_file.read_text())
    entry = raw["entries"][0]
    assert entry["id"] == eid
    assert "html" not in entry, "history must not persist html (1.7MB bloat)"


def test_delete_returns_true_and_removes_entry(tmp_history_file):
    a = history.add({"topic_id": "kb-001", "title": "x", "workdir": "/tmp/a"})
    b = history.add({"topic_id": "kb-002", "title": "y", "workdir": "/tmp/b"})
    assert history.delete(a) is True
    raw = json.loads(tmp_history_file.read_text())
    ids = [e["id"] for e in raw["entries"]]
    assert ids == [b]


def test_delete_unknown_id_returns_false(tmp_history_file):
    history.add({"topic_id": "kb-001", "title": "x", "workdir": "/tmp/a"})
    assert history.delete(999) is False
    assert len(history.list_entries()) == 1


def test_delete_decrements_next_id_via_load(tmp_history_file):
    history.add({"topic_id": "kb-001", "title": "x", "workdir": "/tmp/a"})
    history.add({"topic_id": "kb-002", "title": "y", "workdir": "/tmp/b"})
    raw = json.loads(tmp_history_file.read_text())
    saved_next_id = raw["next_id"]
    history._entries.clear()
    history._next_id = 1
    history.delete(1)
    # reload should pick up the saved next_id so new adds don't collide
    raw2 = json.loads(tmp_history_file.read_text())
    assert raw2["next_id"] == saved_next_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_webapp_history.py -v`
Expected: 4 failures with `AttributeError` (delete doesn't exist) or assertion on `html in entry`.

- [ ] **Step 3: Update `history.py` — drop html from `add`, add `delete()`**

Replace `add()` body to filter out `html` (and any other large blob fields), and append `delete()`:

```python
# webapp/history.py — replace the add() body
def add(entry: Dict[str, Any]) -> int:
    """Add a new history entry. Trims to _MAX_ENTRIES oldest-first.

    The ``html`` field is stripped here — it lived as a 1.7 MB blob in
    history.json and forced every /api/history/<id> response to ferry
    a base64-embedded iframe through JSON. The iframe now loads from
    /api/history/<id>/html instead.
    """
    global _next_id
    with _lock:
        _load()
        clean = {k: v for k, v in entry.items() if k != "html"}
        new_entry = {"id": _next_id, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                     **clean}
        _next_id += 1
        _entries.append(new_entry)
        while len(_entries) > _MAX_ENTRIES:
            _entries.pop(0)
        _save()
        return new_entry["id"]


def delete(entry_id: int) -> bool:
    """Remove an entry by id. Returns True if it existed, False otherwise."""
    global _next_id
    with _lock:
        _load()
        before = len(_entries)
        _entries = [e for e in _entries if e["id"] != entry_id]
        if len(_entries) == before:
            return False
        _save()
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_webapp_history.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add webapp/history.py tests/test_webapp_history.py
git commit -m "feat(webapp): history.delete() + drop html from entries"

# Stop the running container first so the import in subsequent steps
# picks up changes:
docker compose -f /root/.openclaw/workspace/skills/wechat-studio/docker-compose.yml restart wechat-studio-web
```

---

## Task 2: New Flask endpoints — html, image, delete

**Files:**
- Modify: `webapp/app.py` — add `api_history_html`, `api_history_image`, `api_history_delete`; modify `api_preview` and `api_history_get` to drop html and add `html_url`.

**Interfaces:**
- `api_preview` response: `{ok, history_id, html_url, image_mode, topic, theme}` (no html in body)
- `api_history_get` response: `{ok, entry, html_url}` (no html in entry)
- `GET /api/history/<id>/html` → `text/html` response (raw HTML with bootstrap CSS injected)
- `GET /api/history/<id>/images/<name>` → image bytes with correct MIME
- `DELETE /api/history/<id>` → `{ok, deleted: id}`

- [ ] **Step 1: Modify `api_preview` to drop html and add html_url**

In `webapp/app.py:256-269`, replace the response dict:

```python
    entry_id = history.add({
        "topic_id": topic.get("id"),
        "title": topic.get("title", ""),
        "category": topic.get("category", ""),
        "theme": theme,
        "workdir": str(workdir),
        "image_mode": image_mode,
    })
    log.info("preview %s → history #%d (%s, %d chars HTML)",
             topic_id, entry_id, image_mode, len(html))

    return jsonify(
        {
            "ok": True,
            "history_id": entry_id,
            "html_url": f"/api/history/{entry_id}/html",
            "image_mode": image_mode,
            "topic": {
                "id": topic.get("id"),
                "title": topic.get("title"),
                "category": topic.get("category"),
            },
            "theme": theme,
        }
    )
```

- [ ] **Step 2: Modify `api_history_get` to drop html and add html_url**

In `webapp/app.py:287-293`, replace the response:

```python
@app.route("/api/history/<int:entry_id>", methods=["GET"])
def api_history_get(entry_id: int):
    """Return entry metadata + iframe URL (no html — too big to ship in JSON)."""
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    return jsonify(
        {
            "ok": True,
            "entry": entry,
            "html_url": f"/api/history/{entry_id}/html",
        }
    )
```

- [ ] **Step 3: Add `api_history_html` endpoint**

Append after `api_history_get`:

```python
# MIME types for /api/history/<id>/images/
_HISTORY_IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif",
}


@app.route("/api/history/<int:entry_id>/html", methods=["GET"])
def api_history_html(entry_id: int):
    """Serve the themed HTML for iframe.src.

    The HTML has relative <img src="images/cover.jpg"> references that
    resolve to /api/history/<id>/images/cover.jpg via the iframe's base URL.
    Cache-Control: private, max-age=3600 — the file is immutable for a given
    history_id (preview never re-renders the same id).
    """
    from .render import _inject_iframe_bootstrap  # late import — avoids circulars

    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    html_path = Path(entry["workdir"]) / "article.html"
    if not html_path.exists():
        return jsonify({"ok": False, "error": "article.html 已丢失",
                        "phase": "session"}), 410
    html = _inject_iframe_bootstrap(html_path.read_text(encoding="utf-8"))
    resp = Response(html, mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.route("/api/history/<int:entry_id>/images/<path:name>", methods=["GET"])
def api_history_image(entry_id: int, name: str):
    """Serve an image file from the workdir's images/ subdirectory.

    Rejects path-traversal: name must be a single segment without '/'.
    """
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    # Block path traversal: only accept a single filename, no slashes/dots.
    if "/" in name or ".." in name or name.startswith("."):
        return jsonify({"error": "bad image name"}), 400
    img_path = (Path(entry["workdir"]) / "images" / name).resolve()
    images_dir = (Path(entry["workdir"]) / "images").resolve()
    if not str(img_path).startswith(str(images_dir) + "/"):
        return jsonify({"error": "path escape"}), 400
    if not img_path.is_file():
        return jsonify({"error": "image not found"}), 404
    ext = img_path.suffix.lower()
    mime = _HISTORY_IMAGE_MIME.get(ext, "application/octet-stream")
    data = img_path.read_bytes()
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp
```

Add `Response` to the import line at the top of `webapp/app.py`:

```python
from flask import Flask, Response, jsonify, redirect, render_template, request
```

- [ ] **Step 4: Add `api_history_delete` endpoint**

Append after `api_history_image`:

```python
@app.route("/api/history/<int:entry_id>", methods=["DELETE"])
def api_history_delete(entry_id: int):
    """Delete a history entry and its workdir.

    The workdir is bind-mounted disk content — we own it and can free it.
    If the directory is already gone (cleanup is idempotent), that's fine.
    """
    import shutil

    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    history.delete(entry_id)
    workdir = entry.get("workdir")
    if workdir:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError as e:
            log.warning("failed to remove workdir %s: %s", workdir, e)
    log.info("deleted history #%d (workdir=%s)", entry_id, workdir)
    return jsonify({"ok": True, "deleted": entry_id})
```

- [ ] **Step 5: Restart, smoke-test the new endpoints**

Run:

```bash
docker compose -f /root/.openclaw/workspace/skills/wechat-studio/docker-compose.yml restart wechat-studio-web
sleep 3
curl -s http://localhost:9997/api/health
```

Expected: `{"ok": true, "app": "wechat-studio", "version": "1.3.0", ...}` — server is up.

```bash
# Login cookie
curl -s -c /tmp/ws-cookie -b /tmp/ws-cookie -X POST http://localhost:9997/login \
  -d "password=asdf123456" -o /dev/null

# List history, pick the most recent entry id
HIST_ID=$(curl -s -b /tmp/ws-cookie http://localhost:9997/api/history \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['entries'][0]['id'])")
echo "history_id: $HIST_ID"

# 1. /api/history/<id> no longer carries html
curl -s -b /tmp/ws-cookie http://localhost:9997/api/history/$HIST_ID \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'html' not in d['entry']; assert 'html_url' in d; print('no html ✓ html_url=', d['html_url'])"

# 2. /api/history/<id>/html returns themed HTML
curl -s -b /tmp/ws-cookie -D /tmp/hdrs.txt http://localhost:9997/api/history/$HIST_ID/html -o /tmp/h.html
grep -i "Cache-Control" /tmp/hdrs.txt
grep -c "data-ws-bootstrap" /tmp/h.html
grep -c "max-width: 100%" /tmp/h.html
ls -la /tmp/h.html

# 3. /api/history/<id>/images/cover.jpg returns image bytes
curl -s -b /tmp/ws-cookie -D /tmp/imghdrs.txt http://localhost:9997/api/history/$HIST_ID/images/cover.jpg -o /tmp/c.jpg
grep -i "Content-Type" /tmp/imghdrs.txt
file /tmp/c.jpg

# 4. Path traversal is blocked
curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/ws-cookie \
  http://localhost:9997/api/history/$HIST_ID/images/../article.html
# Expected: 400
```

Expected: 4 successful checks. The /html endpoint returns HTML with `data-ws-bootstrap` marker and `max-width: 100%` rule, sized ~50 KB. The image endpoint returns valid JPEG with `image/jpeg` Content-Type.

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py
git commit -m "feat(webapp): serve iframe via /api/history/<id>/html + delete endpoint"
```

---

## Task 3: Frontend — switch iframe to `src`-based loading

**Files:**
- Modify: `webapp/templates/index.html:322-357` (`setPreview` + scroll helpers), `428-440` (loadHistoryEntry), `482` (doPreview)

**Interfaces:**
- `setPreview(htmlUrl, restoreScroll)` — `htmlUrl` is now a URL string, not HTML. Sets `frame.src = htmlUrl` instead of `frame.srcdoc = html`. Save/restore-scroll logic unchanged.

- [ ] **Step 1: Update `setPreview` to use `src` instead of `srcdoc`**

In `webapp/templates/index.html:322-344`, replace `setPreview`:

```javascript
function setPreview(htmlUrl, restoreScroll) {
      frame.style.display = 'block';
      empty.style.display = 'none';
      frame.src = htmlUrl;          // was: frame.srcdoc = html
      if (restoreScroll !== undefined) {
        frame.onload = () => {
          writeIframeScroll(restoreScroll);
          frame.onload = null;
        };
        setTimeout(() => {
          if (frame.onload) {
            writeIframeScroll(restoreScroll);
            frame.onload = null;
          }
        }, 50);
      } else {
        frame.onload = null;
      }
    }
```

The `readIframeScroll` and `writeIframeScroll` helpers below it stay unchanged.

- [ ] **Step 2: Update `loadHistoryEntry` to use `data.html_url`**

In `webapp/templates/index.html`, find the `loadHistoryEntry` function and replace the `setPreview(e.html, restore)` call (around line 436):

```javascript
        const e = data.entry;
        const prevId = currentPreview ? currentPreview.history_id : null;
        currentPreview = {
          history_id: e.id,
          topic: {id: e.topic_id, title: e.title, category: e.category},
          theme: e.theme,
          html_url: data.html_url,
          image_mode: e.image_mode,
        };
        const restore = prevId === e.id ? readIframeScroll() : 0;
        setPreview(data.html_url, restore);
        setMeta(currentPreview);
```

- [ ] **Step 3: Update `doPreview` to use `data.html_url`**

In `webapp/templates/index.html`, find the `doPreview` function and replace the `setPreview(data.html)` call (around line 482):

```javascript
        currentPreview = {
          history_id: data.history_id,
          topic: data.topic,
          theme: data.theme,
          html_url: data.html_url,
          image_mode: data.image_mode,
        };
        setPreview(data.html_url, undefined);  // reset scroll on new preview
        setMeta(currentPreview);
```

- [ ] **Step 4: Restart and verify the iframe loads via src**

```bash
docker compose -f /root/.openclaw/workspace/skills/wechat-studio/docker-compose.yml restart wechat-studio-web
sleep 3
curl -s http://localhost:9997/api/health
```

Then in a browser (or via curl with cookies — won't render but you can confirm the API shape):

```bash
# Login
curl -s -c /tmp/ws-cookie -b /tmp/ws-cookie -X POST http://localhost:9997/login \
  -d "password=asdf123456" -o /dev/null

# Click an existing history entry
HIST_ID=$(curl -s -b /tmp/ws-cookie http://localhost:9997/api/history \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['entries'][0]['id'])")
curl -s -b /tmp/ws-cookie http://localhost:9997/api/history/$HIST_ID \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('html_url:', d['html_url']); print('keys:', sorted(d.keys()))"
```

Expected: `html_url: /api/history/<id>/html` and entry has no `html` field.

- [ ] **Step 5: Commit**

```bash
git add webapp/templates/index.html
git commit -m "feat(webapp): iframe src-based loading via /api/history/<id>/html"
```

---

## Task 4: Frontend — delete button per history entry

**Files:**
- Modify: `webapp/templates/index.html` — add `.delete-btn` CSS, render the button in `renderHistory()`, add delete handler.

**Interfaces:**
- Click `×` on a history item → `confirm("确认删除历史 #N?")` → `DELETE /api/history/<id>` → `refreshHistory()` → clear preview if it was the active one.

- [ ] **Step 1: Add CSS for the delete button**

In `webapp/templates/index.html` `<style>` block, after the `.history-item .badge.placeholder` rule (around line 218), add:

```css
  .history-item .delete-btn {
    position: absolute;
    top: 4px;
    right: 6px;
    background: transparent;
    border: none;
    color: var(--text-3);
    font-size: 14px;
    line-height: 1;
    padding: 2px 6px;
    border-radius: 4px;
    cursor: pointer;
    opacity: 0.6;
    transition: all 0.15s;
  }
  .history-item { position: relative; }
  .history-item .delete-btn:hover {
    color: var(--danger);
    background: rgba(248, 113, 113, 0.12);
    opacity: 1;
  }
```

- [ ] **Step 2: Render the delete button in `renderHistory()`**

In `webapp/templates/index.html`, find the `renderHistory(entries)` function and modify the `div.innerHTML` to include the button. Replace the innerHTML assignment:

```javascript
        div.innerHTML =
          '<div class="id-row">' +
            '<span class="hid">#' + e.id + '</span>' +
            imageModeBadge(e.image_mode) +
          '</div>' +
          '<div class="title">' + (e.title || e.topic_id) + '</div>' +
          '<div class="meta">' +
            (e.topic_id || '') + ' · ' + (e.theme || '') + ' · ' +
            (e.created_at || '') +
          '</div>' +
          '<button class="delete-btn" data-id="' + e.id + '" title="删除">×</button>';
```

- [ ] **Step 3: Wire the delete-button click (stop propagation)**

Find the `div.addEventListener('click', () => loadHistoryEntry(e.id));` line in `renderHistory` and add a delete handler that runs BEFORE the body click:

```javascript
        div.querySelector('.delete-btn').addEventListener('click', (ev) => {
          ev.stopPropagation();
          deleteHistory(e.id);
        });
        div.addEventListener('click', () => loadHistoryEntry(e.id));
```

- [ ] **Step 4: Add the `deleteHistory` function**

Insert this function right after `loadHistoryEntry` (around line 450):

```javascript
    async function deleteHistory(id) {
      if (!confirm('确认删除历史 #' + id + '？')) return;
      try {
        const resp = await fetch('/api/history/' + id, { method: 'DELETE' });
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
          showStatus('error', '删除失败：' + (data.error || resp.status));
          return;
        }
        if (currentPreview && currentPreview.history_id === id) {
          clearPreview();
          currentPreview = null;
          btnPublish.disabled = true;
          metaEl.innerHTML = '&nbsp;';
        }
        await refreshHistory();
      } catch (e) {
        showStatus('error', '请求失败：' + (e && e.message ? e.message : e));
      }
    }
```

- [ ] **Step 5: Restart, manually verify the delete UX**

```bash
docker compose -f /root/.openclaw/workspace/skills/wechat-studio/docker-compose.yml restart wechat-studio-web
sleep 3
```

In the browser:
1. Load the page — see history list with × on each entry.
2. Click × on an entry — confirm dialog appears.
3. Confirm — entry disappears, workdir is gone from disk.

Verify on disk:

```bash
# Pick an entry to delete
HIST_ID=$(curl -s -b /tmp/ws-cookie http://localhost:9997/api/history \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['entries'][0]['id'])")
WORKDIR=$(curl -s -b /tmp/ws-cookie http://localhost:9997/api/history/$HIST_ID \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['entry']['workdir'])")
echo "before: $WORKDIR exists? $(test -d "$WORKDIR" && echo y || echo n)"

# Delete via API
curl -s -b /tmp/ws-cookie -X DELETE http://localhost:9997/api/history/$HIST_ID
echo "after: $WORKDIR exists? $(test -d "$WORKDIR" && echo y || echo n)"
```

Expected: `before: y` then `{"ok": true, "deleted": $HIST_ID}` then `after: n`.

- [ ] **Step 6: Commit**

```bash
git add webapp/templates/index.html
git commit -m "feat(webapp): delete button per history entry with confirm()"
```

---

## Task 5: Drop `_embed_images_as_data_uris` from `render.py`

**Files:**
- Modify: `webapp/render.py` — remove `_embed_images_as_data_uris` and the `_IMG_TAG_RE` / `_MIME_FOR_EX` constants. Remove the call site in `render_preview_html`.

**Interfaces:**
- `render_preview_html(workdir, theme) -> str` — still returns HTML but no longer base64-encodes images. The function is now only called by `api_publish` indirectly (via `cli.py preview`) — the iframe loads from `/api/history/<id>/html` which reads `workdir/article.html` directly.

- [ ] **Step 1: Verify nothing else calls `_embed_images_as_data_uris`**

Run:

```bash
grep -rn "_embed_images_as_data_uris" /root/.openclaw/workspace/skills/wechat-studio
```

Expected: only the definition in `webapp/render.py` and the call site in `render_preview_html`. No other consumers.

- [ ] **Step 2: Remove the function and constants from `render.py`**

Delete these lines from `webapp/render.py`:

```python
# ── 把图片 src 替换成 data URI（给 iframe srcdoc 用）────────────────────
_IMG_TAG_RE = re.compile(...)  # delete
_MIME_FOR_EX = {...}  # delete
def _embed_images_as_data_uris(...):  # delete
    ...
```

And in `render_preview_html`, remove the `_embed_images_as_data_uris(html, workdir)` call (the function now returns `html` directly).

Replace the tail of `render_preview_html`:

```python
    html = html_file.read_text(encoding="utf-8")
    html = _inject_iframe_bootstrap(html)
    return html
```

Note: `render_preview_html` is now only called from `api_history_html` (which already uses `_inject_iframe_bootstrap` directly). Actually wait — re-check. Looking at `webapp/app.py`, `render_preview_html` is imported and called in `api_preview`. Since `api_preview` no longer needs the HTML in its response, we drop the call entirely.

Replace `api_preview` so it never calls `render_preview_html`:

```python
    try:
        image_mode = generate_images_in_workdir(workdir, topic, image_rels)
    except Exception as e:
        log.error("image generation hard-failed: %s", e)
        return jsonify({"ok": False, "error": f"图片生成失败：{e}",
                        "phase": "images"}), 500

    # cli.py preview writes article.html into the workdir. The iframe loads
    # from /api/history/<id>/html so we don't need the HTML in this response.
    try:
        _run_cli_inline(workdir, theme)  # see Step 3
    except Exception as e:
        log.error("preview render failed: %s", e)
        return jsonify({"ok": False, "error": f"预览渲染失败：{e}",
                        "phase": "render"}), 500
```

Wait — actually, `render_preview_html` is what runs cli.py. We still need to run cli.py preview to produce `article.html`. Let me re-check.

In `render_preview_html`, the function:
1. Calls `cli.py preview` via subprocess to produce `workdir/article.html`
2. Reads it
3. Calls `_embed_images_as_data_uris` (now removed)
4. Returns the HTML

The cli.py preview step is necessary — that's what produces the themed HTML from the markdown. We still need to run it (so the file exists for `/api/history/<id>/html` to serve). But we don't need to read+return the HTML.

Refactor: rename `render_preview_html` to `_write_preview_html` and have it just run cli.py and write the file. The return value is no longer used.

```python
def _write_preview_html(workdir: Path, theme: str) -> None:
    """Run cli.py preview on article.md, producing article.html in workdir.

    The iframe loads this directly via /api/history/<id>/html, so we don't
    return the HTML — we just need to make sure the file exists.
    """
    md_file = workdir / "article.md"
    html_file = workdir / "article.html"
    proc = subprocess.run(
        [
            sys.executable,
            str(TOOLKIT_DIR / "cli.py"),
            "preview",
            str(md_file),
            "--theme",
            theme,
            "--no-open",
            "-o",
            str(html_file),
        ],
        cwd=str(SKILL_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or not html_file.exists():
        raise RuntimeError(
            f"cli.py preview 失败 (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
```

Importantly — note that `webapp/render.py` is also imported by `scripts/write_article.py` paths? Let me check. Actually `render.py` is only imported by `webapp/app.py`. Safe to refactor.

Update `api_preview` to call `_write_preview_html(workdir, theme)` instead of `render_preview_html(workdir, theme)`. Drop the `html = ...` variable.

- [ ] **Step 3: Update `api_preview` to use `_write_preview_html`**

In `webapp/app.py`, change the import and the call:

```python
from .render import (
    _write_preview_html,  # was: render_preview_html
    generate_images_in_workdir,
    write_article_to_workdir,
)
```

And update the `api_preview` block accordingly:

```python
    try:
        image_mode = generate_images_in_workdir(workdir, topic, image_rels)
    except Exception as e:
        log.error("image generation hard-failed: %s", e)
        return jsonify({"ok": False, "error": f"图片生成失败：{e}",
                        "phase": "images"}), 500

    try:
        _write_preview_html(workdir, theme)
    except Exception as e:
        log.error("preview render failed: %s", e)
        return jsonify({"ok": False, "error": f"预览渲染失败：{e}",
                        "phase": "render"}), 500
```

- [ ] **Step 4: Run unit tests + curl smoke**

```bash
pytest tests/ -v
```

Expected: 33 passed (29 existing + 4 new from Task 1).

```bash
docker compose -f /root/.openclaw/workspace/skills/wechat-studio/docker-compose.yml restart wechat-studio-web
sleep 3
curl -s -c /tmp/ws-cookie -b /tmp/ws-cookie -X POST http://localhost:9997/login \
  -d "password=asdf123456" -o /dev/null
# Trigger a fresh preview and confirm it works end-to-end
curl -s -b /tmp/ws-cookie -X POST http://localhost:9997/api/preview \
  -H "Content-Type: application/json" \
  -d '{"topic_id":"kb-003","theme":"terracotta"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('ok:', d.get('ok'), 'html_url:', d.get('html_url'))"
```

Expected: `ok: True html_url: /api/history/<id>/html`.

- [ ] **Step 5: Commit**

```bash
git add webapp/render.py webapp/app.py
git commit -m "refactor(webapp): drop data-URI embedding, return URL from preview"
```

---

## Task 6: End-to-end verification

**Files:** none (pure verification)

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: 33 passed, 0 failed.

- [ ] **Step 2: Curl-driven end-to-end check**

```bash
# Health
curl -s http://localhost:9997/api/health

# Login
curl -s -c /tmp/ws-cookie -b /tmp/ws-cookie -X POST http://localhost:9997/login \
  -d "password=asdf123456" -o /dev/null

# Trigger a preview
TOPIC_ID=kb-002
RESP=$(curl -s -b /tmp/ws-cookie -X POST http://localhost:9997/api/preview \
  -H "Content-Type: application/json" \
  -d "{\"topic_id\":\"$TOPIC_ID\",\"theme\":\"terracotta\"}")
echo "$RESP" | python3 -m json.tool
HIST_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['history_id'])")
HTML_URL=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['html_url'])")

# Verify the HTML URL serves the iframe
curl -s -b /tmp/ws-cookie http://localhost:9997$HTML_URL -o /tmp/h.html
ls -la /tmp/h.html
grep -c "data-ws-bootstrap" /tmp/h.html
grep -c "max-width: 100%" /tmp/h.html

# Verify images load
curl -s -b /tmp/ws-cookie http://localhost:9997$HTML_URL/images/cover.jpg -o /tmp/c.jpg
file /tmp/c.jpg

# Verify history.json is small
ls -la /root/.openclaw/workspace/skills/wechat-studio/webapp/_data/history.json

# Verify delete works
curl -s -b /tmp/ws-cookie -X DELETE http://localhost:9997/api/history/$HIST_ID
curl -s -b /tmp/ws-cookie http://localhost:9997/api/history/$HIST_ID
```

Expected:
- `/api/preview` returns `{ok: True, html_url: "/api/history/<id>/html", ...}` (no `html` key in response).
- `<html_url>` returns ~50 KB HTML with `data-ws-bootstrap` and `max-width: 100%` markers.
- `/images/cover.jpg` returns valid JPEG.
- `history.json` is under 10 KB.
- DELETE returns `{ok: true, deleted: <id>}`.
- Subsequent GET on the deleted id returns 404.

- [ ] **Step 3: Browser-side manual verification**

In the browser at `http://localhost:9997`:
1. Click on a history entry — iframe loads near-instantly (HTML is small, images stream in).
2. Click the same entry again — iframe loads instantly (HTTP cache hit).
3. Click × on a history entry — confirm dialog appears, then entry disappears.
4. Generate a new preview — iframe loads with the new article, scroll resets to top.
5. Open DevTools → Network tab → click a history entry → confirm `200 (disk cache)` for the second click.

- [ ] **Step 4: Commit any leftover cleanup**

```bash
git status
# If anything is dirty, commit it as a small fix.
```

---

## Self-Review (run before declaring done)

**Spec coverage:**
- [x] Split HTML and images via iframe.src — Task 2 + Task 3
- [x] Stop writing html into history.json — Task 1
- [x] New endpoints (html, image, delete) — Task 2
- [x] Cache headers — Task 2
- [x] Delete button per history entry with confirm() — Task 4
- [x] Drop `_embed_images_as_data_uris` — Task 5

**Placeholder scan:** None — every step has concrete code or commands.

**Type consistency:** `history.delete(entry_id: int) -> bool` used consistently in Task 1 test, Task 2 endpoint, Task 4 frontend. `setPreview(htmlUrl, restoreScroll)` used consistently in Task 3. `html_url` field used consistently.
