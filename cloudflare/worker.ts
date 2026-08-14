type TopicStatus = "available" | "drafted" | "pushed" | "published" | "archived";
type ArticleStatus =
  | "generating"
  | "draft"
  | "review"
  | "ready"
  | "pushed"
  | "published"
  | "failed"
  | "archived";
type JobStatus = "queued" | "running" | "completed" | "failed" | "interrupted" | "cancelled";

type TopicRow = {
  id: string;
  source: string;
  client: string;
  title: string;
  category: string;
  context_json: string | null;
  status: TopicStatus;
  created_at: string;
  updated_at: string;
  used_at: string | null;
};

type ArticleRow = {
  article_id: string;
  local_history_id: number;
  topic_id: string | null;
  client: string;
  title: string;
  category: string;
  status: ArticleStatus;
  theme: string;
  markdown: string | null;
  image_mode: string | null;
  assessment_json: string | null;
  artifact_ref: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

type JobRow = {
  id: string;
  article_id: string | null;
  kind: string;
  status: JobStatus;
  phase: string;
  progress: number;
  payload_json: string | null;
  result_json: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
};

type JsonObject = Record<string, unknown>;

const ARTICLE_TRANSITIONS: Record<ArticleStatus, readonly ArticleStatus[]> = {
  generating: ["draft", "review", "ready", "failed", "archived"],
  draft: ["generating", "review", "ready", "failed", "archived"],
  review: ["generating", "draft", "ready", "failed", "archived"],
  ready: ["generating", "draft", "review", "pushed", "failed", "archived"],
  pushed: ["generating", "draft", "review", "published", "archived"],
  published: ["generating", "draft", "review", "archived"],
  failed: ["generating", "draft", "archived"],
  archived: ["draft"],
};

const TOPIC_TRANSITIONS: Record<TopicStatus, readonly TopicStatus[]> = {
  available: ["drafted", "archived"],
  drafted: ["available", "pushed", "published", "archived"],
  pushed: ["drafted", "published", "archived"],
  published: ["archived"],
  archived: ["available"],
};

const JOB_TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  queued: ["running", "failed", "interrupted", "cancelled"],
  running: ["completed", "failed", "interrupted", "cancelled"],
  completed: [],
  failed: ["queued"],
  interrupted: ["queued", "cancelled"],
  cancelled: ["queued"],
};

class HttpError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

function response(data: JsonObject, status = 200): Response {
  return Response.json(data, {
    status,
    headers: {"Cache-Control": "no-store"},
  });
}

async function authorized(request: Request, expected: string): Promise<boolean> {
  const header = request.headers.get("Authorization") ?? "";
  const provided = header.startsWith("Bearer ") ? header.slice(7) : "";
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

async function body(request: Request): Promise<JsonObject> {
  const length = Number(request.headers.get("Content-Length") ?? "0");
  if (length > 900_000) throw new HttpError(413, "request body too large");
  const value: unknown = await request.json();
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError(400, "JSON object required");
  }
  return value as JsonObject;
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value.trim() : fallback;
}

function nullableText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseJson(value: string | null): unknown {
  if (!value) return null;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function topicJson(row: TopicRow): JsonObject {
  const context = parseJson(row.context_json);
  return {...row, context};
}

function articleJson(row: ArticleRow): JsonObject {
  return {
    id: row.local_history_id,
    article_id: row.article_id,
    topic_id: row.topic_id,
    client: row.client,
    title: row.title,
    category: row.category,
    status: row.status,
    theme: row.theme,
    markdown: row.markdown,
    image_mode: row.image_mode,
    assessment: parseJson(row.assessment_json),
    workdir: row.artifact_ref ?? "",
    version: row.version,
    created_at: row.created_at,
    updated_at: row.updated_at,
    archived_at: row.archived_at,
  };
}

function jobJson(row: JobRow): JsonObject {
  return {
    ...row,
    payload: parseJson(row.payload_json),
    result: parseJson(row.result_json),
  };
}

function isArticleStatus(value: string): value is ArticleStatus {
  return Object.hasOwn(ARTICLE_TRANSITIONS, value);
}

function isTopicStatus(value: string): value is TopicStatus {
  return Object.hasOwn(TOPIC_TRANSITIONS, value);
}

function isJobStatus(value: string): value is JobStatus {
  return Object.hasOwn(JOB_TRANSITIONS, value);
}

async function getTopic(env: Env, id: string): Promise<TopicRow | null> {
  return env.DB.prepare("SELECT * FROM topics WHERE id = ?1").bind(id).first<TopicRow>();
}

async function getArticle(env: Env, historyId: number): Promise<ArticleRow | null> {
  return env.DB.prepare(
    `SELECT id AS article_id, local_history_id, topic_id, client, title, category,
            status, theme, markdown, image_mode, assessment_json, artifact_ref,
            version, created_at, updated_at, archived_at
       FROM articles WHERE local_history_id = ?1`,
  ).bind(historyId).first<ArticleRow>();
}

async function getJob(env: Env, id: string): Promise<JobRow | null> {
  return env.DB.prepare("SELECT * FROM generation_jobs WHERE id = ?1").bind(id).first<JobRow>();
}

async function listTopics(url: URL, env: Env): Promise<Response> {
  const conditions: string[] = [];
  const values: string[] = [];
  const add = (sql: string, value: string): void => {
    conditions.push(sql.replace("?", `?${values.length + 1}`));
    values.push(value);
  };
  const query = text(url.searchParams.get("q"));
  const status = text(url.searchParams.get("status"));
  const category = text(url.searchParams.get("category"));
  const source = text(url.searchParams.get("source"));
  const client = text(url.searchParams.get("client"));
  if (query) {
    values.push(`%${query}%`, `%${query}%`);
    conditions.push(`(title LIKE ?${values.length - 1} OR id LIKE ?${values.length})`);
  }
  if (status && status !== "all") add("status = ?", status);
  if (category && category !== "all") add("category = ?", category);
  if (source && source !== "all") add("source = ?", source);
  if (client) add("client = ?", client);
  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 100), 1), 200);
  const offset = Math.max(Number(url.searchParams.get("offset") ?? 0), 0);
  const listSql = `SELECT * FROM topics ${where}
    ORDER BY CASE status WHEN 'available' THEN 0 WHEN 'drafted' THEN 1 ELSE 2 END,
             updated_at DESC, id ASC LIMIT ?${values.length + 1} OFFSET ?${values.length + 2}`;
  const countSql = `SELECT COUNT(*) AS total FROM topics ${where}`;
  const [listResult, countResult] = await env.DB.batch([
    env.DB.prepare(listSql).bind(...values, limit, offset),
    env.DB.prepare(countSql).bind(...values),
  ]);
  if (!listResult || !countResult) throw new HttpError(500, "topic query failed");
  const rows = (listResult.results ?? []) as TopicRow[];
  const total = Number((countResult.results?.[0] as {total?: number} | undefined)?.total ?? 0);
  return response({ok: true, topics: rows.map(topicJson), total, limit, offset});
}

async function createTopic(request: Request, env: Env): Promise<Response> {
  const data = await body(request);
  const title = text(data.title);
  if (!title) throw new HttpError(400, "title required");
  const source = text(data.source, "custom");
  if (!["corpus", "custom", "hotspot", "import"].includes(source)) {
    throw new HttpError(400, "invalid source");
  }
  const id = text(data.id) || `custom-${crypto.randomUUID()}`;
  const category = text(data.category, "custom");
  const client = text(data.client);
  const context = data.context && typeof data.context === "object" ? JSON.stringify(data.context) : null;
  await env.DB.prepare(
    `INSERT INTO topics (id, source, client, title, category, context_json)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6)`,
  ).bind(id, source, client, title, category, context).run();
  const row = await getTopic(env, id);
  if (!row) throw new HttpError(500, "topic insert failed");
  return response({ok: true, topic: topicJson(row)}, 201);
}

async function bulkTopics(request: Request, env: Env): Promise<Response> {
  const data = await body(request);
  if (!Array.isArray(data.topics) || data.topics.length > 200) {
    throw new HttpError(400, "topics array required (max 200)");
  }
  const statements: D1PreparedStatement[] = [];
  for (const item of data.topics) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const raw = item as JsonObject;
    const id = text(raw.id);
    const title = text(raw.title);
    if (!id || !title) continue;
    const context = {
      key_points: Array.isArray(raw.key_points) ? raw.key_points : [],
      origin: text(raw.origin),
      caution: text(raw.caution, "no"),
    };
    statements.push(env.DB.prepare(
      `INSERT INTO topics (id, source, client, title, category, context_json)
       VALUES (?1, 'corpus', '', ?2, ?3, ?4)
       ON CONFLICT(id) DO UPDATE SET
         title = excluded.title,
         category = excluded.category,
         context_json = excluded.context_json,
         updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`,
    ).bind(id, title, text(raw.category), JSON.stringify(context)));
  }
  if (statements.length) await env.DB.batch(statements);
  return response({ok: true, upserted: statements.length});
}

async function patchTopic(request: Request, env: Env, id: string): Promise<Response> {
  const current = await getTopic(env, id);
  if (!current) throw new HttpError(404, "topic not found");
  const data = await body(request);
  const nextStatus = text(data.status);
  if (!nextStatus || !isTopicStatus(nextStatus)) throw new HttpError(400, "invalid topic status");
  if (nextStatus !== current.status && !TOPIC_TRANSITIONS[current.status].includes(nextStatus)) {
    throw new HttpError(409, `invalid topic transition: ${current.status} -> ${nextStatus}`);
  }
  if (nextStatus !== current.status) {
    await env.DB.batch([
      env.DB.prepare(
        `UPDATE topics SET status = ?1,
          used_at = CASE WHEN ?1 = 'drafted' AND used_at IS NULL THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE used_at END,
          updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?2`,
      ).bind(nextStatus, id),
      env.DB.prepare(
        `INSERT INTO status_events (entity_type, entity_id, from_status, to_status, details_json)
         VALUES ('topic', ?1, ?2, ?3, ?4)`,
      ).bind(id, current.status, nextStatus, JSON.stringify(data.details ?? null)),
    ]);
  }
  const row = await getTopic(env, id);
  if (!row) throw new HttpError(500, "topic update failed");
  return response({ok: true, topic: topicJson(row)});
}

async function listArticles(url: URL, env: Env): Promise<Response> {
  const status = text(url.searchParams.get("status"));
  const query = text(url.searchParams.get("q"));
  const conditions = ["status <> 'archived'"];
  const values: string[] = [];
  if (status && status !== "all") {
    values.push(status);
    conditions.push(`status = ?${values.length}`);
  }
  if (query) {
    values.push(`%${query}%`);
    conditions.push(`(title LIKE ?${values.length} OR topic_id LIKE ?${values.length})`);
  }
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 50), 1), 200);
  const offset = Math.max(Number(url.searchParams.get("offset") ?? 0), 0);
  const result = await env.DB.prepare(
    `SELECT id AS article_id, local_history_id, topic_id, client, title, category,
            status, theme, NULL AS markdown, image_mode, assessment_json, artifact_ref,
            version, created_at, updated_at, archived_at
       FROM articles WHERE ${conditions.join(" AND ")}
       ORDER BY updated_at DESC LIMIT ?${values.length + 1} OFFSET ?${values.length + 2}`,
  ).bind(...values, limit, offset).all<ArticleRow>();
  return response({ok: true, articles: result.results.map(articleJson), limit, offset});
}

async function createArticle(request: Request, env: Env): Promise<Response> {
  const data = await body(request);
  const topicId = nullableText(data.topic_id);
  const statusText = text(data.status, "generating");
  if (!isArticleStatus(statusText)) throw new HttpError(400, "invalid article status");
  if (topicId && !(await getTopic(env, topicId))) throw new HttpError(404, "topic not found");
  const articleId = crypto.randomUUID();
  const requestedHistoryId = Number(data.local_history_id ?? 0);
  const historyId = Number.isInteger(requestedHistoryId) && requestedHistoryId > 0
    ? requestedHistoryId
    : null;
  const createdAt = nullableText(data.created_at);
  const assessment = data.assessment && typeof data.assessment === "object"
    ? JSON.stringify(data.assessment)
    : null;
  await env.DB.prepare(
    `INSERT INTO articles (
       id, source_instance, local_history_id, topic_id, client, title, category,
       status, theme, markdown, image_mode, assessment_json, artifact_ref,
       created_at, updated_at
     ) SELECT ?1, 'local', COALESCE(?2, COALESCE(MAX(local_history_id), 0) + 1),
              ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
              COALESCE(?13, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
              COALESCE(?13, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
       FROM articles`,
  ).bind(
    articleId,
    historyId,
    topicId,
    text(data.client),
    text(data.title),
    text(data.category),
    statusText,
    text(data.theme, "terracotta"),
    nullableText(data.markdown),
    nullableText(data.image_mode),
    assessment,
    nullableText(data.workdir),
    createdAt,
  ).run();
  const inserted = await env.DB.prepare("SELECT local_history_id FROM articles WHERE id = ?1")
    .bind(articleId).first<{local_history_id: number}>();
  if (!inserted) throw new HttpError(500, "article insert failed");
  await env.DB.prepare(
    `INSERT INTO status_events (entity_type, entity_id, from_status, to_status, details_json)
     VALUES ('article', ?1, NULL, ?2, NULL)`,
  ).bind(articleId, statusText).run();
  const row = await getArticle(env, inserted.local_history_id);
  if (!row) throw new HttpError(500, "article read failed");
  return response({ok: true, article: articleJson(row)}, 201);
}

async function patchArticle(request: Request, env: Env, historyId: number): Promise<Response> {
  const current = await getArticle(env, historyId);
  if (!current) throw new HttpError(404, "article not found");
  const data = await body(request);
  const assignments: string[] = [];
  const values: unknown[] = [];
  const add = (column: string, value: unknown): void => {
    values.push(value);
    assignments.push(`${column} = ?${values.length}`);
  };
  for (const [field, column] of [
    ["title", "title"], ["category", "category"], ["theme", "theme"],
    ["markdown", "markdown"], ["image_mode", "image_mode"], ["workdir", "artifact_ref"],
  ] as const) {
    if (field in data) add(column, data[field]);
  }
  if ("assessment" in data) add("assessment_json", JSON.stringify(data.assessment ?? null));
  let nextStatus = current.status;
  if ("status" in data) {
    const requested = text(data.status);
    if (!isArticleStatus(requested)) throw new HttpError(400, "invalid article status");
    if (requested !== current.status && !ARTICLE_TRANSITIONS[current.status].includes(requested)) {
      throw new HttpError(409, `invalid article transition: ${current.status} -> ${requested}`);
    }
    nextStatus = requested;
    add("status", requested);
    if (requested === "archived") add("archived_at", new Date().toISOString());
    if (current.status === "archived" && requested !== "archived") add("archived_at", null);
  }
  if (assignments.length) {
    assignments.push("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')");
    const update = env.DB.prepare(
      `UPDATE articles SET ${assignments.join(", ")} WHERE local_history_id = ?${values.length + 1}`,
    ).bind(...values, historyId);
    if (nextStatus !== current.status) {
      await env.DB.batch([
        update,
        env.DB.prepare(
          `INSERT INTO status_events (entity_type, entity_id, from_status, to_status, details_json)
           VALUES ('article', ?1, ?2, ?3, ?4)`,
        ).bind(current.article_id, current.status, nextStatus, JSON.stringify(data.details ?? null)),
      ]);
    } else {
      await update.run();
    }
  }
  const row = await getArticle(env, historyId);
  if (!row) throw new HttpError(500, "article update failed");
  return response({ok: true, article: articleJson(row)});
}

async function createJob(request: Request, env: Env): Promise<Response> {
  const data = await body(request);
  const kind = text(data.kind);
  if (!["full", "article", "images", "image", "render", "quality"].includes(kind)) {
    throw new HttpError(400, "invalid job kind");
  }
  const requestedId = text(data.id);
  const id = /^[a-f0-9]{32}$/.test(requestedId)
    ? requestedId
    : crypto.randomUUID().replaceAll("-", "");
  const historyId = Number(data.history_id ?? 0);
  const article = historyId ? await getArticle(env, historyId) : null;
  await env.DB.prepare(
    `INSERT INTO generation_jobs (id, article_id, kind, payload_json)
     VALUES (?1, ?2, ?3, ?4)`,
  ).bind(id, article?.article_id ?? null, kind, JSON.stringify(data.payload ?? {})).run();
  const row = await getJob(env, id);
  if (!row) throw new HttpError(500, "job insert failed");
  return response({ok: true, job: jobJson(row)}, 201);
}

async function patchJob(request: Request, env: Env, id: string): Promise<Response> {
  const current = await getJob(env, id);
  if (!current) throw new HttpError(404, "job not found");
  const data = await body(request);
  const assignments: string[] = [];
  const values: unknown[] = [];
  const add = (column: string, value: unknown): void => {
    values.push(value);
    assignments.push(`${column} = ?${values.length}`);
  };
  for (const [field, column] of [["phase", "phase"], ["progress", "progress"], ["error", "error"]] as const) {
    if (field in data) add(column, data[field]);
  }
  if ("result" in data) add("result_json", JSON.stringify(data.result ?? null));
  if ("payload" in data) add("payload_json", JSON.stringify(data.payload ?? null));
  if ("status" in data) {
    const requested = text(data.status);
    if (!isJobStatus(requested)) throw new HttpError(400, "invalid job status");
    if (requested !== current.status && !JOB_TRANSITIONS[current.status].includes(requested)) {
      throw new HttpError(409, `invalid job transition: ${current.status} -> ${requested}`);
    }
    add("status", requested);
    if (requested === "running" && !current.started_at) add("started_at", new Date().toISOString());
    if (["completed", "failed", "interrupted", "cancelled"].includes(requested)) {
      add("completed_at", new Date().toISOString());
    }
  }
  if (assignments.length) {
    assignments.push("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')");
    await env.DB.prepare(
      `UPDATE generation_jobs SET ${assignments.join(", ")} WHERE id = ?${values.length + 1}`,
    ).bind(...values, id).run();
  }
  const row = await getJob(env, id);
  if (!row) throw new HttpError(500, "job update failed");
  return response({ok: true, job: jobJson(row)});
}

async function createPublication(request: Request, env: Env): Promise<Response> {
  const data = await body(request);
  const historyId = Number(data.history_id ?? 0);
  const article = await getArticle(env, historyId);
  if (!article) throw new HttpError(404, "article not found");
  const status = text(data.status, "pending");
  if (!["pending", "pushed", "published", "failed", "revoked"].includes(status)) {
    throw new HttpError(400, "invalid publication status");
  }
  if (status === "pushed" && article.status !== "ready" && article.status !== "pushed") {
    throw new HttpError(409, `article must be ready before push (current: ${article.status})`);
  }
  const result = await env.DB.prepare(
    `INSERT INTO publication_records (
       article_id, platform, target, status, remote_id, response_json, pushed_at, published_at
     ) VALUES (?1, 'wechat', ?2, ?3, ?4, ?5,
       CASE WHEN ?3 = 'pushed' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') END,
       CASE WHEN ?3 = 'published' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') END
     ) RETURNING *`,
  ).bind(
    article.article_id,
    text(data.target, "draft"),
    status,
    nullableText(data.remote_id),
    JSON.stringify(data.response ?? null),
  ).first<Record<string, unknown>>();
  if (status === "pushed") {
    const statements: D1PreparedStatement[] = [];
    if (article.status !== "pushed") {
      statements.push(
        env.DB.prepare(
          `UPDATE articles SET status = 'pushed', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
           WHERE id = ?1`,
        ).bind(article.article_id),
        env.DB.prepare(
          `INSERT INTO status_events (entity_type, entity_id, from_status, to_status, details_json)
           VALUES ('article', ?1, ?2, 'pushed', ?3)`,
        ).bind(article.article_id, article.status, JSON.stringify({publication_id: result?.id ?? null})),
      );
    }
    if (article.topic_id) {
      const topic = await getTopic(env, article.topic_id);
      if (topic && topic.status === "drafted") {
        statements.push(
          env.DB.prepare(
            `UPDATE topics SET status = 'pushed', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = ?1`,
          ).bind(article.topic_id),
          env.DB.prepare(
            `INSERT INTO status_events (entity_type, entity_id, from_status, to_status, details_json)
             VALUES ('topic', ?1, 'drafted', 'pushed', ?2)`,
          ).bind(article.topic_id, JSON.stringify({publication_id: result?.id ?? null})),
        );
      }
    }
    if (statements.length) await env.DB.batch(statements);
  }
  return response({ok: true, publication: result ?? {}}, 201);
}

async function health(env: Env): Promise<Response> {
  const [topics, articles, jobs] = await env.DB.batch([
    env.DB.prepare("SELECT COUNT(*) AS count FROM topics"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM articles WHERE status <> 'archived'"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM generation_jobs"),
  ]);
  if (!topics || !articles || !jobs) throw new HttpError(500, "health query failed");
  const count = (result: D1Result): number => Number((result.results?.[0] as {count?: number} | undefined)?.count ?? 0);
  return response({ok: true, service: "wechat-studio-data", topics: count(topics), articles: count(articles), jobs: count(jobs)});
}

async function route(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const method = request.method.toUpperCase();
  const path = url.pathname.replace(/\/+$/, "") || "/";
  if (path === "/health" && method === "GET") return health(env);
  if (path === "/topics" && method === "GET") return listTopics(url, env);
  if (path === "/topics" && method === "POST") return createTopic(request, env);
  if (path === "/topics/bulk" && method === "POST") return bulkTopics(request, env);
  const topicMatch = path.match(/^\/topics\/([^/]+)$/);
  if (topicMatch && method === "GET") {
    const row = await getTopic(env, decodeURIComponent(topicMatch[1]!));
    if (!row) throw new HttpError(404, "topic not found");
    return response({ok: true, topic: topicJson(row)});
  }
  if (topicMatch && method === "PATCH") return patchTopic(request, env, decodeURIComponent(topicMatch[1]!));
  if (path === "/articles" && method === "GET") return listArticles(url, env);
  if (path === "/articles" && method === "POST") return createArticle(request, env);
  const articleMatch = path.match(/^\/articles\/history\/(\d+)$/);
  if (articleMatch && method === "GET") {
    const row = await getArticle(env, Number(articleMatch[1]));
    if (!row) throw new HttpError(404, "article not found");
    return response({ok: true, article: articleJson(row)});
  }
  if (articleMatch && method === "PATCH") return patchArticle(request, env, Number(articleMatch[1]));
  if (articleMatch && method === "DELETE") {
    const replacement = new Request(request, {
      method: "PATCH",
      body: JSON.stringify({status: "archived"}),
      headers: {"Content-Type": "application/json"},
    });
    return patchArticle(replacement, env, Number(articleMatch[1]));
  }
  if (path === "/jobs" && method === "POST") return createJob(request, env);
  const jobMatch = path.match(/^\/jobs\/([a-f0-9]{32})$/);
  if (jobMatch && method === "GET") {
    const row = await getJob(env, jobMatch[1]!);
    if (!row) throw new HttpError(404, "job not found");
    return response({ok: true, job: jobJson(row)});
  }
  if (jobMatch && method === "PATCH") return patchJob(request, env, jobMatch[1]!);
  if (path === "/publications" && method === "POST") return createPublication(request, env);
  throw new HttpError(404, "not found");
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (!(await authorized(request, env.D1_API_TOKEN))) {
      return response({ok: false, error: "unauthorized"}, 401);
    }
    try {
      return await route(request, env);
    } catch (error) {
      const status = error instanceof HttpError ? error.status : 500;
      const message = error instanceof Error ? error.message : "unknown error";
      console.error(JSON.stringify({message: "request failed", path: url.pathname, status, error: message}));
      return response({ok: false, error: status === 500 ? "internal error" : message}, status);
    }
  },
} satisfies ExportedHandler<Env>;
