import io
import pandas as pd
import pytest
from test_api import client

def upload(client,frame,name='new.csv'):
    r=client.post('/api/upload',files={'file':(name,frame.to_csv(index=False).encode('utf-8'))})
    assert r.status_code==200,r.text
    return r.json()

@pytest.fixture
def data():return pd.DataFrame({'key':['A','B','C','D'],'group':['X','X','Y','Y'],'v':[1.,None,3.,5.],'text':[' aa ','BB','cc','DD'],'date':['2025-01-01','2025-01-02','2025-01-04','2025-01-05'],'items':['[1,2]','[]','[3]','[4]']})

@pytest.mark.parametrize('operation,params',[
 ('sample',{'mode':'count','n':3,'seed':7}),('topn',{'field':'v','n':2,'keep':'all'}),('bin',{'field':'v','name':'b','bins':3}),('mapping',{'field':'group','name':'mapped','pairs':[{'from':'X','to':'x'}]}),('string',{'field':'text','name':'clean','method':'strip'}),('date',{'field':'date','name':'quarter','method':'quarter'}),('cumulative',{'field':'v','name':'sum','sort':'date'}),('interpolate',{'field':'v','name':'filled','method':'time','time':'date'}),('melt',{'ids':['key'],'values':['v'],'variableName':'variable','valueName':'measure'}),('stack',{'ids':['key'],'values':['v'],'variableName':'variable','valueName':'measure'}),('pivot_strict',{'ids':['group'],'levels':['key'],'values':['v']}),('unstack',{'ids':['group','key'],'levels':['key'],'values':['v']}),('explode',{'field':'items'}),('dummies',{'columns':['group'],'dummyNa':True}),('group_transform',{'groups':['group'],'field':'v','name':'avg'}),('window_calc',{'field':'v','name':'diff','method':'diff','sort':'date'}),('resample',{'field':'v','time':'date','frequency':'D'}),('rolling',{'field':'v','time':'date','name':'roll','window':2,'minPeriods':1}),('ewm',{'field':'v','time':'date','name':'smooth','alpha':.5}),('growth',{'field':'v','time':'date','name':'rate','periods':1}),('time_gaps',{'field':'v','time':'date','frequency':'D','fill':'linear'})])
def test_incremental_preview_apply_export_undo_redo(client,data,operation,params):
    original=upload(client,data);ident=original['id'];url=f'/api/datasets/{ident}'
    body={'operation':operation,'params':params,'revision':original['revision']}
    r=client.post(url+'/preview',json=body);assert r.status_code==200,r.text;preview=r.json()
    assert client.get(url).json()['cursor']==0
    r=client.post(url+'/operations',json=body);assert r.status_code==200,r.text;applied=r.json()
    assert applied['overview']==preview['overview']
    after=client.post(url+'/table',json={'limit':100}).json();assert after['rows'][:8]==preview['after']['rows']
    step=applied['history'][-1];assert step['status']=='success' and step['rows']==applied['overview']['rows'] and step['columnsBefore']==6
    exported=client.get(url+'/export/csv');assert len(pd.read_csv(io.BytesIO(exported.content)))==applied['overview']['rows']
    undone=client.post(url+'/history/undo',json={'revision':applied['revision']}).json();assert undone['overview']==original['overview']
    redone=client.post(url+'/history/redo',json={'revision':undone['revision']}).json();assert redone['overview']==applied['overview']

def test_selection_date_range_revision_and_formal_filter(client,data):
    d=upload(client,data);url=f'/api/datasets/{d["id"]}'
    low=pd.Timestamp('2025-01-02',tz='UTC').timestamp()*1000;high=pd.Timestamp('2025-01-04',tz='UTC').timestamp()*1000
    r=client.post(url+'/analysis',json={'kind':'select','field':'date','lower':low,'upper':high,'includeUpper':True,'revision':0}).json();assert r['ids']==[1,2]
    body={'operation':'select_rows','params':{'ids':r['ids']},'revision':0}
    assert client.post(url+'/preview',json=body).json()['overview']['rows']==2
    applied=client.post(url+'/operations',json=body).json();assert applied['overview']['rows']==2
    assert client.post(url+'/analysis',json={'kind':'describe','revision':0}).json()['error']=='stale_revision'
    back=client.post(url+'/history/undo',json={'revision':applied['revision']}).json();assert back['overview']['rows']==4
    assert client.post(url+'/operations',json={'operation':'select_rows','params':{'ids':[999]},'revision':back['revision']}).status_code==400
    assert client.get(url).json()['revision']==back['revision']

def test_comparison_read_only_right_version_and_isolation(client,data):
    left=upload(client,data);right=upload(client,data.assign(v=[9.,2.,3.,5.]));url=f'/api/datasets/{left["id"]}'
    body={'operation':'compare','revision':0,'params':{'dataset':right['id'],'otherRevision':0,'left':'key','right':'key','columns':['v']}}
    p=client.post(url+'/preview',json=body);assert p.status_code==200,p.text;assert p.json()['visual']['quality']['modifiedValues']==2
    assert client.post(url+'/operations',json=body).json()['error']=='read_only_operation'
    client.post(f'/api/datasets/{right["id"]}/history/reset',json={'revision':0})
    assert client.post(url+'/preview',json=body).json()['error']=='stale_revision'

@pytest.mark.parametrize('operation,extra',[('update',{}),('combine_first',{}),('merge_asof',{'duplicates':'last','direction':'nearest','tolerance':'1D'})])
def test_combination_preview_apply_undo_and_foreign_ownership(client,data,operation,extra):
    import uuid
    left=upload(client,data);right=upload(client,data.assign(v=[9.,2.,3.,5.]));url=f'/api/datasets/{left["id"]}'
    key='date' if operation=='merge_asof' else 'key'
    body={'operation':operation,'revision':0,'params':{'dataset':right['id'],'otherRevision':0,'left':key,'right':key,'columns':['v'],**extra}}
    r=client.post(url+'/preview',json=body);assert r.status_code==200,r.text
    preview=r.json();r=client.post(url+'/operations',json=body);assert r.status_code==200,r.text
    applied=r.json();assert applied['overview']==preview['overview']
    assert client.post(url+'/table',json={}).json()['rows'][:8]==preview['after']['rows']
    undone=client.post(url+'/history/undo',json={'revision':applied['revision']}).json();assert undone['overview']==left['overview']
    body['revision']=undone['revision']
    original_owner=client.headers['X-Studio-Session'];client.headers['X-Studio-Session']=str(uuid.uuid4())
    foreign=upload(client,data);client.headers['X-Studio-Session']=original_owner
    body['params']['dataset']=foreign['id']
    assert client.post(url+'/preview',json=body).json()['error']=='dataset_not_found'
    assert client.get(url).json()['revision']==undone['revision']

def test_operation_parameter_size_rejection_is_atomic(client,data):
    d=upload(client,data);url=f'/api/datasets/{d["id"]}'
    r=client.post(url+'/operations',json={'operation':'sample','revision':0,'params':{'n':1,'unused':'x'*65537}})
    assert r.status_code==422 and client.get(url).json()['revision']==0

def test_aggregated_time_rows_do_not_report_unrelated_cell_differences(client):
    d=upload(client,pd.DataFrame({'date':['2025-01-01','2025-01-01','2025-01-02'],'v':[1.,3.,8.]}));url=f'/api/datasets/{d["id"]}'
    body={'operation':'rolling','revision':0,'params':{'time':'date','field':'v','name':'roll','duplicates':'mean','window':1,'minPeriods':1}}
    p=client.post(url+'/preview',json=body).json()
    assert p['diff']['rowsAfter']==2 and p['diff']['modifiedCells']==0 and p['diff']['affectedRows']==3
    assert p['after']['rows'][0]['v']==2 and p['after']['rows'][1]['v']==8
    applied=client.post(url+'/operations',json=body).json();assert applied['overview']==p['overview']
