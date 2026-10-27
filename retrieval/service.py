"""Internal local embedding/Qdrant service. Stores job chunks, never resumes."""
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

import numpy as np

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import QdrantClient, models

MODEL = 'BAAI/bge-small-zh-v1.5'
DIMENSIONS = 512
COLLECTION = os.getenv('QDRANT_COLLECTION', 'career_jobs_bge_zh_v1')
MANIFEST = Path('/opt/embedding-model/manifest.json')
REVISION = json.loads(MANIFEST.read_text())['revision'] if MANIFEST.exists() else 'test'
CHUNK_VERSION = 2


class JobDocument(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=160)
    city: str = Field(max_length=80)
    education: str = Field(max_length=20)
    major: str = Field(max_length=200)
    experience: str = Field(max_length=20)
    description: str = Field(max_length=10000)
    salary_min: int | None = None
    salary_max: int | None = None


class SyncInput(BaseModel):
    jobs: list[JobDocument] = Field(max_length=20000)


class SearchInput(SyncInput):
    query: str = Field(min_length=1, max_length=6000)
    limit: int = Field(default=40, ge=1, le=40)


def chunks(job):
    heading = f'{job.title[:60]}\n城市：{job.city[:20]}；学历：{job.education}；经验：{job.experience}'
    # Keep every part of the description searchable, within the model's context window.
    text = f'岗位名称：{job.title}\n专业要求：{job.major}\n岗位描述：{job.description}'.strip()
    return [heading + '\n' + text[start:start + 300] for start in range(0, len(text), 250)]


def digest(job):
    versioned = {'job': job.model_dump(), 'model': MODEL, 'revision': REVISION, 'chunks': CHUNK_VERSION}
    return hashlib.sha256(json.dumps(versioned, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Index:
    def __init__(self, client, encoder, collection=COLLECTION):
        self.client, self.encoder, self.collection = client, encoder, collection
        self.lock = threading.RLock()
        if not client.collection_exists(collection):
            client.create_collection(collection, vectors_config=models.VectorParams(size=DIMENSIONS, distance=models.Distance.COSINE))
        info = client.get_collection(collection)
        if info.config.params.vectors.size != DIMENSIONS or info.config.params.vectors.distance != models.Distance.COSINE:
            raise RuntimeError('Embedding collection configuration mismatch; use a new collection')
        client.create_payload_index(collection, 'job_id', models.PayloadSchemaType.INTEGER)

    def stored(self):
        result, offset = {}, None
        while True:
            points, offset = self.client.scroll(self.collection, limit=256, offset=offset,
                                                 with_payload=['job_id', 'digest'], with_vectors=False)
            for point in points:
                payload = point.payload or {}
                result.setdefault(payload['job_id'], []).append(payload['digest'])
            if offset is None:
                return result

    def _upsert(self, jobs, stored):
        updated = 0
        if len({job.id for job in jobs}) != len(jobs):
            raise ValueError('Duplicate job IDs')
        for job in jobs:
            version = digest(job)
            texts = chunks(job)
            existing = stored.get(job.id, [])
            if len(existing) == len(texts) and set(existing) == {version}:
                continue
            vectors = list(self.encoder.passage_embed(texts))
            points = [models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, f'{self.collection}:{job.id}:{version}:{i}')),
                        vector=vector.tolist(), payload={'job_id': job.id, 'digest': version, 'chunk': i, 'text': text})
                      for i, (text, vector) in enumerate(zip(texts, vectors, strict=True))]
            for start in range(0, len(points), 32):
                self.client.upsert(self.collection, points=points[start:start + 32], wait=True)
            self.client.delete(self.collection, models.FilterSelector(filter=models.Filter(
                must=[models.FieldCondition(key='job_id', match=models.MatchValue(value=job.id))],
                must_not=[models.FieldCondition(key='digest', match=models.MatchValue(value=version))])), wait=True)
            updated += 1
        return updated

    def sync(self, jobs):
        with self.lock:
            stored = self.stored()
            updated = self._upsert(jobs, stored)
            stale = set(stored) - {job.id for job in jobs}
            if stale:
                self.client.delete(self.collection, models.FilterSelector(filter=models.Filter(must=[
                    models.FieldCondition(key='job_id', match=models.MatchAny(any=list(stale)))])), wait=True)
            return {'indexed_jobs': len(jobs), 'updated_jobs': updated, 'removed_jobs': len(stale), 'model': MODEL}

    def search(self, query, jobs, limit):
        with self.lock:
            # Request-local upsert ensures imports/edits are visible even before periodic sync.
            self._upsert(jobs, self.stored())
            if not jobs:
                return {'hits': [], 'eligible_jobs': 0, 'model': MODEL}
            query_parts = [query[start:start + 300] for start in range(0, len(query), 250)]
            vector = np.mean(list(self.encoder.query_embed(query_parts)), axis=0).tolist()
            groups = self.client.query_points_groups(self.collection, query=vector, group_by='job_id', group_size=1,
                limit=limit, with_payload=True, with_vectors=False, query_filter=models.Filter(must=[
                    models.FieldCondition(key='job_id', match=models.MatchAny(any=[job.id for job in jobs]))]))
            return {'hits': [{'job_id': group.id, 'score': group.hits[0].score,
                             'chunk': group.hits[0].payload['text'], 'digest': group.hits[0].payload['digest']} for group in groups.groups],
                    'eligible_jobs': len(jobs), 'model': MODEL}

    def status(self):
        with self.lock:
            stored = self.stored()
            return {'ready': True, 'model': MODEL, 'revision': REVISION, 'dimensions': DIMENSIONS, 'indexed_jobs': len(stored),
                    'indexed_chunks': sum(len(v) for v in stored.values())}


index = None


@asynccontextmanager
async def lifespan(app):
    global index
    from fastembed import TextEmbedding
    encoder = TextEmbedding(model_name=MODEL, specific_model_path='/opt/embedding-model', threads=2)
    client = QdrantClient(url=os.getenv('QDRANT_URL', 'http://qdrant:6333'), timeout=60)
    index = Index(client, encoder)
    yield
    client.close()


app = FastAPI(lifespan=lifespan)


@app.get('/health')
def health():
    if index is None:
        raise HTTPException(503, 'Embedding model is loading')
    return index.status()


@app.post('/sync')
def sync(data: SyncInput):
    try:
        return index.sync(data.jobs)
    except Exception:
        raise HTTPException(503, 'Job index synchronization failed') from None


@app.post('/search')
def search(data: SearchInput):
    try:
        return index.search(data.query, data.jobs, data.limit)
    except Exception:
        raise HTTPException(503, 'Vector retrieval is unavailable') from None
