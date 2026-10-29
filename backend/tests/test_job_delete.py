from app.db import SessionLocal
from app.models import Job
from test_business import preview


def imported(client, rows):
    batch = preview(client, rows).json()
    response = client.post(f"/api/imports/{batch['id']}/commit")
    assert response.status_code == 200, response.text
    return batch


def test_single_delete_keeps_history_and_allows_reimport(clients):
    c = clients('alice')
    batch = imported(c, [['后端开发', '甲', '上海', '本科', '不限', '不限']])
    job = c.get('/api/jobs').json()['items'][0]
    sid = c.post('/api/students', json={'name': '学员', 'target_role': '后端', 'target_city': '上海', 'major': '计算机'}).json()['id']
    reco = c.post(f'/api/students/{sid}/recommendations', json={'job_id': job['id']}).json()
    c.post(f'/api/students/{sid}/followups', json={'recommendation_id': reco['id'], 'content': '已沟通', 'stage': '已推荐'})
    assert c.delete(f"/api/jobs/{job['id']}").json()['deleted'] == 1
    assert c.get('/api/jobs?status=失效').json()['total'] == 0
    assert c.get('/api/jobs?status=有效').json()['total'] == 0
    assert c.get('/api/dashboard').json()['jobs'] == 0
    assert c.get(f"/api/jobs/{job['id']}").status_code == 404
    assert c.put(f"/api/jobs/{job['id']}", json={'title':'后端开发','company':'甲','city':'上海'}).status_code == 404
    profile = c.get(f'/api/students/{sid}').json()
    assert profile['recommendations'][0]['snapshot']['title'] == '后端开发'
    assert profile['followups'][0]['content'] == '已沟通'
    assert c.post(f'/api/students/{sid}/recommendations', json={'job_id':job['id']}).status_code == 400
    assert c.get(f'/api/students/{sid}/matched-jobs').json()['total'] == 0
    assert c.post(f'/api/students/{sid}/jobs/export', json={'job_ids':[job['id']]}).status_code == 200
    sid2 = c.post('/api/students', json={'name': '其他学员'}).json()['id']
    assert c.post(f'/api/students/{sid2}/jobs/export', json={'job_ids':[job['id']]}).status_code == 404
    assert c.delete(f"/api/jobs/{job['id']}").json()['deleted'] == 0
    imported(c, [['后端开发', '甲', '上海']])
    assert c.get('/api/jobs').json()['total'] == 1
    summary = c.get(f"/api/imports/{batch['id']}/jobs/summary").json()
    assert summary['remaining'] == 0 and summary['deleted'] == 1


def test_bulk_delete_is_atomic_and_checks_permissions(clients):
    a,b,admin = clients('alice'),clients('bob'),clients('admin')
    imported(a, [['甲岗位','甲','上海']]); imported(b, [['乙岗位','乙','北京']])
    jobs = a.get('/api/jobs').json()['items']; ids=[j['id'] for j in jobs]
    assert a.post('/api/jobs/bulk-delete', json={'job_ids':ids}).status_code == 403
    assert a.get('/api/jobs').json()['total'] == 2
    assert admin.post('/api/jobs/bulk-delete', json={'job_ids':[ids[0],999999]}).status_code == 404
    assert a.get('/api/jobs').json()['total'] == 2
    assert admin.post('/api/jobs/bulk-delete', json={'job_ids':ids+ids}).json()['deleted'] == 2
    assert admin.post('/api/jobs/bulk-delete', json={'job_ids':[]}).status_code == 422
    assert a.get('/api/jobs').json()['total'] == 0


def test_delete_batch_does_not_delete_duplicate_rows_from_other_batch(clients):
    a,b = clients('alice'),clients('bob')
    first=imported(a,[['共享岗位','甲','上海']])
    second=imported(b,[['共享岗位','甲','上海'],['新岗位','乙','北京']])
    url=f"/api/imports/{second['id']}/jobs"
    assert a.delete(url).status_code == 404
    assert b.get(url+'/summary').json()['remaining'] == 1
    assert b.delete(url).json()['deleted'] == 1
    assert b.get('/api/jobs').json()['items'][0]['title'] == '共享岗位'
    assert b.get(url+'/summary').json()['deleted'] == 1
    assert b.delete(url).json()['deleted'] == 0
    assert a.get(f"/api/imports/{first['id']}/jobs/summary").json()['remaining'] == 1
    assert b.get(f"/api/imports/{second['id']}").json()['status'] == '已完成'


def test_legacy_batch_and_edited_jobs_are_safely_traced(clients):
    c=clients('alice')
    batch=imported(c,[['原岗位','甲','上海'],['保留来源','乙','北京']])
    jobs=c.get('/api/jobs').json()['items']
    legacy=next(j for j in jobs if j['title']=='原岗位')
    edited=next(j for j in jobs if j['title']=='保留来源')
    with SessionLocal() as db:
        obj=db.get(Job,legacy['id']); obj.source_batch_id=None; obj.source_row_number=None; db.commit()
    assert c.put(f"/api/jobs/{edited['id']}",json={'title':'编辑后岗位','company':'乙','city':'北京'}).status_code==200
    url=f"/api/imports/{batch['id']}/jobs"
    assert c.get(url+'/summary').json()['remaining']==2
    assert c.delete(url).json()['deleted']==2
    assert c.get(url+'/summary').json()['deleted']==2
    pending=preview(c,[['待确认','甲','上海']]).json()
    assert c.delete(f"/api/imports/{pending['id']}/jobs").status_code==409
