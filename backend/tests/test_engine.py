import numpy as np
import pandas as pd
import pytest
from app.engine import apply_operation, analyze, chart, DataError, pack, unpack, differences

@pytest.fixture
def data():
    return pd.DataFrame({'team':['A','A','B','B','B'],'value':[1.,None,3.,3.,100.],'label':['  One','Two','Three','Three','Five'],'date':pd.date_range('2025-01-01',periods=5)})

def run(df,op,**params):
    return apply_operation(df,op,params)[0]

def test_missing_undoable_input(data):
    out=run(data,'missing',columns=['value'],method='median')
    assert out.value.iloc[1]==3
    assert pd.isna(data.value.iloc[1])
    assert differences(data,out)['modifiedCells']==1
    assert len(run(data,'missing',columns=['value'],method='drop_rows'))==4
    assert run(data,'missing',columns=['value'],method='ffill').value.iloc[1]==1
    assert run(data,'missing',columns=['value'],method='bfill').value.iloc[1]==3

def test_missing_errors():
    df=pd.DataFrame({'a':[np.nan,np.nan],'b':['x',None]})
    with pytest.raises(DataError,match='all_missing'):run(df,'missing',columns=['a'],method='mean')
    with pytest.raises(DataError,match='numeric_required'):run(df,'missing',columns=['b'],method='median')
    with pytest.raises(DataError,match='last_column'):run(df,'missing',columns=['a','b'],method='drop_columns')
    assert run(df,'missing',columns=['a'],method='constant',value='2').a.tolist()==[2,2]

@pytest.mark.parametrize('keep,n',[('first',4),('last',4),('none',3)])
def test_duplicates(data,keep,n):
    assert len(run(data,'duplicates',columns=['team','value'],keep=keep))==n

def test_convert():
    df=pd.DataFrame({'a':['1','bad',None]})
    with pytest.raises(DataError,match='conversion_failed'):run(df,'type',field='a',target='number')
    result,warnings=apply_operation(df,'type',{'field':'a','target':'number'},preview=True)
    assert warnings[0]['count']==1
    assert result.a.isna().sum()==2
    bools=run(pd.DataFrame({'a':['true','false','yes','0',None]}),'type',field='a',target='boolean')
    assert bools.a.iloc[:4].tolist()==[True,False,True,False]

def test_filter_sort(data):
    out=run(data,'filter',conditions=[{'field':'value','operator':'ge','value':'3'},{'field':'team','operator':'eq','value':'B'}],logic='and')
    assert out.index.tolist()==[2,3,4]
    out=run(data,'filter',conditions=[{'field':'value','operator':'lt','value':2},{'field':'value','operator':'gt','value':90}],logic='or')
    assert out.index.tolist()==[0,4]
    assert run(data,'sort',columns=['team','value'],ascending=[False,False],nulls='first').index.tolist()==[4,2,3,1,0]
    assert run(data,'filter',conditions=[{'field':'label','operator':'contains','value':'.*'}]).empty

def test_category_filter_keeps_commas_and_boolean_date_types():
    df=pd.DataFrame({'category':['East, China','West','East, China'],'flag':[True,False,True],'date':pd.date_range('2025-01-01',periods=3)})
    assert run(df,'filter',conditions=[{'field':'category','operator':'in','value':['East, China']}]).index.tolist()==[0,2]
    assert run(df,'filter',conditions=[{'field':'flag','operator':'in','value':['false']}]).index.tolist()==[1]
    assert run(df,'filter',conditions=[{'field':'date','operator':'in','value':['2025-01-02']}]).index.tolist()==[1]
    with pytest.raises(DataError,match='invalid_value'):
        run(df,'filter',conditions=[{'field':'flag','operator':'eq','value':'invalid'}])

def test_columns(data):
    assert run(data,'column',action='calculate',field='value',name='double',method='multiply',value=2).double.iloc[0]==2
    assert run(data,'column',action='string',field='label',name='trimmed',method='strip').trimmed.iloc[0]=='One'
    assert run(data,'column',action='date',field='date',name='year',method='year').year.iloc[0]==2025
    assert run(data,'column',action='rename',field='team',name='group').columns[0]=='group'
    with pytest.raises(DataError):run(data,'column',action='calculate',field='value',name='attack',method='__import__',value=1)

def test_group_pivot_join(data):
    out=run(data,'group',groups=['team'],values=['value'],agg='sum')
    assert out.value.tolist()==[1,106]
    pivot=run(data,'pivot',row='team',column='label',value='value',agg='count')
    assert pivot.loc[pivot.team=='B','Three'].iloc[0]==2
    other=pd.DataFrame({'team':['A','C'],'extra':[10,20]})
    merged=apply_operation(data,'join',{'left':'team','right':'team','how':'outer'},other)[0]
    assert len(merged)==6
    assert len(apply_operation(data,'concat',{'axis':0},data)[0])==10
    with pytest.raises(DataError,match='overlapping_fields'):run(data,'group',groups=['team'],values=['team'],agg='count')

def test_outliers(data):
    out=run(data,'outliers',field='value',method='custom',lower=0,upper=10,action='clip')
    assert out.value.iloc[-1]==10
    assert len(run(data,'outliers',field='value',method='iqr',threshold=1.5,action='drop'))==4

def test_stats_charts_and_serialization(data):
    result=analyze(data,{'kind':'describe'})['rows'][0]
    assert result['mean']==26.75
    assert result['median']==3
    assert chart(data,{'type':'bar','x':'team','y':'value','agg':'sum'})['series'][0]['data'][1]['value']==106
    assert chart(data,{'type':'scatter','x':'value','y':'value'})['points'][0]['id']==0
    assert analyze(data,{'kind':'describe','selection':[2,3]})['rows'][0]['mean']==3
    assert chart(data,{'type':'heatmap','x':'value'})['cells'][0][2]==1
    pd.testing.assert_frame_equal(unpack(pack(data)),data)
    for kind in ['histogram','box','violin']:
        result=chart(data,{'type':kind,'x':'value'})
        assert len(result['groups'])==1
    assert analyze(data,{'kind':'test','test':'normality','field':'value'})['p'] is not None

def test_empty_allnull_and_constant():
    df=pd.DataFrame({'n':pd.Series([],dtype=float),'s':pd.Series([],dtype=str)})
    assert analyze(df,{'kind':'describe'})['rows'][0]['mean'] is None
    assert chart(df,{'type':'histogram','x':'n'})['groups']==[]
    assert chart(pd.DataFrame({'n':[1.,1.,1.]}),{'type':'violin','x':'n'})['groups'][0]['density']==[]

def test_join_explosion_blocked():
    df=pd.DataFrame({'key':[1]*400})
    with pytest.raises(DataError,match='result_too_large'):
        apply_operation(df,'join',{'left':'key','right':'key','how':'inner'},df)

def test_pivot_heatmap_uses_values_and_row_selection():
    df=pd.DataFrame({'region':['East','East','West'],'product':['A','B','A'],'amount':[10.,20.,30.]})
    pivot=run(df,'pivot',row='region',column='product',value='amount',agg='sum')
    result=chart(pivot,{'type':'heatmap','x':'region','method':'values','agg':'mean'})
    assert result['xLabels']==['A','B'] and result['yLabels']==['East','West']
    assert result['cells']==[[0,0,10.],[1,0,20.],[0,1,30.],[1,1,None]]
    assert result['rowIds'][1]==[1]
    assert result['range']==[10.,30.]
    assert chart(pd.DataFrame({'cat':[str(i) for i in range(61)],'n':range(61)}),{'type':'heatmap','x':'cat','method':'values'})['sampled']

def test_group_histogram_uses_common_bins_and_exact_selection():
    df=pd.DataFrame({'value':[0.,1.,2.,10.,11.,12.],'team':['A','A','A','B','B','B']})
    result=chart(df,{'type':'histogram','x':'value','group':'team','bins':3})
    assert result['groups'][0]['edges']==result['groups'][1]['edges']
    assert result['groups'][0]['hist']==[3,0,0]
    assert result['groups'][1]['hist']==[0,0,3]
    assert analyze(df,{'kind':'select','field':'value','lower':0,'upper':2})['ids']==[0,1]
    assert analyze(df,{'kind':'select','field':'value','lower':0,'upper':2,'includeUpper':True})['ids']==[0,1,2]
    assert analyze(df,{'kind':'select','field':'value','lower':0,'upper':12,'includeUpper':True,'group':'team','categories':['B']})['ids']==[3,4,5]

@pytest.mark.parametrize('agg',['count','sum','mean','median','min','max','std','nunique'])
def test_all_group_aggregations(data,agg):
    result=run(data,'group',groups=['team'],values=['value'],agg=agg)
    expected=data.groupby('team',dropna=False)['value'].agg(agg).reset_index()
    pd.testing.assert_frame_equal(result,expected)
