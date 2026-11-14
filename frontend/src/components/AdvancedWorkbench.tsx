import {useEffect,useState} from 'react';
import {useTranslation} from 'react-i18next';
import {useStudio} from '../store';
import {Field,Select,MultiFields,Tabs} from './UI';
import {OperationPanel} from './OperationPanel';
export function AdvancedWorkbench(){
 const {dataset}=useStudio();const d=dataset!;const {t}=useTranslation();const names=d.fields.map(f=>f.name),numbers=d.fields.filter(f=>f.type==='number').map(f=>f.name),cats=d.fields.filter(f=>f.type!=='number').map(f=>f.name);
 const [op,setOp]=useState('melt'),[p,setP]=useState<Record<string,unknown>>({});
 useEffect(()=>{setP({ids:cats.slice(0,1),levels:cats.slice(1,2),values:numbers.slice(0,2),groups:cats.slice(0,1),columns:cats.slice(0,1),field:op==='explode'?(cats[0]||''):(numbers[0]||''),name:`${numbers[0]||'value'}_${op}`,variableName:'variable',valueName:'measure',sourceName:'source_row',method:op==='group_transform'?'mean':'rank',mode:'json',delimiter:',',sort:'',periods:1,rankMethod:'average',ascending:true,dropFirst:false,dummyNa:false,retain:false,percentile:false})},[op,d.id]);
 const patch=(v:Record<string,unknown>)=>setP(p=>({...p,...v}));
 const multi=(key:string,options=names)=><Field label={t(key==='ids'?'identifierFields':key==='levels'?'indexLevels':key)}><MultiFields fields={options} value={(p[key]||[]) as string[]} onChange={v=>patch(key==='field'&&p.name===`${p.field}_${op}`?{field:v,name:`${v}_${op}`}:{[key]:v})}/></Field>;
 const select=(key:string,options:string[],label=key,fields=false,optional=false)=><Field label={t(label)}><Select value={String(p[key]??'')} onChange={v=>patch(key==='field'&&p.name===`${p.field}_${op}`?{field:v,name:`${v}_${op}`}:{[key]:v})} options={options.map(v=>({value:v,label:fields?v:t(key==='rankMethod'&&v==='first'?'rankFirst':v)}))} placeholder={optional?'—':undefined}/></Field>;
 const input=(key:string,label=key,type='text')=><Field label={t(label)}><input type={type} value={String(p[key]??'')} onChange={e=>patch({[key]:type==='number'?Number(e.target.value):e.target.value})}/></Field>;
 const check=(key:string)=><label className="checkbox-label"><input type="checkbox" checked={!!p[key]} onChange={e=>patch({[key]:e.target.checked})}/>{t(key)}</label>;
 return <><Tabs tabs={['melt','pivot_strict','stack','unstack','explode','dummies','group_transform','window_calc']} value={op} onChange={setOp}/><OperationPanel operation={op} params={p} live><p className="muted">{t(op+'Help')}</p>
 {['melt','pivot_strict','stack','unstack'].includes(op)&&<><div className="form-grid">{multi('ids')}{multi('values')}</div>{['pivot_strict','unstack'].includes(op)?multi('levels'):<div className="form-grid">{input('variableName')}{input('valueName')}</div>}</>}
 {op==='explode'&&<div className="form-grid">{select('field',names,'field',true)}{select('mode',['json','delimiter'],'listMode')}{p.mode==='delimiter'&&input('delimiter')}{input('sourceName')}</div>}
 {op==='dummies'&&<>{multi('columns')}<div className="button-row">{check('retain')}{check('dropFirst')}{check('dummyNa')}</div></>}
 {['group_transform','window_calc'].includes(op)&&<>{op==='group_transform'&&multi('groups')}<div className="form-grid">{select('field',numbers,'field',true)}{select('method',op==='group_transform'?['mean','max','min','zscore','rank']:['rank','diff','shift','pct_change'])}{input('name','newName')}{op==='window_calc'&&select('sort',names,'sortBy',true,true)}{p.method==='rank'?select('rankMethod',['average','min','max','first','dense']):op==='window_calc'&&input('periods','periods','number')}</div><div className="button-row">{check('ascending')}{op==='window_calc'&&p.method==='rank'&&check('percentile')}</div></>}
 </OperationPanel></>
}
