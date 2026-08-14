import uuid

import pytest


class MemoryD1Client:
    def __init__(self):
        self.topics = {
            "kb-001": {
                "id": "kb-001", "title": "幸存者偏差", "category": "cognitive_bias",
                "source": "corpus", "status": "available", "client": "", "context": {},
            }
        }
        self.articles = {}
        self.jobs = {}
        self.publications = []
        self.next_history_id = 1

    def get(self, path, *, params=None, allow_404=False):
        if path == "/health":
            return {"ok": True, "topics": len(self.topics), "articles": len(self.articles), "jobs": len(self.jobs)}
        if path == "/topics":
            values = list(self.topics.values())
            params = params or {}
            for key in ("status", "source", "category"):
                value = params.get(key)
                if value and value != "all":
                    values = [item for item in values if item.get(key) == value]
            query = params.get("q") or ""
            if query:
                values = [item for item in values if query in item["title"] or query in item["id"]]
            return {"ok": True, "topics": values, "total": len(values)}
        if path.startswith("/topics/"):
            value = self.topics.get(path.rsplit("/", 1)[-1])
            return {"ok": True, "topic": value} if value else None
        if path == "/articles":
            values = [item for item in self.articles.values() if item.get("status") != "archived"]
            return {"ok": True, "articles": list(reversed(values))}
        if path.startswith("/articles/history/"):
            value = self.articles.get(int(path.rsplit("/", 1)[-1]))
            return {"ok": True, "article": value} if value else None
        if path.startswith("/jobs/"):
            value = self.jobs.get(path.rsplit("/", 1)[-1])
            return {"ok": True, "job": value} if value else None
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, data):
        if path == "/topics":
            topic_id = data.get("id") or f"custom-{uuid.uuid4()}"
            topic = {"id": topic_id, "status": "available", **data}
            self.topics[topic_id] = topic
            return {"ok": True, "topic": topic}
        if path == "/topics/bulk":
            for item in data["topics"]:
                self.topics[item["id"]] = {
                    **item, "source": "corpus", "status": "available", "client": "", "context": {},
                }
            return {"ok": True, "upserted": len(data["topics"])}
        if path == "/articles":
            history_id = data.get("local_history_id") or self.next_history_id
            self.next_history_id = max(self.next_history_id, history_id + 1)
            article = {
                "id": history_id,
                "article_id": str(uuid.uuid4()),
                "created_at": data.get("created_at") or "2026-08-14T00:00:00Z",
                "updated_at": "2026-08-14T00:00:00Z",
                "workdir": "",
                "status": "generating",
                "assessment": {},
                **data,
            }
            self.articles[history_id] = article
            return {"ok": True, "article": article}
        if path == "/jobs":
            job_id = data.get("id") or uuid.uuid4().hex
            job = {
                "id": job_id, "kind": data["kind"], "status": "queued", "phase": "queued",
                "progress": 0, "payload": data.get("payload") or {}, "result": None, "error": None,
            }
            self.jobs[job_id] = job
            return {"ok": True, "job": job}
        if path == "/publications":
            record = {"id": len(self.publications) + 1, **data}
            self.publications.append(record)
            if data.get("status") == "pushed":
                self.articles[data["history_id"]]["status"] = "pushed"
            return {"ok": True, "publication": record}
        raise AssertionError(f"unexpected POST {path}")

    def patch(self, path, data):
        if path.startswith("/topics/"):
            topic = self.topics[path.rsplit("/", 1)[-1]]
            topic.update(data)
            return {"ok": True, "topic": topic}
        if path.startswith("/articles/history/"):
            article = self.articles[int(path.rsplit("/", 1)[-1])]
            article.update(data)
            article["updated_at"] = "2026-08-14T00:01:00Z"
            return {"ok": True, "article": article}
        if path.startswith("/jobs/"):
            job = self.jobs[path.rsplit("/", 1)[-1]]
            job.update(data)
            return {"ok": True, "job": job}
        raise AssertionError(f"unexpected PATCH {path}")

    def delete(self, path):
        article = self.articles[int(path.rsplit("/", 1)[-1])]
        article["status"] = "archived"
        return {"ok": True, "article": article}


@pytest.fixture
def memory_d1(monkeypatch):
    from webapp import history, jobs, publications, topics
    from webapp import app as app_module

    fake = MemoryD1Client()
    monkeypatch.setattr(history, "client", fake)
    monkeypatch.setattr(jobs, "client", fake)
    monkeypatch.setattr(topics, "client", fake)
    monkeypatch.setattr(publications, "client", fake)
    monkeypatch.setattr(app_module, "d1", fake)
    return fake
