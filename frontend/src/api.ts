import type { Dataset,DatasetRef,OperationRequest,Preview,Project,TableData,ChartData } from './types';
import {createId} from './id';
const base=(import.meta as unknown as {env:Record<string,string>}).env.VITE_API_BASE||'';
export const session=localStorage.getItem('vps-session')||createId();
localStorage.setItem('vps-session',session);
const revisions=new Map<string,number>();
export class ApiError extends Error {constructor(public code:string,public details?:unknown){super(code)}}
export async function request<T>(path:string,options:RequestInit={}):Promise<T>{
 const headers:Record<string,string>={'X-Studio-Session':session,...options.headers as Record<string,string>};
 if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
 let response:Response;try{response=await fetch(`${base}/api${path}`,{...options,headers})}catch{throw new ApiError('network')}
 if(!response.ok){const body=await response.json().catch(()=>({error:response.status===413?'file_too_large':response.status===429?'rate_limit':'server_error'}));throw new ApiError(body.error||'server_error',body.details)}
 const value=await response.json();if(value&&typeof value.id==='string'&&typeof value.revision==='number')revisions.set(value.id,value.revision);return value;
}
export const api={
 list:()=>request<DatasetRef[]>('/datasets'),get:(id:string)=>request<Dataset>(`/datasets/${id}`),
 sample:(name:string)=>request<Dataset>(`/samples/${name}`,{method:'POST'}),
 upload:(data:FormData)=>request<Dataset>('/upload',{method:'POST',body:data}),sheets:(data:FormData)=>request<{sheets:string[]}>('/upload/sheets',{method:'POST',body:data}),
 importProject:(data:FormData)=>request<Dataset>('/projects/import',{method:'POST',body:data}),
 remove:(id:string)=>request(`/datasets/${id}`,{method:'DELETE'}),
 table:(id:string,query:URLSearchParams)=>{const payload={offset:Number(query.get('offset')||0),limit:Number(query.get('limit')||25),search:query.get('search')||'',sort:query.get('sort')||'',desc:query.get('desc')==='true',selection_active:query.get('selection_active')==='true',ids:(query.get('ids')||'').split(',').filter(Boolean).map(Number)};return request<TableData>(`/datasets/${id}/table`,{method:'POST',body:JSON.stringify(payload)})},
 preview:(id:string,body:OperationRequest)=>request<Preview>(`/datasets/${id}/preview`,{method:'POST',body:JSON.stringify(body)}),
 operate:(id:string,body:OperationRequest)=>request<Dataset>(`/datasets/${id}/operations`,{method:'POST',body:JSON.stringify(body)}),
 history:(id:string,action:string,revision:number)=>request<Dataset>(`/datasets/${id}/history/${action}`,{method:'POST',body:JSON.stringify({revision})}),
 analyze:<T=ChartData>(id:string,body:Record<string,unknown>)=>request<T>(`/datasets/${id}/analysis`,{method:'POST',body:JSON.stringify({...body,revision:revisions.get(id)})}),
 project:(id:string,project:Project,revision:number)=>request<Dataset>(`/datasets/${id}/project`,{method:'PUT',body:JSON.stringify({project,revision})}),
};
export async function download(id:string,format:string,name:string){
 let res:Response;try{res=await fetch(`${base}/api/datasets/${id}/export/${format}`,{headers:{'X-Studio-Session':session}})}catch{throw new ApiError('network')}
 if(!res.ok){const err=await res.json();throw new ApiError(err.error)}
 saveBlob(await res.blob(),`${name}.${format}`);
}
export function saveBlob(blob:Blob,name:string){const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
