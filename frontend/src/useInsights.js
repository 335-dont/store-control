import {useSyncExternalStore} from 'react';
export const moneyCents=n=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format((Number(n)||0)/100);
export const dateTime=s=>s?new Date(s).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'}):'—';
const empty={orders:[],clients:[],top_products:[],daily:{},summary:{},truncated:false};
let state={data:empty,loading:true,error:''};
const subscribers=new Set();
let timer=null,generation=0;
let pending=false,lastFetchAt=0;
const hasCachedData=()=>Array.isArray(state.data?.orders) && !!state.data?.summary && Object.keys(state.data.summary).length>0;
const messageFor=e=> e instanceof TypeError && /load failed|failed to fetch|networkerror/i.test(e.message) ? 'Conexão instável com a API. Tentaremos atualizar automaticamente.' : e.message;
const emit=()=>{state={...state};subscribers.forEach(listener=>listener())};
const get=()=>state;
async function refresh(){
 if(pending||document.visibilityState==='hidden')return;
 pending=true;
 const requestId=++generation;
 state={...state,loading:!hasCachedData()};emit();
 try{
  const chosen=await fetch('/auth/selected-guild',{credentials:'same-origin',cache:'no-store'});
  const selection=await chosen.json().catch(()=>({}));
  if(!chosen.ok||!selection.selected_guild_id)throw new Error('Selecione um servidor no perfil.');
  const r=await fetch('/api/store/insights',{credentials:'same-origin',cache:'no-store',headers:{'X-Store-Guild':selection.selected_guild_id}});
  const json=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(json.detail||`Erro HTTP ${r.status}`);
  if(requestId===generation){lastFetchAt=Date.now();state={data:json,loading:false,error:''};emit()}
 }catch(e){if(requestId===generation){state={data:state.data,loading:false,error:hasCachedData()?'':messageFor(e)};emit()}}
 finally{pending=false}
}
function onVisible(){if(document.visibilityState==='visible'&&Date.now()-lastFetchAt>30000)void refresh()}
function onFocus(){if(Date.now()-lastFetchAt>30000)void refresh()}
function subscribe(fn){
 subscribers.add(fn);
 if(subscribers.size===1){
  window.addEventListener('focus',onFocus);
  document.addEventListener('visibilitychange',onVisible);
  window.addEventListener('store-guild-changed',refresh);
  timer=window.setInterval(refresh,120000);
  void refresh();
 }
 return ()=>{
  subscribers.delete(fn);
  if(!subscribers.size){
   generation++;
   window.removeEventListener('focus',onFocus);
   document.removeEventListener('visibilitychange',onVisible);
   window.removeEventListener('store-guild-changed',refresh);
   window.clearInterval(timer);timer=null;
  }
 };
}
export function useInsights(){return useSyncExternalStore(subscribe,get,get)}
export function exportCsv(rows,filename){
 const text='\uFEFF'+rows.map(row=>row.map(value=>'"'+String(value??'').replaceAll('"','""')+'"').join(';')).join('\r\n');
 const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));
 const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);
}
