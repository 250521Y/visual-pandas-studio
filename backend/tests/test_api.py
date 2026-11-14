import io
import os
import tempfile
import uuid
os.environ['VPS_DATA_DIR']=tempfile.mkdtemp(prefix='vps-test-')
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    with TestClient(app) as client:
        client.headers['X-Studio-Session']=str(uuid.uuid4())
        yield client

def uploaded(client):
    r=client.post('/api/upload',files={'file':('test.csv',b'team,value\nA,1\nA,\nB,3\nB,3\n','text/csv')})
    assert r.status_code==200,r.text
    return r.json()

def test_import_preview_history_export(client):
    d=uploaded(client);id=d['id']
    assert d['overview']['missing']==1
    body={'operation':'missing','params':{'columns':['value'],'method':'median'},'revision':0}
    preview=client.post(f'/api/datasets/{id}/preview',json=body).json()
    assert preview['diff']['modifiedCells']==1
    assert client.get(f'/api/datasets/{id}').json()['overview']['missing']==1
    d=client.post(f'/api/datasets/{id}/operations',json=body).json()
    assert d['overview']['missing']==0
    assert client.post(f'/api/datasets/{id}/operations',json=body).status_code==400
    undone=client.post(f'/api/datasets/{id}/history/undo',json={'revision':d['revision']}).json()
    assert undone['overview']['missing']==1
    redone=client.post(f'/api/datasets/{id}/history/redo',json={'revision':undone['revision']}).json()
    assert redone['overview']['missing']==0
    assert client.get(f'/api/datasets/{id}').json()['cursor']==1
    csv=client.get(f'/api/datasets/{id}/export/csv')
    assert pd.read_csv(io.BytesIO(csv.content)).value.isna().sum()==0
    xlsx=client.get(f'/api/datasets/{id}/export/xlsx')
    assert len(pd.read_excel(io.BytesIO(xlsx.content)))==4
    saved=client.put(f'/api/datasets/{id}/project',json={'revision':redone['revision'],'project':{'report':{'title':'标题','notes':'note'}}}).json()
    assert saved['project']['report']['title']=='标题'
    exported=client.get(f'/api/datasets/{id}/export/json')
    restored=client.post('/api/projects/import',files={'file':('project.json',exported.content,'application/json')})
    assert restored.status_code==200,restored.text
    assert restored.json()['overview']['missing']==0
    assert restored.json()['project']['report']['title']=='标题'
    assert restored.json()['cursor']==1
    assert [h['operation'] for h in restored.json()['history']]==['import','missing']

def test_project_preserves_undo_branch_ids_and_text_types(client):
    d=client.post('/api/upload',files={'file':('dates.csv',b'date,value\n2025-01-01,1\n2025-01-02,2\n2025-01-03,3\n')}).json()
    ident=d['id']
    operations=[('type',{'field':'date','target':'text'}),('filter',{'conditions':[{'field':'value','operator':'ge','value':2}]}),('sort',{'columns':['value'],'ascending':[False]})]
    for op,params in operations:
        r=client.post(f'/api/datasets/{ident}/operations',json={'operation':op,'params':params,'revision':d['revision']})
        assert r.status_code==200,r.text
        d=r.json()
    d=client.post(f'/api/datasets/{ident}/history/undo',json={'revision':d['revision']}).json()
    exported=client.get(f'/api/datasets/{ident}/export/json')
    r=client.post('/api/projects/import',files={'file':('project.json',exported.content)})
    assert r.status_code==200,r.text
    restored=r.json();newid=restored['id']
    assert newid!=ident and restored['cursor']==2 and len(restored['history'])==4
    assert restored['fields'][0]['type']=='text'
    assert client.post(f'/api/datasets/{newid}/table',json={'limit':25}).json()['ids']==[1,2]
    redo=client.post(f'/api/datasets/{newid}/history/redo',json={'revision':restored['revision']}).json()
    assert redo['cursor']==3
    assert client.post(f'/api/datasets/{newid}/table',json={}).json()['ids']==[2,1]
    back=client.post(f'/api/datasets/{newid}/history/undo',json={'revision':redo['revision']}).json()
    branch=client.post(f'/api/datasets/{newid}/operations',json={'operation':'column','params':{'action':'copy','field':'value','name':'copy'},'revision':back['revision']}).json()
    assert branch['history'][-1]['operation']=='column' and len(branch['history'])==4
    assert client.post(f'/api/datasets/{newid}/history/redo',json={'revision':branch['revision']}).status_code==400

def test_selection_empty_and_project_validation(client):
    d=uploaded(client);ident=d['id']
    result=client.post(f'/api/datasets/{ident}/table',json={'selection_active':True,'ids':[]}).json()
    assert result['rows']==[] and result['total']==0
    assert client.put(f'/api/datasets/{ident}/project',json={'revision':0,'project':{'charts':[None]}}).status_code==400
    reset=client.post(f'/api/datasets/{ident}/history/reset',json={'revision':0}).json()
    assert reset['cursor']==1 and reset['overview']['missing']==1

def test_excel_encoding_samples_and_isolation(client):
    for name,count in [('iris',150),('titanic',891),('sales',726)]:
        r=client.post('/api/samples/'+name)
        assert r.status_code==200,r.text
        assert r.json()['overview']['rows']==count
    stream=io.BytesIO()
    with pd.ExcelWriter(stream,engine='openpyxl') as writer:
        pd.DataFrame({'中文':[1,2]}).to_excel(writer,sheet_name='工作表',index=False)
    files={'file':('sample.xlsx',stream.getvalue())}
    assert client.post('/api/upload/sheets',files=files).json()['sheets']==['工作表']
    r=client.post('/api/upload',files=files,data={'sheet':'工作表'})
    assert r.status_code==200,r.text
    d=r.json()
    assert d['fields'][0]['name']=='中文'
    token=client.headers['X-Studio-Session']
    client.headers['X-Studio-Session']=str(uuid.uuid4())
    assert client.get('/api/datasets/'+d['id']).status_code==404
    assert client.get('/api/datasets').json()==[]
    client.headers['X-Studio-Session']=token
    content='地区;值\n东;1\n西;2'.encode('gb18030')
    assert client.post('/api/upload',files={'file':('cn.csv',content)},data={'encoding':'gb18030','delimiter':';'}).json()['overview']['rows']==2

def test_table_and_bad_files(client):
    d=uploaded(client);id=d['id']
    result=client.get(f'/api/datasets/{id}/table?search=B&sort=value&desc=true&limit=1').json()
    assert result['total']==2 and len(result['rows'])==1
    assert client.post('/api/upload',files={'file':('bad.exe',b'abc')}).status_code==400
    assert client.post('/api/upload',files={'file':('bad.csv',b'a,a\n1,2')}).json()['error']=='duplicate_columns'
    assert client.post('/api/upload',files={'file':('bad.xlsx',b'not zip')}).json()['error']=='parse_failed'
    assert client.get(f'/api/datasets/{id}/table?limit=1000').status_code==422

def test_excel_preserves_formula_like_text_without_executing(client):
    from openpyxl import load_workbook
    d=client.post('/api/upload',files={'file':('text.csv',b'text,value\n=1+1,2\n+plain,3\n-plain,4\n@plain,5\n')}).json()
    exported=client.get(f'/api/datasets/{d["id"]}/export/xlsx')
    frame=pd.read_excel(io.BytesIO(exported.content))
    assert frame.text.tolist()==['=1+1','+plain','-plain','@plain']
    book=load_workbook(io.BytesIO(exported.content),data_only=False)
    assert book.active['A2'].data_type=='s'
