"""Validated, reproducible operations shared by preview and commit."""
from __future__ import annotations
import json
import re
import math
import warnings
import numpy as np
import pandas as pd
from .engine import DataError, check_columns, numeric, kind, clean

OPERATIONS = {'sample','topn','bin','mapping','string','date','cumulative','interpolate','select_rows'}

def choice(p, key, allowed, default=None):
    value=p.get(key,default)
    if value not in allowed:
        raise DataError('invalid_method', {'parameter':key})
    return value

def integer(p, key, default, low=0, high=100000):
    v=p.get(key,default)
    if type(v) is not int or not low<=v<=high:
        raise DataError('invalid_value', {'parameter':key})
    return v

def number(p,key,default,low=-1e100,high=1e100):
    v=p.get(key,default)
    if type(v) not in {int,float} or not math.isfinite(v) or not low<=v<=high:
        raise DataError('invalid_value', {'parameter':key})
    return float(v)

def flag(p,key,default=False):
    v=p.get(key,default)
    if type(v) is not bool:
        raise DataError('invalid_value', {'parameter':key})
    return v

def columns(df,p,key,required=True):
    v=p.get(key,[])
    if not isinstance(v,list) or any(not isinstance(c,str) for c in v) or len(set(v))!=len(v):
        raise DataError('invalid_field')
    if v or required:
        check_columns(df,v)
    return v

def output(df,p,source=None):
    name=p.get('name','')
    if not isinstance(name,str):raise DataError('invalid_name')
    name=name.strip()
    if not name or len(name)>100 or name in df and not (flag(p,'overwrite') and name==source):
        raise DataError('invalid_name')
    return name

def ordered(df,p):
    sort=p.get('sort','')
    if sort:
        check_columns(df,[sort])
        return df.sort_values(sort,ascending=flag(p,'ascending',True),kind='stable')
    return df.copy()

def dates(s,p):
    fmt=p.get('format','')
    if not isinstance(fmt,str) or len(fmt)>100:
        raise DataError('invalid_value')
    utc=choice(p,'timezone',{'utc','naive'},'utc')=='utc'
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',FutureWarning)
            result=pd.to_datetime(s,errors='coerce',format=fmt or 'mixed',utc=utc)
        if not pd.api.types.is_datetime64_any_dtype(result):
            raise DataError('timezone_required')
        return result
    except (ValueError,TypeError,FutureWarning):
        raise DataError('timezone_required')

def invalid_dates(s,parsed,p,preview):
    failed=s.notna() & parsed.isna()
    if failed.any() and not preview and not flag(p,'coerce'):
        raise DataError('conversion_failed',{'count':int(failed.sum())})
    return [{'code':'conversion_failed','count':int(failed.sum()),'examples':clean(s[failed].head(5).tolist()),'ids':s.index[failed][:100].tolist()}] if failed.any() else []

def safe_pattern(pattern,s):
    # Deliberately bounded subset: no groups, alternation or backreferences.
    if not isinstance(pattern,str) or len(pattern)>128:
        raise DataError('invalid_regex')
    try:
        re.compile(pattern)
    except re.error:
        raise DataError('invalid_regex')
    if re.search(r'(?<!\\)[()|]',pattern) or re.search(r'\\[1-9]',pattern) or len(re.findall(r'(?<!\\)(?:[*+?]|\{\d+(?:,\d*)?\})',pattern))>1 or any(int(v)>100 for v in re.findall(r'\d+', ''.join(re.findall(r'\{[^}]*\}',pattern)))):
        raise DataError('regex_restricted')
    lengths=s.str.len().fillna(0)
    if lengths.max()>2000 or lengths.sum()>2000000:
        raise DataError('regex_restricted')
    return pattern

def cast_key(value,s):
    if value is None:
        return None
    if kind(s)=='number':
        try:
            value=float(value)
            if not math.isfinite(value):raise ValueError()
            return value
        except (ValueError,TypeError):raise DataError('invalid_value')
    if kind(s)=='boolean':
        if value in [True,'true','True','1']:return True
        if value in [False,'false','False','0']:return False
        raise DataError('invalid_value')
    return str(value)

def apply(df,op,p,preview=False):
    result=df.copy(deep=True); warnings=[]; visual={}
    if op=='select_rows':
        ids=p.get('ids')
        if not isinstance(ids,list) or len(ids)>5000 or any(type(i) is not int for i in ids) or not set(ids)<=set(df.index):
            raise DataError('invalid_value')
        result=df.loc[df.index.isin(ids)].copy()
    elif op=='sample':
        mode=choice(p,'mode',{'count','fraction'},'fraction')
        seed=integer(p,'seed',42,0,2**32-1)
        replace=flag(p,'replace'); group=p.get('group','')
        kwargs={'random_state':seed,'replace':replace}
        if mode=='count':kwargs['n']=integer(p,'n',min(10,len(df)))
        else:kwargs['frac']=number(p,'fraction',.2,0,10 if replace else 1)
        if group:
            check_columns(df,[group])
            sizes=df.groupby(group,dropna=False,observed=True).size()
            estimated=len(sizes)*kwargs['n'] if mode=='count' else int(sizes.mul(kwargs['frac']).round().sum())
            if estimated>100000:raise DataError('result_too_large')
            parts=[]
            for _,frame in df.groupby(group,dropna=False,observed=True,sort=False):
                if mode=='count' and not replace and kwargs['n']>len(frame):raise DataError('sample_size')
                parts.append(frame.sample(**kwargs))
            result=pd.concat(parts) if parts else df.iloc[:0].copy()
        else:
            if not replace and kwargs.get('n',0)>len(df) or df.empty and (kwargs.get('n',0)>0):raise DataError('sample_size')
            estimate=kwargs.get('n',round(len(df)*kwargs.get('frac',1)))
            if estimate>100000:raise DataError('result_too_large')
            result=df.sample(**kwargs)
        visual={'sourceIds':result.index[:100].tolist(),'sampleRows':len(result)}
        if replace:result=result.reset_index(drop=True)
    elif op=='topn':
        c=p.get('field');numeric(df,c)
        n=integer(p,'n',10,1);direction=choice(p,'direction',{'largest','smallest'},'largest');keep=choice(p,'keep',{'first','last','all'},'first')
        result=getattr(df,'nlargest' if direction=='largest' else 'nsmallest')(n,c,keep=keep)
        visual={'labels':[str(i+1) for i in result.index[:60]],'values':clean(result[c].head(60).tolist())}
    elif op=='bin':
        c=p.get('field');numeric(df,c);name=output(df,p);method=choice(p,'method',{'cut','qcut','custom'},'cut')
        bins=integer(p,'bins',5,2,60);labels=p.get('labels') or None
        if labels is not None and (not isinstance(labels,list) or len(set(labels))!=len(labels) or any(not isinstance(v,str) for v in labels)):raise DataError('bin_labels')
        if df[c].notna().sum()==0:raise DataError('all_missing')
        try:
            if method=='qcut':
                duplicates=choice(p,'duplicates',{'drop','raise'},'drop')
                binned,edges=pd.qcut(df[c],q=bins,labels=labels,retbins=True,duplicates=duplicates)
            else:
                edges=p.get('edges',[]) if method=='custom' else bins
                if method=='custom' and (not isinstance(edges,list) or not 2<=len(edges)<=61 or any(type(v) not in {int,float} or not math.isfinite(v) for v in edges) or any(a>=b for a,b in zip(edges,edges[1:]))):raise DataError('bin_edges')
                binned,edges=pd.cut(df[c],bins=edges,labels=labels,retbins=True,right=flag(p,'right',True),include_lowest=flag(p,'includeLowest',True))
        except ValueError as ex:
            raise DataError('bin_labels' if labels else 'bin_edges',str(ex)[:200])
        result[name]=binned.astype('string')
        counts=binned.value_counts(sort=False)
        hist,hist_edges=np.histogram(df[c].dropna(),bins=30)
        visual={'edges':edges.tolist(),'labels':[str(v) for v in counts.index],'counts':counts.tolist(),'unassigned':int(binned.isna().sum()),'hist':hist.tolist(),'histEdges':hist_edges.tolist(),'field':c}
    elif op=='mapping':
        c=p.get('field');check_columns(df,[c]);name=output(df,p,c);mode=choice(p,'method',{'map','replace'},'map');unmatched=choice(p,'unmatched',{'keep','missing'},'keep')
        pairs=p.get('pairs',[])
        if not isinstance(pairs,list) or not 1<=len(pairs)<=100 or any(not isinstance(row,dict) or set(row)!={'from','to'} or any(type(v) not in {str,int,float,bool,type(None)} or type(v) is float and not math.isfinite(v) or isinstance(v,str) and len(v)>2000 for v in row.values()) for row in pairs):raise DataError('invalid_value')
        mapping={};missing_value=None;has_missing=False
        for pair in pairs:
            key=cast_key(pair['from'],df[c])
            if key is None:
                if has_missing:raise DataError('duplicate_mapping')
                has_missing=True;missing_value=pair['to']
            else:
                if key in mapping:raise DataError('duplicate_mapping')
                mapping[key]=pair['to']
        s=df[c];out=s.map(mapping).astype(object)
        if mode=='replace':
            out=s.astype(object).replace(mapping)
        elif unmatched=='keep':out=out.where(s.isin(mapping),s.astype(object))
        if has_missing:out.loc[s.isna()]=missing_value
        result[name]=out
        visual={'pairs':pairs,'uniqueBefore':int(s.nunique()),'uniqueAfter':int(out.nunique()),'unmatched':int((s.notna() & ~s.isin(mapping)).sum())}
    elif op=='string':
        c=p.get('field');check_columns(df,[c])
        if kind(df[c])!='text':raise DataError('text_required')
        name=output(df,p,c);s=df[c].astype('string');method=choice(p,'method',{'strip','lower','upper','len','contains','startswith','endswith','replace','split','match'},'strip');pattern=p.get('pattern','');regex=flag(p,'regex')
        if not isinstance(pattern,str) or len(pattern)>500:raise DataError('invalid_value')
        if regex or method=='match':pattern=safe_pattern(pattern,s)
        if method in {'strip','lower','upper','len'}:out=getattr(s.str,method)()
        elif method=='contains':out=s.str.contains(pattern,regex=regex,case=flag(p,'case',True),na=pd.NA)
        elif method in {'startswith','endswith'}:out=getattr(s.str,method)(pattern,na=pd.NA)
        elif method=='match':out=s.str.match(pattern,case=flag(p,'case',True),na=pd.NA)
        elif method=='replace':
            replacement=p.get('replacement','')
            if not isinstance(replacement,str) or len(replacement)>500:raise DataError('invalid_value')
            try:out=s.str.replace(pattern,replacement,regex=regex)
            except (re.error,IndexError):raise DataError('invalid_regex')
        else:
            if not pattern:raise DataError('invalid_value')
            parts=s.str.split(pattern,regex=regex,n=integer(p,'splits',10,1,100))
            out=parts.map(lambda v: json.dumps(v,ensure_ascii=False) if isinstance(v,list) else pd.NA).astype('string')
        result[name]=out
    elif op=='date':
        c=p.get('field');check_columns(df,[c]);s=dates(df[c],p);warnings=invalid_dates(df[c],s,p,preview)
        method=choice(p,'method',{'parse','year','month','day','dayofweek','quarter','difference','sort','range'},'parse')
        if method=='sort':
            result[c]=s;result=result.sort_values(c,ascending=flag(p,'ascending',True),kind='stable')
        elif method=='range':
            low=dates(pd.Series([p.get('start')]),p).iloc[0];high=dates(pd.Series([p.get('end')]),p).iloc[0]
            if pd.isna(low) or pd.isna(high) or low>high:raise DataError('invalid_range')
            result=result.loc[s.between(low,high)]
        else:
            name=output(df,p,c)
            if method=='parse':out=s
            elif method=='difference':
                other=p.get('other');check_columns(df,[other]);other_date=dates(df[other],p);warnings+=invalid_dates(df[other],other_date,p,preview)
                unit=choice(p,'unit',{'days','hours','seconds'},'days');out=(s-other_date).dt.total_seconds()/({'days':86400,'hours':3600,'seconds':1}[unit])
            else:out=getattr(s.dt,method)
            result[name]=out
        grouped=s.dropna().dt.floor('D').value_counts().sort_index()
        visual={'labels':[str(v) for v in grouped.index[:300]],'values':grouped.iloc[:300].tolist(),'invalidIds':[i for w in warnings for i in w.get('ids',[])]}
    elif op=='cumulative':
        c=p.get('field');numeric(df,c);name=output(df,p);method=choice(p,'method',{'cumsum','cumprod','cummin','cummax'},'cumsum')
        result=ordered(df,p);result[name]=getattr(result[c],method)(skipna=flag(p,'skipna',True))
    elif op=='interpolate':
        c=p.get('field');numeric(df,c);name=output(df,p,c);method=choice(p,'method',{'linear','time','ffill','bfill'},'linear');result=ordered(df,p)
        s=result[c].astype(float)
        if method=='time':
            time=p.get('time');check_columns(df,[time]);parsed=dates(result[time],p);warnings=invalid_dates(result[time],parsed,p,preview)
            if parsed.isna().any():raise DataError('valid_time_required')
            if parsed.duplicated().any():raise DataError('duplicate_time')
            result=result.assign(**{time:parsed}).sort_values(time,kind='stable');s=pd.Series(result[c].to_numpy(),index=pd.DatetimeIndex(result[time]))
        if method in {'ffill','bfill'}:out=getattr(s,method)()
        else:out=s.interpolate(method=method,limit_area='inside' if flag(p,'inside',True) else None)
        result[name]=out.to_numpy()
    else:raise DataError('invalid_operation')
    numeric_name=p.get('name');numeric_name=numeric_name.strip() if isinstance(numeric_name,str) else None;c=p.get('field')
    if numeric_name in result and c in df and kind(result[numeric_name])=='number':
        part=result.head(300)
        axis=p.get('time') if op=='interpolate' and p.get('method')=='time' else p.get('sort')
        visual.update(labels=[str(v) for v in part[axis]] if axis in part else [str(i+1) for i in part.index],original=clean(df[c].reindex(part.index).tolist()),values=clean(part[numeric_name].tolist()),missingIds=clean(part.index[df[c].reindex(part.index).isna()].tolist()))
    result.attrs['visual']=clean(visual)
    return result,warnings
