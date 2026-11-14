import numpy as np
import pandas as pd
import pytest
from app.engine import apply_operation,DataError,pack,unpack

def run(df,op,**p):return apply_operation(df,op,p)[0]

@pytest.mark.parametrize('pattern',['a?a?a?z','a{1,20}a{1,20}z','a+a+z'])
def test_regex_complexity_guard(pattern):
    with pytest.raises(DataError,match='regex_restricted'):
        run(pd.DataFrame({'text':['a'*2000]}),'string',field='text',name='new',method='match',pattern=pattern)

def test_replacement_regex_error_and_mapping_nonfinite():
    df=pd.DataFrame({'text':['aaa'],'v':[1.]})
    with pytest.raises(DataError,match='invalid_regex'):
        run(df,'string',field='text',name='new',method='replace',pattern='a+',replacement='\\g<bad>',regex=True)
    for pair in [{'from':1,'to':float('inf')},{'from':[],'to':'x'},{'from':'NaN','to':0}]:
        with pytest.raises(DataError,match='invalid_value'):run(df,'mapping',field='v',name='new',pairs=[pair])
    with pytest.raises(DataError,match='invalid_name'):run(df,'cumulative',field='v',name=' v ')

def test_preview_counts_deleted_rows_and_added_columns():
    from app.engine import differences
    df=pd.DataFrame({'v':[1.,2.,3.,4.]})
    d=differences(df,df.iloc[:2]);assert d['affectedRows']==2 and d['affectedFields']==['v']
    d=differences(df,df.assign(copy=df.v));assert d['affectedRows']==4 and d['affectedFields']==['copy']
    d=differences(df,df.iloc[::-1]);assert d['affectedRows']==4 and d['modifiedCells']==0
    d=differences(pd.DataFrame({'v':[None]}),pd.DataFrame({'v':['<NULL>']}));assert d['modifiedCells']==1

def test_sample_reproducible_preview_count_fraction_replacement_group():
    df=pd.DataFrame({'n':range(20),'g':['A']*10+['B']*10})
    p={'mode':'count','n':8,'seed':17,'replace':False}
    preview=apply_operation(df,'sample',p,preview=True)[0]
    pd.testing.assert_frame_equal(preview,df.sample(n=8,random_state=17))
    pd.testing.assert_frame_equal(preview,run(df,'sample',**p))
    assert len(run(df,'sample',mode='fraction',fraction=.25,seed=42))==5
    replacement=run(df,'sample',mode='count',n=40,seed=42,replace=True)
    assert len(replacement)==40 and replacement.index.is_unique
    assert run(df,'sample',mode='count',n=3,group='g',seed=42).g.value_counts().tolist()==[3,3]
    with pytest.raises(DataError,match='sample_size'):run(df,'sample',mode='count',n=21)

@pytest.mark.parametrize('direction',['largest','smallest'])
@pytest.mark.parametrize('keep',['first','last','all'])
def test_topn_ties(direction,keep):
    df=pd.DataFrame({'v':[2.,2.,1.,1.,3.,np.nan]})
    expected=getattr(df,'nlargest' if direction=='largest' else 'nsmallest')(2,'v',keep=keep)
    pd.testing.assert_frame_equal(run(df,'topn',field='v',n=2,direction=direction,keep=keep),expected)

@pytest.mark.parametrize('method',['cut','qcut'])
def test_bins_match_pandas(method):
    df=pd.DataFrame({'v':[0.,1.,2.,3.,4.,np.nan]})
    result=run(df,'bin',field='v',name='bins',method=method,bins=3)
    expected=pd.cut(df.v,3,include_lowest=True) if method=='cut' else pd.qcut(df.v,3,duplicates='drop')
    pd.testing.assert_series_equal(result.bins,expected.astype('string'),check_names=False)
    assert sum(result.attrs['visual']['counts'])==5
    pd.testing.assert_frame_equal(unpack(pack(result)),result)

def test_custom_bins_quantile_duplicates_empty_bins_and_labels():
    df=pd.DataFrame({'v':[0.,1.,1.,1.,3.,np.nan]})
    result=run(df,'bin',field='v',name='b',method='custom',edges=[0,1,2,4],right=False,includeLowest=True,labels=['a','b','c'])
    assert result.b.iloc[:5].tolist()==['a','b','b','b','c']
    assert len(run(df,'bin',field='v',name='b',method='qcut',bins=4,duplicates='drop').attrs['visual']['edges'])<5
    with pytest.raises(DataError,match='bin_edges'):run(df,'bin',field='v',name='b',method='custom',edges=[1,1,2])
    with pytest.raises(DataError,match='bin_labels'):run(df,'bin',field='v',name='b',bins=3,labels=['only'])

def test_mapping_unmatched_missing_and_explicit_null():
    df=pd.DataFrame({'v':['A','B','C',None]})
    pairs=[{'from':'A','to':None},{'from':'B','to':'beta'},{'from':None,'to':'empty'}]
    assert run(df,'mapping',field='v',name='new',pairs=pairs,unmatched='keep').new.tolist()==[None,'beta','C','empty']
    assert pd.isna(run(df,'mapping',field='v',name='new',pairs=pairs,unmatched='missing').new.iloc[2])
    assert run(df,'mapping',field='v',name='v',overwrite=True,method='replace',pairs=[{'from':'B','to':'b'}]).v.tolist()==['A','b','C',None]

@pytest.mark.parametrize('method',['strip','lower','upper','len','contains','startswith','endswith','replace','split','match'])
def test_string_accessors(method):
    df=pd.DataFrame({'v':[' Aa-A ','Ab',None]});p={'field':'v','name':'new','method':method,'pattern':'A','replacement':'Z'}
    result=run(df,'string',**p);s=df.v.astype('string')
    if method in {'strip','lower','upper','len'}:expected=getattr(s.str,method)()
    elif method=='contains':expected=s.str.contains('A',regex=False,na=pd.NA)
    elif method in {'startswith','endswith'}:expected=getattr(s.str,method)('A',na=pd.NA)
    elif method=='replace':expected=s.str.replace('A','Z',regex=False)
    elif method=='match':expected=s.str.match('A',na=pd.NA)
    else:
        import json
        expected=s.str.split('A',n=10,regex=False).map(lambda v:json.dumps(v,ensure_ascii=False) if isinstance(v,list) else pd.NA).astype('string')
    pd.testing.assert_series_equal(result.new,expected,check_names=False)

def test_regex_feedback_and_bounds():
    df=pd.DataFrame({'v':['ABC','abc',None]})
    assert run(df,'string',field='v',name='new',method='match',pattern='^[A-Z]+$').new.iloc[:2].tolist()==[True,False]
    with pytest.raises(DataError,match='invalid_regex'):run(df,'string',field='v',name='n',method='match',pattern='[')
    with pytest.raises(DataError,match='regex_restricted'):run(df,'string',field='v',name='n',method='match',pattern='(a+)+$')

def test_date_preview_failures_timezone_quarter_diff_range():
    df=pd.DataFrame({'v':['2025/01/02','bad','2025/07/01'],'other':['2025/01/01']*3})
    p={'field':'v','name':'parsed','method':'parse','format':'%Y/%m/%d','timezone':'utc'}
    result,warnings=apply_operation(df,'date',p,preview=True)
    assert warnings[0]['ids']==[1] and result.parsed.isna().sum()==1
    with pytest.raises(DataError,match='conversion_failed'):run(df,'date',**p)
    assert run(df,'date',field='v',name='q',method='quarter',coerce=True).q.iloc[[0,2]].tolist()==[1,3]
    assert run(df,'date',field='v',name='delta',method='difference',other='other',coerce=True).delta.iloc[0]==1
    assert len(run(df,'date',field='v',method='range',start='2025-01-01',end='2025-01-31',coerce=True))==1

@pytest.mark.parametrize('method',['cumsum','cumprod','cummin','cummax'])
def test_cumulative_sorted(method):
    df=pd.DataFrame({'v':[3.,np.nan,2.,1.],'order':[3,4,2,1]})
    out=run(df,'cumulative',field='v',name='new',method=method,sort='order')
    pd.testing.assert_series_equal(out.new,getattr(df.sort_values('order').v,method)(),check_names=False)

def test_linear_time_interpolation_real_spacing_and_no_input_mutation():
    df=pd.DataFrame({'v':[0.,np.nan,10.],'date':['2025-01-01','2025-01-02','2025-01-11']})
    assert run(df,'interpolate',field='v',name='v',overwrite=True,method='linear').v.tolist()==[0,5,10]
    out=run(df,'interpolate',field='v',name='filled',method='time',time='date')
    assert out.filled.tolist()==[0,1,10] and pd.isna(df.v.iloc[1])
    with pytest.raises(DataError,match='duplicate_time'):run(pd.DataFrame({'v':[0.,None],'date':['2025-01-01']*2}),'interpolate',field='v',name='f',method='time',time='date')
