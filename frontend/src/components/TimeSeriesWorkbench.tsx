import {useEffect,useState} from 'react';
import {useTranslation} from 'react-i18next';
import {useStudio} from '../store';
import {Field,Select,Tabs} from './UI';
import {TimelineChart} from './TimelineChart';
import {SelectionControls} from './SelectionControls';
import {DataTable} from './DataTable';
import {OperationPanel} from './OperationPanel';
export function TimeSeriesWorkbench(){
 const {dataset}=useStudio();const d=dataset!;const {t}=useTranslation();const nums=d.fields.filter(f=>f.type==='number').map(f=>f.name),times=d.fields.filter(f=>f.type==='date'||f.type==='text').map(f=>f.name);
 const [op,setOp]=useState('resample'),[p,setP]=useState<Record<string,unknown>>({});
 useEffect(()=>setP({field:nums[0]||'',time:d.fields.find(f=>f.type==='date')?.name||times[0]||'',name:`${nums[0]||'value'}_${op}`,frequency:'D',agg:'mean',method:'mean',duplicates:'reject',invalid:'reject',timezone:'utc',window:7,minPeriods:7,alpha:.3,periods:1,adjust:true,center:false,fill:'none',anomalyThreshold:.5}),[op,d.id]);
 const patch=(v:Record<string,unknown>)=>setP(p=>({...p,...v}));
 const select=(key:string,options:string[],label=key,fields=false)=><Field label={t(label)}><Select value={String(p[key]??'')} onChange={v=>patch(key==='field'&&p.name===`${p.field}_${op}`?{field:v,name:`${v}_${op}`}:{[key]:v})} options={options.map(v=>({value:v,label:fields?v:t(v==='drop'?'dropInvalidTime':v==='sum'?'sum':v==='first'?'keepFirstTime':v==='last'?'keepLastTime':v==='none'?'noFill':v)}))}/></Field>;
 const input=(key:string,type='number',label=key)=><Field label={t(label)}><input type={type} value={String(p[key]??'')} onChange={e=>patch({[key]:type==='number'?Number(e.target.value):e.target.value})}/></Field>;
 return <><Tabs tabs={['resample','rolling','ewm','growth','time_gaps']} value={op} onChange={setOp}/><SelectionControls/>{p.time&&p.field?<TimelineChart time={String(p.time)} field={String(p.field)}/>:null}<OperationPanel operation={op} params={p} live disabled={!p.field||!p.time}><p className="muted">{t('timeSeriesHelp')}</p><div className="form-grid">{select('time',times,'timeField',true)}{select('field',nums,'field',true)}{select('duplicates',['reject','first','last','mean','sum'],'duplicatePolicy')}{select('invalid',['reject','drop'],'invalidTimePolicy')}
 {['resample','time_gaps'].includes(op)?<>{select('frequency',op==='time_gaps'?['h','12h','D','W','ME']:['D','W','ME','QE','YE'])}{select('agg',['sum','mean','count','min','max'])}{op==='time_gaps'&&select('fill',['none','linear','ffill','bfill'],'gapFill')}</>:<>{input('name','text','newName')}{op==='growth'?input('periods'): <><Field label={`${t('window')} · ${p.window}`}><input type="range" min="1" max="100" value={Number(p.window||7)} onChange={e=>patch({window:Number(e.target.value),minPeriods:Math.min(Number(p.minPeriods),Number(e.target.value))})}/></Field>{input('minPeriods')}{op==='rolling'?select('method',['mean','std','max','min']):<Field label={`${t('alpha')} · ${p.alpha}`}><input type="range" min="0.01" max="1" step="0.01" value={Number(p.alpha||.3)} onChange={e=>patch({alpha:Number(e.target.value)})}/></Field>}</>}</>}
 </div><details className="feature-help"><summary>{t('advancedParameters')}</summary><div className="form-grid">{select('timezone',['utc','naive'])}{input('anomalyThreshold')}{op==='ewm'&&<label className="checkbox-label"><input type="checkbox" checked={!!p.adjust} onChange={e=>patch({adjust:e.target.checked})}/>{t('adjust')}</label>}{op==='rolling'&&<label className="checkbox-label"><input type="checkbox" checked={!!p.center} onChange={e=>patch({center:e.target.checked})}/>{t('center')}</label>}</div><p>{t('timePolicyHint')}</p></details></OperationPanel><DataTable linked/></>
}
