from __future__ import annotations
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.packages'))
import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Header, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from . import engine as e
from . import storage as s

s.init()
app = FastAPI(title='Visual Pandas Studio', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('VPS_CORS_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173').split(','), allow_methods=['GET','POST','PUT','DELETE'], allow_headers=['Content-Type','X-Studio-Session'])

def owner(x_studio_session: str = Header(default='')):
    if not re.fullmatch(r'[a-f0-9-]{36}', x_studio_session):
        raise e.DataError('session_required')
    return x_studio_session

@app.exception_handler(e.DataError)
async def data_error(_, exc):
    return JSONResponse(status_code=404 if exc.code == 'dataset_not_found' else 400, content={'error': exc.code, 'details': e.clean(exc.details)})

@app.exception_handler(RequestValidationError)
async def validation_error(_, exc):
    return JSONResponse(status_code=422, content={'error': 'invalid_value'})

@app.exception_handler(ValueError)
@app.exception_handler(TypeError)
@app.exception_handler(KeyError)
async def value_error(_, exc):
    return JSONResponse(status_code=400, content={'error': 'invalid_value'})

class Operation(BaseModel):
    operation: str = Field(min_length=1,max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)
    revision: int

    @field_validator('params')
    @classmethod
    def bounded_params(cls,value):
        if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))>65536:
            raise ValueError('parameters too large')
        return value

class Analysis(BaseModel):
    kind: str = 'describe'
    spec: dict[str, Any] = Field(default_factory=dict)
    selection: list[int] | None = None
    field: str | None = None
    group: str | None = None
    test: str | None = None
    method: str = 'iqr'
    threshold: float = 1.5
    lower: float | None = None
    upper: float | None = None
    categories: list[str] | None = None
    includeUpper: bool = False
    temporal: bool = False
    revision: int | None = None

def validate_frame(df, *, infer_dates=True, reset_index=True):
    if not len(df.columns) or len(df) > int(os.getenv('VPS_MAX_ROWS','100000')) or len(df.columns) > int(os.getenv('VPS_MAX_COLUMNS','200')):
        raise e.DataError('result_too_large')
    df.columns = [str(c).strip() for c in df.columns]
    if df.columns.duplicated().any() or any(not c or len(c)>100 for c in df.columns):
        raise e.DataError('duplicate_columns')
    df = df.replace([float('inf'),-float('inf')], float('nan'))
    for c in df:
        if infer_dates and e.kind(df[c]) == 'text':
            nonnull = df[c].dropna()
            if len(nonnull) and nonnull.astype(str).str.match(r'^\d{4}-\d{2}-\d{2}').all():
                converted = pd.to_datetime(df[c], errors='coerce', format='mixed')
                if converted.notna().sum()==len(nonnull):
                    df[c]=converted
    if not reset_index and (not df.index.is_unique or any(type(i) is not int or abs(i)>2**53 for i in df.index.tolist())):
        raise e.DataError('invalid_value')
    return df.reset_index(drop=True) if reset_index else df

def validate_project(value):
    if not isinstance(value,dict):
        raise e.DataError('invalid_value')
    charts=value.get('charts',[])
    if not isinstance(charts,list) or len(charts)>12 or len(json.dumps(value))>250000:
        raise e.DataError('result_too_large')
    for chart in charts:
        if not isinstance(chart,dict) or any(not isinstance(chart.get(key),str) for key in ['id','type','x','agg','title']):
            raise e.DataError('invalid_value')
        if chart['type'] not in {'bar','line','scatter','area','histogram','pie','box','heatmap','bubble','violin','kde'}:
            raise e.DataError('invalid_value')
        for key in ['y','color','size','group','primary','secondary','sort','method','width']:
            if key in chart and not isinstance(chart[key],str):
                raise e.DataError('invalid_value')
        if 'tooltip' in chart and (not isinstance(chart['tooltip'],list) or any(not isinstance(x,str) for x in chart['tooltip'])):
            raise e.DataError('invalid_value')
        if 'bins' in chart and (type(chart['bins']) is not int or not 3<=chart['bins']<=60):
            raise e.DataError('invalid_value')
    if len({c['id'] for c in charts})!=len(charts):
        raise e.DataError('invalid_value')
    report=value.get('report',{})
    if not isinstance(report,dict) or any(not isinstance(report.get(k,''),str) for k in ['title','notes']):
        raise e.DataError('invalid_value')
    if not isinstance(report.get('hidden',[]),list) or any(not isinstance(x,str) for x in report.get('hidden',[])):
        raise e.DataError('invalid_value')
    return value

async def read_file(file):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in {'.csv','.xlsx','.xls'}:
        raise e.DataError('file_format')
    limit=int(os.getenv('VPS_MAX_UPLOAD_MB','20'))*1024*1024
    data=await file.read(limit+1)
    if len(data)>limit:
        raise e.DataError('file_too_large')
    if suffix=='.xlsx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(f.file_size for f in archive.infolist())>100*1024*1024:
                    raise e.DataError('file_too_large')
        except zipfile.BadZipFile:
            raise e.DataError('parse_failed')
    return data,suffix

@app.get('/api/health')
def health():
    return {'status':'ok','engine':'pandas','pandas':pd.__version__}

@app.get('/api/datasets')
def datasets(user=Depends(owner)):
    with s.transaction() as db:
        return [{'id':r['id'],'name':r['name'],'source':r['source']} for r in db.execute('SELECT id,name,source FROM datasets WHERE owner=? ORDER BY updated DESC',(user,))]

@app.post('/api/samples/{sample}')
def sample_dataset(sample:str,user=Depends(owner)):
    if sample not in {'iris','titanic','sales'}:
        raise e.DataError('invalid_dataset')
    df=validate_frame(pd.read_csv(Path(__file__).resolve().parents[1]/'data'/f'{sample}.csv'))
    with s.transaction() as db:
        return s.create(db,user,{'iris':'Iris','titanic':'Titanic','sales':'Sales'}[sample],sample,df)

@app.post('/api/upload/sheets')
async def sheets(file:UploadFile=File(...),user=Depends(owner)):
    data,suffix=await read_file(file)
    if suffix=='.csv':
        return {'sheets':[]}
    try:
        with pd.ExcelFile(io.BytesIO(data),engine='xlrd' if suffix=='.xls' else 'openpyxl') as book:
            return {'sheets':book.sheet_names}
    except ImportError:
        raise e.DataError('dependency_missing')
    except Exception:
        raise e.DataError('parse_failed')

@app.post('/api/upload')
async def upload(file:UploadFile=File(...),encoding:str=Form('utf-8-sig'),delimiter:str=Form(','),sheet:str=Form(''),user=Depends(owner)):
    data,suffix=await read_file(file)
    try:
        if suffix=='.csv':
            if encoding not in {'utf-8-sig','gb18030','latin1','utf-16'} or delimiter not in {',',';','\t','|'}:
                raise e.DataError('invalid_value')
            import csv
            header=next(csv.reader(io.StringIO(data.decode(encoding)),delimiter=delimiter))
            if len(header)!=len(set(header)):
                raise e.DataError('duplicate_columns')
            df=pd.read_csv(io.BytesIO(data),encoding=encoding,sep=delimiter,nrows=int(os.getenv('VPS_MAX_ROWS','100000'))+1)
        else:
            df=pd.read_excel(io.BytesIO(data),sheet_name=sheet or 0,engine='xlrd' if suffix=='.xls' else 'openpyxl',nrows=int(os.getenv('VPS_MAX_ROWS','100000'))+1)
        df=validate_frame(df)
    except e.DataError:
        raise
    except ImportError:
        raise e.DataError('dependency_missing')
    except Exception:
        raise e.DataError('parse_failed')
    with s.transaction() as db:
        return s.create(db,user,Path(file.filename or 'Dataset').name,'upload',df)

@app.get('/api/datasets/{ident}')
def dataset(ident:str,user=Depends(owner)):
    with s.transaction() as db:
        return s.summary(db,s.record(db,user,ident))

@app.delete('/api/datasets/{ident}')
def delete_dataset(ident:str,user=Depends(owner)):
    with s.transaction() as db:
        s.record(db,user,ident)
        db.execute('DELETE FROM datasets WHERE id=?',(ident,))
    return {'ok':True}

@app.get('/api/datasets/{ident}/table')
def dataset_table(ident:str,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),search:str='',sort:str='',desc:bool=False,ids:str='',selection_active:bool=False,user=Depends(owner)):
    with s.transaction() as db:
        df=s.current(db,s.record(db,user,ident))
    if selection_active:
        df=df.loc[df.index.isin([int(x) for x in ids.split(',') if x])]
    if search:
        df=df.loc[df.astype('string').apply(lambda x:x.str.contains(search,case=False,regex=False,na=False)).any(axis=1)]
    if sort:
        e.check_columns(df,[sort])
        df=df.sort_values(sort,ascending=not desc,kind='stable')
    return e.table(df,offset,limit)

@app.post('/api/datasets/{ident}/table')
def selected_table(ident:str, payload:dict, user=Depends(owner)):
    offset, limit = int(payload.get('offset',0)), int(payload.get('limit',25))
    if offset < 0 or limit < 1 or limit > 100 or len(payload.get('ids',[])) > 5000:
        raise e.DataError('invalid_value')
    with s.transaction() as db:
        df=s.current(db,s.record(db,user,ident))
    if payload.get('selection_active'):
        df=df.loc[df.index.isin(payload.get('ids',[]))]
    if payload.get('search'):
        df=df.loc[df.astype('string').apply(lambda x:x.str.contains(str(payload['search']),case=False,regex=False,na=False)).any(axis=1)]
    if payload.get('sort'):
        e.check_columns(df,[payload['sort']])
        df=df.sort_values(payload['sort'],ascending=not payload.get('desc',False),kind='stable')
    return e.table(df,offset,limit)

def operation_data(db,user,ident,req,preview):
    rec=s.record(db,user,ident)
    if req.revision!=rec['revision']:
        raise e.DataError('stale_revision')
    before=s.current(db,rec)
    other=None
    if req.operation in {'join','concat','compare','update','combine_first','merge_asof'}:
        other_rec=s.record(db,user,req.params['dataset'])
        if req.params.get('otherRevision',other_rec['revision'])!=other_rec['revision']:
            raise e.DataError('stale_revision')
        other=s.current(db,other_rec)
    after,warnings=e.apply_operation(before,req.operation,req.params,other,preview)
    return rec,before,after,warnings

@app.post('/api/datasets/{ident}/preview')
def preview(ident:str,req:Operation,user=Depends(owner)):
    with s.transaction() as db:
        _,before,after,warnings=operation_data(db,user,ident,req,True)
    aligned=req.operation not in {'group','pivot','melt','stack','unstack','pivot_strict','explode','resample','time_gaps','join','concat','merge_asof','combine_first'} and not (req.operation=='sample' and req.params.get('replace'))
    # Aggregating duplicate timestamps creates a new row identity space.
    if req.operation in {'rolling','ewm','growth'} and req.params.get('duplicates') in {'mean','sum'}:
        aligned=False
    return {'before':e.table(before,0,8),'after':e.table(after,0,8),'diff':e.differences(before,after,aligned),'warnings':warnings,'overview':e.overview(after),'visual':after.attrs.get('visual',{}),'revision':req.revision}

@app.post('/api/datasets/{ident}/operations')
def operate(ident:str,req:Operation,user=Depends(owner)):
    if req.operation=='compare':raise e.DataError('read_only_operation')
    with s.transaction() as db:
        rec,_,after,_=operation_data(db,user,ident,req,False)
        return s.commit(db,rec,after,req.operation,req.params,req.revision)

@app.post('/api/datasets/{ident}/history/{action}')
def history(ident:str,action:str,payload:dict,user=Depends(owner)):
    with s.transaction() as db:
        rec=s.record(db,user,ident)
        if payload.get('revision')!=rec['revision']:
            raise e.DataError('stale_revision')
        maximum=db.execute('SELECT MAX(step) FROM snapshots WHERE dataset=?',(ident,)).fetchone()[0]
        if action=='undo' and rec['cursor']>0:
            cursor=rec['cursor']-1
        elif action=='redo' and rec['cursor']<maximum:
            cursor=rec['cursor']+1
        elif action=='reset':
            return s.commit(db,rec,e.unpack(rec['original']),'reset',{},rec['revision'])
        else:
            raise e.DataError('invalid_operation')
        db.execute('UPDATE datasets SET cursor=?,revision=revision+1 WHERE id=?',(cursor,ident))
        rec.update(cursor=cursor,revision=rec['revision']+1)
        return s.summary(db,rec)

@app.post('/api/datasets/{ident}/analysis')
def analysis(ident:str,req:Analysis,user=Depends(owner)):
    with s.transaction() as db:
        rec=s.record(db,user,ident)
        if req.revision is not None and req.revision!=rec['revision']:
            raise e.DataError('stale_revision')
        df=s.current(db,rec)
    return e.analyze(df,req.model_dump(exclude_none=True))

@app.put('/api/datasets/{ident}/project')
def project(ident:str,payload:dict,user=Depends(owner)):
    project_data=validate_project(payload.get('project',{}))
    with s.transaction() as db:
        rec=s.record(db,user,ident)
        if payload.get('revision')!=rec['revision']:
            raise e.DataError('stale_revision')
        db.execute('UPDATE datasets SET project=?,revision=revision+1 WHERE id=?',(json.dumps(project_data,ensure_ascii=False),ident))
        return s.summary(db,s.record(db,user,ident))

@app.get('/api/datasets/{ident}/export/{format}')
def export(ident:str,format:str,user=Depends(owner)):
    with s.transaction() as db:
        rec=s.record(db,user,ident)
        df=s.current(db,rec)
        info=s.summary(db,rec,df)
        snapshots=[dict(r) for r in db.execute('SELECT step,data,operation,params,created FROM snapshots WHERE dataset=? ORDER BY step',(ident,))] if format=='json' else []
    if format=='csv':
        return Response(df.to_csv(index=False).encode('utf-8-sig'),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="dataset.csv"'})
    if format=='xlsx':
        stream=io.BytesIO()
        with pd.ExcelWriter(stream,engine='openpyxl') as writer:
            df.to_excel(writer,index=False)
            for row in writer.sheets['Sheet1'].iter_rows():
                for cell in row:
                    if isinstance(cell.value,str):
                        cell.data_type='s'
        return Response(stream.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="dataset.xlsx"'})
    if format=='json':
        for item in snapshots:
            item['data']=json.loads(item['data'])
            item['params']=json.loads(item['params'])
        obj={'format':'visual-pandas-studio/v1','dataset':info,'original':json.loads(rec['original']),'current':json.loads(e.pack(df)),'snapshots':snapshots}
        return Response(json.dumps(obj,ensure_ascii=False,allow_nan=False).encode(),media_type='application/json',headers={'Content-Disposition':'attachment; filename="analysis-project.json"'})
    raise e.DataError('file_format')

@app.post('/api/projects/import')
async def import_project(file:UploadFile=File(...),user=Depends(owner)):
    raw=await file.read(20*1024*1024+1)
    if len(raw)>20*1024*1024:
        raise e.DataError('file_too_large')
    try:
        obj=json.loads(raw)
        if obj['format']!='visual-pandas-studio/v1':
            raise e.DataError('file_format')
        original=validate_frame(e.unpack(json.dumps(obj['original'])),infer_dates=False,reset_index=False)
        current=validate_frame(e.unpack(json.dumps(obj['current'])),infer_dates=False,reset_index=False)
        project_obj=validate_project(obj['dataset'].get('project',{}))
        imported=obj.get('snapshots')
        cursor=obj['dataset'].get('cursor',0)
        if imported is not None:
            if not isinstance(imported,list) or not 1<=len(imported)<=int(os.getenv('VPS_MAX_HISTORY','30'))+1:
                raise e.DataError('history_limit')
            if type(cursor) is not int or not 0<=cursor<len(imported):
                raise e.DataError('invalid_value')
            validated=[]
            for step,item in enumerate(imported):
                if item['step']!=step or not isinstance(item['operation'],str) or len(item['operation'])>100 or not isinstance(item['params'],dict):
                    raise e.DataError('invalid_value')
                frame=validate_frame(e.unpack(json.dumps(item['data'])),infer_dates=False,reset_index=False)
                validated.append((step,e.pack(frame),item['operation'],json.dumps(item['params'],ensure_ascii=False),float(item['created'])))
            if e.pack(current)!=validated[cursor][1] or e.pack(original)!=validated[0][1]:
                raise e.DataError('invalid_value')
        with s.transaction() as db:
            info=s.create(db,user,obj['dataset']['name'],'project',original)
            rec=s.record(db,user,info['id'])
            if imported is None:
                s.commit(db,rec,current,'restore_project',{},0)
            else:
                db.execute('DELETE FROM snapshots WHERE dataset=?',(rec['id'],))
                db.executemany('INSERT INTO snapshots VALUES(?,?,?,?,?,?)',[(rec['id'],*item) for item in validated])
                db.execute('UPDATE datasets SET cursor=? WHERE id=?',(cursor,rec['id']))
            db.execute('UPDATE datasets SET project=? WHERE id=?',(json.dumps(project_obj),rec['id']))
            return s.summary(db,s.record(db,user,rec['id']))
    except e.DataError:
        raise
    except Exception:
        raise e.DataError('parse_failed')
