import React,{useEffect,useState} from 'react';
import './push-settings.css';

const installed = () => window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
const supported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const urlBytes = value => {
 const padding = '='.repeat((4-value.length%4)%4);
 const raw=atob((value+padding).replace(/-/g,'+').replace(/_/g,'/'));
 return Uint8Array.from(raw,c=>c.charCodeAt(0));
};
async function selectedGuild(){
 const r=await fetch('/auth/selected-guild',{credentials:'same-origin',cache:'no-store'});
 const v=await r.json();if(!r.ok||!v.selected_guild_id)throw Error('Selecione seu servidor no perfil.');return v.selected_guild_id;
}
async function request(path,guild,options={}){
 const r=await fetch('/api/store/push'+path,{credentials:'same-origin',cache:'no-store',...options,headers:{'X-Store-Guild':guild,...options.headers}});
 const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.detail||'Falha ao configurar notificações');return data;
}
export default function PushSettings({onClose}){
 const [config,setConfig]=useState(null),[status,setStatus]=useState(''),[busy,setBusy]=useState(false),[enabled,setEnabled]=useState(false),[registered,setRegistered]=useState(false);
 const canUse=supported();const standalone=installed();
 useEffect(()=>{let active=true;setStatus('');(async()=>{try{const gid=await selectedGuild();const cfg=await request('/config',gid);const reg=canUse?await navigator.serviceWorker.getRegistration('/'):null;const sub=reg?await reg.pushManager.getSubscription():null;const info=sub?await request('/subscriptions/check',gid,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint:sub.endpoint})}):{registered:false};if(active){setConfig(cfg);setRegistered(info.registered);setEnabled(!!sub&&info.registered);if(sub&&!info.registered)setStatus('Existe uma inscrição antiga no iPhone, mas ela não está cadastrada no servidor. Toque em Ativar notificações para corrigir.');}}catch(e){if(active)setStatus(e.message)}})();return()=>{active=false}},[]);
 const enable=async()=>{
  setBusy(true);setStatus('');try{
   if(!canUse)throw Error('Este navegador não oferece Web Push.');
   if(!standalone && /iPad|iPhone|iPod/.test(navigator.userAgent))throw Error('No iPhone, abra a Eleve pelo ícone adicionado à Tela de Início.');
   if(!config?.enabled)throw Error('Notificações ainda não configuradas no Railway.');
   // iOS requires the permission prompt to be triggered directly by the tap.
   const permission=await Notification.requestPermission();if(permission!=='granted')throw Error('Permissão negada. Verifique Ajustes → Notificações → Eleve.');
   const gid=await selectedGuild();const cfg=await request('/config',gid);
   const reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
   await navigator.serviceWorker.ready;
   let sub=await reg.pushManager.getSubscription();
   if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBytes(cfg.public_key)});
   await request('/subscriptions',gid,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub.toJSON())});
   setRegistered(true);setEnabled(true);setStatus('Dispositivo cadastrado no servidor! Use Testar aviso para confirmar o recebimento.');
  }catch(e){setStatus(e.message)}finally{setBusy(false)}
 };
 const test=async()=>{setBusy(true);setStatus('Enviando aviso de teste…');try{const gid=await selectedGuild();const data=await request('/test',gid,{method:'POST'});setStatus(`${data.message} Enviados: ${data.sent}; falhas: ${data.failed}.`)}catch(e){setStatus(e.message)}finally{setBusy(false)}};
 const disable=async()=>{
  setBusy(true);setStatus('');try{const gid=await selectedGuild();const reg=await navigator.serviceWorker.getRegistration('/');const sub=await reg?.pushManager.getSubscription();if(sub){await request('/subscriptions',gid,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub.toJSON())});await sub.unsubscribe()}setEnabled(false);setRegistered(false);setStatus('Notificações desativadas neste dispositivo.')}catch(e){setStatus(e.message)}finally{setBusy(false)}
 };
 return <div className="push-cover" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><section className="push-dialog" role="dialog" aria-modal="true" aria-label="Notificações da Eleve"><div className="push-head"><div><h2>Notificações da Eleve</h2><p>Receba um aviso quando um pagamento for aprovado no seu servidor.</p></div><button onClick={onClose} aria-label="Fechar">✕</button></div>
 <div className="push-body"><p><strong>Status:</strong> {enabled?'Inscrição salva no servidor':registered?'Cadastradas':'Não confirmadas neste servidor'}</p>{!standalone&&<p className="push-guide">📱 iPhone: abra o site no Safari → Compartilhar → Adicionar à Tela de Início. Depois abra a Eleve pelo novo ícone e toque em Ativar notificações.</p>}{config&&!config.enabled&&<p className="push-guide">O administrador precisa configurar as chaves VAPID no Railway para liberar os avisos.</p>}<div className="push-buttons"><button className="pill primary" onClick={enable} disabled={busy||!canUse||config?.enabled===false}>{busy?'Configurando…':'Ativar notificações'}</button>{enabled&&<button className="pill" onClick={test} disabled={busy}>Testar aviso</button>}{enabled&&<button className="pill" onClick={disable} disabled={busy}>Desativar</button>}</div>{status&&<p role="status" className="push-status">{status}</p>}<small>As notificações podem chegar mesmo com o site fechado. Dependem da permissão do iPhone, da conexão e do serviço de notificações da Apple.</small></div></section></div>
}
