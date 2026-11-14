import {create} from 'zustand';
import {api,ApiError} from './api';
import type {Dataset,DatasetRef,Project} from './types';
import {uniqueSelection,type SelectionMode} from './selection';
interface State {dataset:Dataset|null;datasets:DatasetRef[];ready:boolean;busy:boolean;error:string;notice:string;selection:number[]|null;selectionMode:SelectionMode;setSelectionMode:(s:SelectionMode)=>void;selectedField:string|null;setDataset:(d:Dataset)=>void;init:()=>Promise<void>;refreshList:()=>Promise<void>;load:(id:string)=>Promise<void>;sample:(name:string)=>Promise<void>;history:(action:string)=>Promise<void>;saveProject:(p:Project)=>Promise<boolean>;setSelection:(s:number[]|null)=>void;setField:(s:string|null)=>void;notify:(s:string)=>void;fail:(e:unknown)=>void;clearMessage:()=>void;}
export const useStudio=create<State>((set,get)=>({
 dataset:null,datasets:[],ready:false,busy:false,error:'',notice:'',selection:null,selectionMode:'temporary',selectedField:null,
 setDataset:d=>{localStorage.setItem('vps-active',d.id);set({dataset:d,selection:null,selectedField:null});get().refreshList()},
 refreshList:async()=>{try{set({datasets:await api.list()})}catch(e){get().fail(e)}},
 init:async()=>{try{await get().refreshList();const id=localStorage.getItem('vps-active');if(id&&get().datasets.some(d=>d.id===id))set({dataset:await api.get(id)})}catch(e){get().fail(e)}finally{set({ready:true})}},
 load:async id=>{set({busy:true});try{get().setDataset(await api.get(id))}catch(e){get().fail(e)}finally{set({busy:false})}},
 sample:async name=>{set({busy:true});try{get().setDataset(await api.sample(name));get().notify('loaded')}catch(e){get().fail(e)}finally{set({busy:false})}},
 history:async action=>{const d=get().dataset;if(!d||get().busy)return;set({busy:true});try{get().setDataset(await api.history(d.id,action,d.revision));get().notify('applied')}catch(e){get().fail(e)}finally{set({busy:false})}},
 saveProject:async project=>{const d=get().dataset;if(!d||get().busy)return false;set({busy:true});try{const result=await api.project(d.id,project,d.revision);set({dataset:result});get().notify('saved');return true}catch(e){get().fail(e);return false}finally{set({busy:false})}},
 setSelectionMode:selectionMode=>set({selectionMode}),setSelection:selection=>{const next=selection===null?null:uniqueSelection(selection).sort((a,b)=>a-b);const old=get().selection;if(next===null?old===null:old!==null&&next.length===old.length&&next.every((v,i)=>v===old[i]))return;set({selection:next})},setField:selectedField=>set({selectedField}),
 notify:notice=>set({notice,error:''}),fail:e=>set({error:e instanceof ApiError?e.code:'server_error',notice:''}),clearMessage:()=>set({notice:'',error:''}),
}));
