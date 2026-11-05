import {useSyncExternalStore} from 'react';
const empty={catalogs:[],products:[]};
let state={data:empty,ready:false,saving:false,error:'',revision:0,guild:null};
const listeners=new Set();
let currentGuild=null;
const emit=()=>{state={...state};listeners.forEach(f=>f())};
const subscribe=fn=>{listeners.add(fn);return()=>listeners.delete(fn)};
const get=()=>state;
let generation=0,dirty=false,running=false;
async function api(method,body){
 const r=await fetch('/api/store/snapshot',{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Store-Guild':currentGuild||''},...(body?{body:JSON.stringify(body)}:{})});
 const data=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(data.detail||`Erro HTTP ${r.status}`);
 return data;
}
export async function loadStore(){
 const gen=++generation;dirty=false;state={...state,ready:false,error:'',data:empty};emit();
 try{
  const selected=await fetch('/auth/selected-guild',{credentials:'same-origin'}).then(r=>r.json());
  if(gen!==generation)return;
  currentGuild=selected.selected_guild_id;
  if(!currentGuild)throw new Error('Selecione um servidor no perfil.');
  const result=await api('GET');if(gen!==generation)return;state={...state,ready:true,data:result.data,revision:result.revision,error:''};emit()}
 catch(e){if(gen!==generation)return;state={...state,ready:false,error:e.message};emit()}
}
export function setStoreData(update){
 if(!state.ready||state.error)return;
 const data=typeof update==='function'?update(state.data):update;
 state={...state,data};dirty=true;emit();void flush();
}
async function flush(){
 if(running||!dirty||!state.ready||state.error)return;
 running=true;const gen=generation;state={...state,saving:true};emit();
 try{
  while(dirty&&gen===generation){
   dirty=false;const data=state.data;const result=await api('PUT',{revision:state.revision,data});
   if(gen!==generation)return;
   state={...state,revision:result.revision};emit();
  }
 }catch(e){if(gen===generation){dirty=false;state={...state,error:e.message};emit()}}
 finally{running=false;if(gen===generation){state={...state,saving:false};emit();if(dirty)void flush()}}
}
export function useStore(){return useSyncExternalStore(subscribe,get,get)};
export function retryStore(){void loadStore()}
window.addEventListener('store-guild-changed',()=>{void loadStore()});
// A selected guild is stored in an HttpOnly signed cookie; the server validates permissions.
void loadStore();
