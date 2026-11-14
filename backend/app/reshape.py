"""Reshape and feature engineering with flat, serializable result columns."""
import json
import numpy as np
import pandas as pd
from .engine import DataError,check_columns,numeric,clean,kind
from .extensions import columns,choice,flag,integer,output,ordered

OPERATIONS={'melt','pivot_strict','stack','unstack','explode','dummies','group_transform','window_calc'}

def field_name(p,key,default,existing):
    value=p.get(key,default)
    if not isinstance(value,str):raise DataError('invalid_name')
    value=value.strip()
    if not value or len(value)>100 or value in existing:raise DataError('invalid_name')
    return value

def hierarchy(df,fields):
    tree={}
    for row in df[fields].head(50).itertuples(index=False,name=None):
        node=tree
        for value in row:
            key=str(value)
            node=node.setdefault(key,{})
    return tree

def flat(df):
    df=df.reset_index()
    df.columns=[' | '.join(str(v) for v in c if str(v)!='') if isinstance(c,tuple) else str(c) for c in df.columns]
    if any(len(c)>100 for c in df):raise DataError('invalid_name')
    return df

def apply(df,op,p):
    result=df.copy();visual={}
    if op in {'melt','stack'}:
        ids=columns(df,p,'ids',required=False);values=columns(df,p,'values')
        if set(ids)&set(values):raise DataError('overlapping_fields')
        if len(df)*len(values)>100000:raise DataError('result_too_large')
        variable=field_name(p,'variableName','variable',list(df.columns));value=field_name(p,'valueName','value',list(df.columns)+[variable])
        if op=='melt':result=df.melt(id_vars=ids,value_vars=values,var_name=variable,value_name=value)
        else:
            if not ids:raise DataError('invalid_field')
            indexed=df.set_index(ids)[values].rename_axis(columns=variable)
            result=indexed.stack(future_stack=True).rename(value).reset_index()
            visual['hierarchy']=hierarchy(result,ids+[variable])
        visual['sourceRows']=len(df)
    elif op in {'pivot_strict','unstack'}:
        ids=columns(df,p,'ids');values=columns(df,p,'values');levels=columns(df,p,'levels')
        if set(ids)&set(values) or set(values)&set(levels):raise DataError('overlapping_fields')
        index=list(dict.fromkeys(ids+levels))
        if df.duplicated(index).any():raise DataError('duplicate_index')
        level_count=len(df[levels].drop_duplicates())
        if level_count*len(values)+len(ids)>200 or len(df[ids].drop_duplicates())*max(1,level_count)*len(values)>2000000:raise DataError('result_too_large')
        if op=='pivot_strict':
            if set(ids)&set(levels):raise DataError('overlapping_fields')
            result=df.pivot(index=ids,columns=levels,values=values)
        else:
            if not set(levels)<set(ids):raise DataError('index_levels')
            result=df.set_index(ids)[values].unstack(level=levels)
        result=flat(result);visual['hierarchy']=hierarchy(df,index)
    elif op=='explode':
        c=p.get('field');check_columns(df,[c]);mode=choice(p,'mode',{'json','delimiter'},'json');delimiter=p.get('delimiter',',')
        if mode=='delimiter' and (not isinstance(delimiter,str) or not 1<=len(delimiter)<=10):raise DataError('invalid_value')
        def parse(v):
            if v is None or v is pd.NA or isinstance(v,float) and np.isnan(v):return v
            if isinstance(v,list):items=v
            elif mode=='delimiter':items=str(v).split(delimiter)
            else:
                try:items=json.loads(v)
                except (ValueError,TypeError):raise DataError('list_required')
            if not isinstance(items,list) or len(items)>1000 or any(isinstance(x,(dict,list)) for x in items):raise DataError('list_required')
            return items
        result[c]=result[c].map(parse)
        if int(result[c].map(lambda v:max(1,len(v)) if isinstance(v,list) else 1).sum())>100000:raise DataError('result_too_large')
        source=field_name(p,'sourceName','source_row',list(df.columns));result[source]=df.index
        result=result.explode(c,ignore_index=True)
        visual['hierarchy']={str(i):{'expandedRows':int(n)} for i,n in result[source].value_counts(sort=False).head(50).items()}
    elif op=='dummies':
        cols=columns(df,p,'columns');drop=flag(p,'dropFirst');missing=flag(p,'dummyNa');retain=flag(p,'retain')
        generated=sum(df[c].nunique() + int(missing)-int(drop) for c in cols)
        if generated+len(df.columns)-(0 if retain else len(cols))>200 or generated*len(df)>10000000:raise DataError('result_too_large')
        encoded=pd.get_dummies(df[cols].astype('string'),columns=cols,drop_first=drop,dummy_na=missing,dtype=int)
        result=pd.concat([df if retain else df.drop(columns=cols),encoded],axis=1)
        if any(len(c)>100 for c in result):raise DataError('invalid_name')
        visual['encoding']={'columns':encoded.columns.tolist(),'rows':encoded.head(20).values.tolist()}
    elif op=='group_transform':
        groups=columns(df,p,'groups');c=p.get('field');numeric(df,c);name=output(df,p);method=choice(p,'method',{'mean','min','max','zscore','rank'},'mean')
        grouped=df.groupby(groups,dropna=False,observed=True)[c]
        if method=='zscore':out=(df[c]-grouped.transform('mean'))/grouped.transform('std').replace(0,np.nan)
        elif method=='rank':out=grouped.rank(method=choice(p,'rankMethod',{'average','min','max','first','dense'},'average'),ascending=flag(p,'ascending',True))
        else:out=grouped.transform(method)
        result[name]=out
        visual['hierarchy']=hierarchy(df,groups)
        means=result.groupby(groups,dropna=False,observed=True)[[c,name]].mean().head(60)
        visual['groupComparison']={'labels':[str(v) for v in means.index],'original':clean(means[c].tolist()),'values':clean(means[name].tolist())}
    elif op=='window_calc':
        c=p.get('field');numeric(df,c);name=output(df,p);method=choice(p,'method',{'rank','diff','shift','pct_change'},'rank');result=ordered(df,p);lag=integer(p,'periods',1,-1000,1000)
        if method=='rank':result[name]=result[c].rank(method=choice(p,'rankMethod',{'average','min','max','first','dense'},'average'),ascending=flag(p,'ascending',True),pct=flag(p,'percentile'))
        elif method=='pct_change':result[name]=result[c].pct_change(periods=lag,fill_method=None).replace([np.inf,-np.inf],np.nan)
        else:result[name]=getattr(result[c],method)(periods=lag)
    else:raise DataError('invalid_operation')
    if op in {'melt','pivot_strict','stack','unstack'}:result=result.reset_index(drop=True)
    if op in {'group_transform','window_calc'}:
        name=str(p['name']).strip();c=p['field'];part=result.head(300)
        visual.update(labels=[str(v) for v in part[p['sort']]] if p.get('sort') in part else [str(i+1) for i in part.index],original=clean(part[c].tolist()),values=clean(part[name].tolist()))
    result.attrs['visual']=clean(visual)
    return result,[]
