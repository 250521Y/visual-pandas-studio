import {useTranslation} from 'react-i18next';
import {MousePointer2,X} from 'lucide-react';
import {useStudio} from '../store';
import {OperationPanel} from './OperationPanel';
import {Select} from './UI';
export function SelectionControls(){const {selection,selectionMode,setSelection,setSelectionMode}=useStudio();const {t}=useTranslation();return <div className="selection-controls"><div className="selection-controls-line"><div><MousePointer2 size={16}/><strong>{selection===null?t('noActiveSelection'):t('selection',{count:selection.length})}</strong></div><Select value={selectionMode} onChange={v=>setSelectionMode(v as typeof selectionMode)} options={['highlight','temporary','apply'].map(v=>({value:v,label:t('selectionMode.'+v)}))}/><button className="button secondary" disabled={selection===null} onClick={()=>setSelection(null)}><X size={14}/>{t('clearSelection')}</button></div><p className="muted">{t('selectionHint.'+selectionMode)}</p>{selectionMode==='apply'&&selection!==null&&<OperationPanel operation="select_rows" params={{ids:selection}} disabled={!selection.length}><p className="muted">{t('formalSelectionHint')}</p></OperationPanel>}</div>}
