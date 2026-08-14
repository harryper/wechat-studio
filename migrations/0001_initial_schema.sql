-- WeChat Studio persistent content lifecycle for Cloudflare D1.
-- Large binary assets stay outside D1; JSON columns are stored as TEXT.

CREATE TABLE IF NOT EXISTS topics (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL DEFAULT 'corpus'
    CHECK (source IN ('corpus', 'custom', 'hotspot', 'import')),
  client TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  context_json TEXT,
  status TEXT NOT NULL DEFAULT 'available'
    CHECK (status IN ('available', 'drafted', 'pushed', 'published', 'archived')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_topics_client_status
  ON topics(client, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_topics_source_category
  ON topics(source, category);

CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY,
  source_instance TEXT NOT NULL DEFAULT 'local',
  local_history_id INTEGER,
  topic_id TEXT,
  client TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN (
      'generating', 'draft', 'review', 'ready', 'pushed',
      'published', 'failed', 'archived'
    )),
  theme TEXT NOT NULL DEFAULT 'terracotta',
  markdown TEXT,
  image_mode TEXT
    CHECK (image_mode IS NULL OR image_mode IN ('real', 'mixed', 'placeholder')),
  assessment_json TEXT,
  artifact_ref TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  archived_at TEXT,
  FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE SET NULL,
  UNIQUE (source_instance, local_history_id)
);

CREATE INDEX IF NOT EXISTS idx_articles_status_updated
  ON articles(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_topic
  ON articles(topic_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_client
  ON articles(client, created_at DESC);

CREATE TABLE IF NOT EXISTS generation_jobs (
  id TEXT PRIMARY KEY,
  article_id TEXT,
  kind TEXT NOT NULL
    CHECK (kind IN ('full', 'article', 'images', 'image', 'render', 'quality')),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'interrupted', 'cancelled')),
  phase TEXT NOT NULL DEFAULT 'queued',
  progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  payload_json TEXT,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  started_at TEXT,
  completed_at TEXT,
  FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_generation_jobs_status_updated
  ON generation_jobs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_article
  ON generation_jobs(article_id, created_at DESC);

CREATE TABLE IF NOT EXISTS publication_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'wechat',
  target TEXT NOT NULL DEFAULT 'draft'
    CHECK (target IN ('draft', 'broadcast')),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'pushed', 'published', 'failed', 'revoked')),
  remote_id TEXT,
  response_json TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  pushed_at TEXT,
  published_at TEXT,
  FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_publication_article_created
  ON publication_records(article_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_publication_status_updated
  ON publication_records(status, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_publication_remote_id
  ON publication_records(platform, remote_id)
  WHERE remote_id IS NOT NULL AND remote_id <> '';

CREATE TABLE IF NOT EXISTS status_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL
    CHECK (entity_type IN ('topic', 'article', 'job', 'publication')),
  entity_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  details_json TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_status_events_entity
  ON status_events(entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_status_events_created
  ON status_events(created_at DESC);
