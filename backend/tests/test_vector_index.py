import sys
from pathlib import Path

import numpy as np
import pytest
from qdrant_client import QdrantClient, models
from fastapi import HTTPException
from app import vector_index

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from retrieval.service import Index, JobDocument, DIMENSIONS


class Encoder:
    def __init__(self): self.encoded = 0
    def vectors(self, texts):
        for text in texts:
            vector = np.zeros(DIMENSIONS)
            if 'Python' in text: vector[0] = 1
            elif '会计' in text: vector[1] = 1
            else: vector[2] = 1
            yield vector
    def passage_embed(self, texts):
        self.encoded += len(texts)
        return self.vectors(texts)
    def query_embed(self, texts): return self.vectors(texts)


def job(job_id=1, **values):
    return JobDocument(id=job_id, title='软件工程师', city='上海', education='本科', major='计算机', experience='不限',
                       description=values.pop('description', '使用 Python 开发服务'), **values)


@pytest.fixture
def index():
    client, encoder = QdrantClient(':memory:'), Encoder()
    value = Index(client, encoder, collection='test_vectors')
    yield value
    client.close()


def test_vector_sync_reuses_unchanged_updates_and_removes(index):
    first = job()
    assert index.sync([first])['updated_jobs'] == 1
    encoded = index.encoder.encoded
    assert index.sync([first])['updated_jobs'] == 0
    assert index.encoder.encoded == encoded
    first.description = '负责会计凭证'
    assert index.sync([first])['updated_jobs'] == 1
    assert len(index.stored()[1]) == 1
    assert index.sync([])['removed_jobs'] == 1
    assert index.status()['indexed_jobs'] == 0


def test_tail_chunks_grouping_and_candidate_filter(index):
    long = job(1, description=('其他职责说明。' * 160) + '使用 Python 开发接口并进行测试。')
    other = job(2, description='Python 数据服务')
    account = job(3, description='会计凭证与财务报表')
    index.sync([long, other, account])
    data = index.search('Python SECRET_RESUME', [long, account], 40)
    assert [hit['job_id'] for hit in data['hits']][0] == 1
    assert len(data['hits']) == 2 and 2 not in [hit['job_id'] for hit in data['hits']]
    assert 'Python' in data['hits'][0]['chunk']
    points, _ = index.client.scroll(index.collection, limit=100, with_payload=True)
    assert all('SECRET_RESUME' not in str(point.payload) for point in points)
    # Editing immediately before a search refreshes the indexed content without a periodic job.
    long.description = 'Python 新版岗位职责'
    index.search('Python', [long], 40)
    points, _ = index.client.scroll(index.collection, limit=100, with_payload=True)
    assert all('其他职责说明' not in point.payload['text'] for point in points if point.payload['job_id'] == 1)


def test_grouped_retrieval_capped_at_distinct_jobs(index):
    jobs = [job(i, description='Python ' + '岗位职责。' * 80) for i in range(1, 46)]
    result = index.search('Python', jobs, 40)
    assert len(result['hits']) == 40
    assert len({hit['job_id'] for hit in result['hits']}) == 40


def test_incomplete_chunk_write_is_repaired(index):
    document = job(description='Python ' * 150)
    index.sync([document])
    points, _ = index.client.scroll(index.collection, limit=100)
    index.client.delete(index.collection, models.PointIdsList(points=[points[0].id]), wait=True)
    assert index.sync([document])['updated_jobs'] == 1


def test_vector_client_not_configured_or_network_failure(monkeypatch):
    monkeypatch.delenv('RETRIEVAL_URL', raising=False)
    assert vector_index.status()['ready'] is False
    with pytest.raises(HTTPException): vector_index.search('Python', [], 40)
    monkeypatch.setenv('RETRIEVAL_URL', 'http://internal-vector-service')
    def fail(*args, **kwargs): raise OSError('network down')
    monkeypatch.setattr(vector_index, 'urlopen', fail)
    assert vector_index.status()['ready'] is False
    with pytest.raises(HTTPException) as caught:
        vector_index.search('Python', [], 40)
    assert caught.value.status_code == 503


def test_reindex_is_admin_only(clients, monkeypatch):
    alice, admin = clients('alice'), clients('admin')
    calls = []
    def sync():
        calls.append(True)
        return {'indexed_jobs': 21, 'updated_jobs': 0}
    monkeypatch.setattr(vector_index, 'sync', sync)
    assert alice.post('/api/ai/reindex').status_code == 403
    assert calls == []
    assert admin.post('/api/ai/reindex').json()['indexed_jobs'] == 21
    assert len(calls) == 1
