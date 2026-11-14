"""Aligned comparison/update and sorted nearest-time matching."""
import numpy as np
import pandas as pd
from .engine import DataError,check_columns,numeric,clean,table,kind
from .extensions import choice,flag,columns,dates

OPERATIONS={'compare','update','combine_first','merge_asof'}

def quality(left,right,p,rows_after):
    lkey,rkey=p['left'],p['right'];check_columns(left,[lkey]);check_columns(right,[rkey])
    l=left.groupby(lkey,dropna=False).size().reset_index();l.columns=['key','left_count']
    r=right.groupby(rkey,dropna=False).size().reset_index();r.columns=['key','right_count']
    counts=l.merge(r,on='key',how='outer');both=counts.left_count.notna() & counts.right_count.notna()
    return {'matchedLeftRows':int(counts.loc[both,'left_count'].sum()),'matchedRightRows':int(counts.loc[both,'right_count'].sum()),'unmatchedLeftRows':int(counts.loc[counts.right_count.isna(),'left_count'].sum()),'unmatchedRightRows':int(counts.loc[counts.left_count.isna(),'right_count'].sum()),'duplicateLeftKeys':int(left[lkey].duplicated(keep=False).sum()),'duplicateRightKeys':int(right[rkey].duplicated(keep=False).sum()),'rowsAfterJoin':rows_after,'expansionRatio':round(rows_after/max(1,len(left)),3)}

def align(df,other,p):
    left,right=p.get('left'),p.get('right');check_columns(df,[left]);check_columns(other,[right])
    if df[left].isna().any() or other[right].isna().any():raise DataError('missing_join_key')
    if df[left].duplicated().any() or other[right].duplicated().any():raise DataError('unique_key_required')
    a=df.set_index(left);b=other.set_index(right);b.index.name=left
    cols=columns(a,p,'columns',required=False) or [c for c in a if c in b]
    check_columns(b,cols)
    if not cols:raise DataError('invalid_field')
    return a,b[cols].copy(),cols,left

def apply(df,op,p,other):
    if other is None:raise DataError('invalid_dataset')
    visual={}
    if op in {'compare','update','combine_first'}:
        a,b,cols,key=align(df,other,p);common=a.index.intersection(b.index,sort=False)
        if op=='compare':
            aa,bb=a.loc[common,cols],b.loc[common,cols]
            equal=(aa.eq(bb) | (aa.isna() & bb.isna())).fillna(False)
            changed=aa.compare(bb,result_names=('before','after'))
            changed.index.name=key;changed=changed.reset_index();changed.columns=[' | '.join(str(v) for v in c if v!='') if isinstance(c,tuple) else str(c) for c in changed.columns]
            visual.update(added=table(b.loc[b.index.difference(a.index)].reset_index(),limit=50),removed=table(a.loc[a.index.difference(b.index)].reset_index(),limit=50),changed=table(changed,limit=50),quality={'addedRows':len(b.index.difference(a.index)),'removedRows':len(a.index.difference(b.index)),'modifiedRecords':int((~equal).any(axis=1).sum()),'modifiedValues':int((~equal).sum().sum())})
            result=df.copy()
        else:
            for c in cols:
                if kind(a[c])=='number':
                    converted=pd.to_numeric(b[c],errors='coerce')
                    if (b[c].notna() & converted.isna()).any():raise DataError('numeric_required')
                    b[c]=converted
            if op=='update':
                result=a.copy();result.update(b,overwrite=flag(p,'overwrite',True))
                result=result.reset_index()[df.columns];result.index=df.index
            else:
                result=a.combine_first(b).reset_index()
            visual['quality']={'matchedLeftRows':len(common),'unmatchedLeftRows':len(a.index.difference(b.index)),'unmatchedRightRows':len(b.index.difference(a.index)),'rowsAfterJoin':len(result)}
    elif op=='merge_asof':
        left,right=p.get('left'),p.get('right');check_columns(df,[left]);check_columns(other,[right]);by=p.get('by') or None
        if by:check_columns(df,[by]);check_columns(other,[by])
        a,b=df.copy(),other.copy();a[left]=dates(a[left],p);b[right]=dates(b[right],p)
        invalid=choice(p,'invalid',{'reject','drop'},'reject')
        if (a[left].isna().any() or b[right].isna().any()) and invalid=='reject':raise DataError('valid_time_required')
        invalid_count=int(a[left].isna().sum()+b[right].isna().sum())
        a=a.dropna(subset=[left]);b=b.dropna(subset=[right]);dup=choice(p,'duplicates',{'reject','first','last'},'reject')
        subset=([by] if by else [])+[right]
        duplicate_count=int(b.duplicated(subset).sum())
        if b.duplicated(subset).any():
            if dup=='reject':raise DataError('duplicate_time')
            b=b.drop_duplicates(subset,keep=dup)
        marker='matched_time'
        while marker in a or marker in b:marker='_'+marker
        b[marker]=b[right];a=a.sort_values(left,kind='stable');b=b.sort_values(right,kind='stable')
        tolerance=p.get('tolerance','')
        if not isinstance(tolerance,str) or len(tolerance)>50:raise DataError('invalid_tolerance')
        try:
            delta=pd.Timedelta(tolerance) if tolerance else None
            if delta is not None and (pd.isna(delta) or delta<pd.Timedelta(0) or delta>pd.Timedelta(days=3660)):raise ValueError()
        except (ValueError,TypeError):raise DataError('invalid_tolerance')
        result=pd.merge_asof(a,b,left_on=left,right_on=right,by=by,direction=choice(p,'direction',{'backward','forward','nearest'},'backward'),tolerance=delta,allow_exact_matches=flag(p,'exact',True),suffixes=('','_right'))
        matched=int(result[marker].notna().sum());visual.update(matches=[{'left':str(l),'right':str(r) if pd.notna(r) else None} for l,r in zip(result[left].head(50),result[marker].head(50))],quality={'matchedLeftRows':matched,'unmatchedLeftRows':len(result)-matched,'rowsAfterJoin':len(result),'invalidDates':invalid_count,'duplicateTimes':duplicate_count})
        result=result.reset_index(drop=True)
    else:raise DataError('invalid_operation')
    result.attrs['visual']=clean(visual)
    return result,[]
