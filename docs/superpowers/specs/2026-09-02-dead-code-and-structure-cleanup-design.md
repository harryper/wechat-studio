# Dead Code and Project Structure Cleanup Design

Date: 2026-09-02

## Goal

Remove code that is demonstrably unused, keep documented and compatibility-sensitive entry points stable, and separate runtime references from development artifacts. The cleanup must not change the article-generation flow, Web API, D1 data, publishing behavior, or user-owned local files.

## Compatibility Boundary

Preserve:

- every command documented in `README.md` or `SKILL.md`;
- legacy data utilities `scripts/migrate_history.py` and `scripts/backfill_signals.py`;
- compatibility entry points including `_build_provider`, `mark_interrupted_jobs`, and `upsert_corpus`;
- the checked-in `dist/openclaw` distribution workflow;
- local `.env`, credentials, client data, `output/`, `workspace/`, and Web runtime artifacts.

No external API, D1 mutation, or customer-data migration is part of this cleanup.

## Dead Code Removal

Delete these files after verifying that neither runtime code nor public documentation references them:

- `scripts/seo_keywords.py`: deprecated failure-only shim replaced by `scripts/keyword_research.py`;
- `toolkit/fix_image_paths.py`: handles the retired `image-1---<uuid>.png` placeholder format;
- `toolkit/normalize_image.py`: standalone normalization tool with no caller or public entry; current image output sizing is handled by `toolkit/image_gen.py`.

Remove these unreferenced implementations:

- `scripts/fetch_stats.py::fetch_article_total`;
- `scripts/learn_theme.py::_load_from_file` and its obsolete `--file` usage claim;
- `toolkit/theme.py::_resolve_css_variables`, `_is_simple_selector`, and `get_inline_css_rules`.

Remove imports that remain unused after those deletions. Because `cssutils` is used only by the removed theme parser, remove it from `requirements.txt` and from the dependency diagnostics.

## Repository Structure

Delete all historical development plans and design documents currently under:

- `docs/superpowers/plans/`;
- `docs/superpowers/specs/`, except this design and its implementation plan;
- `references/plans/`;
- `references/specs/`.

`references/` will then contain runtime knowledge and writing instructions only. `docs/superpowers/` will contain only the current cleanup design and implementation plan.

Update `scripts/build_openclaw.py` so the generated distribution excludes:

- the build script itself;
- development-only `plans` and `specs` directories if they are accidentally placed under a copied source directory in the future;
- the already excluded Web-only D1 migration script and Python cache files.

Regenerate `dist/openclaw/` from source after cleanup. The distribution remains checked in, but it contains only OpenClaw runtime assets.

Update the README directory overview to describe the runtime/development boundary.

## Runtime Behavior and Errors

No runtime data flow changes. The existing flow remains:

`topic selection -> article generation -> image generation -> rendering -> quality checks -> user-confirmed draft publication`.

Deleting private, unreachable functions introduces no new error path. Build exclusions are deterministic: runtime files continue to be copied, while development-only files are omitted. Existing provider fallback, Web error handling, and migration behavior remain unchanged.

## Verification

Add focused tests for the OpenClaw build boundary before changing the builder. The tests will build into a temporary directory and assert that:

- required runtime files and directories are present;
- `scripts/build_openclaw.py` is absent;
- development `plans` and `specs` directories are absent;
- Web-only scripts remain absent.

After implementation, run:

- the complete Pytest suite;
- Python bytecode compilation for `toolkit`, `scripts`, and `webapp`;
- `docker compose config -q`;
- a temporary OpenClaw distribution build;
- `git diff --check`;
- repository-wide searches, excluding the current design and implementation plan, for deleted names, retired image placeholders, and removed historical paths.

The final review must confirm that the worktree contains only intended source, test, documentation, and regenerated distribution changes.
