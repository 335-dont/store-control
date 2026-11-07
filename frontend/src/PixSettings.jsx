import React,{useEffect,useState} from 'react';
export default function PixSettings({notify}){
 const [guild,setGuild]=useState('');
 const [form,setForm]=useState({key:'',name:'',city:''});
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const load=async()=>{
  setError('');setBusy(true);
  try{
   const g=await fetch('/auth/selected-guild',{credentials:'same-origin'}).then(r=>r.json());
   const id=g.selected_guild_id;
   setGuild(id||'');
   if(!id){setForm({key:'',name:'',city:''});return}
   const r=await fetch('/api/store/pix',{headers:{'X-Store-Guild':id},credentials:'same-origin'});
   const data=await r.json();if(!r.ok)throw Error(data.detail||'Falha ao carregar');
   setForm(data);
  }catch(e){setError(e.message)}finally{setBusy(false)}
 };
 useEffect(()=>{load();const changed=()=>load();window.addEventListener('store-guild-changed',changed);return()=>window.removeEventListener('store-guild-changed',changed)},[]);
 const save=async()=>{
  if(!guild)return;
  setBusy(true);setError('');
  try{
   const r=await fetch('/api/store/pix',{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Store-Guild':guild},body:JSON.stringify(form)});
   const data=await r.json();if(!r.ok)throw Error(data.detail||'Falha ao salvar');
   setForm(data);notify?.('Configurações Pix salvas neste servidor');
  }catch(e){setError(e.message)}finally{setBusy(false)}
 };
 return <div className="module-page"><div className="module-heading"><div><div className="eyebrow">STORE CONTROL / PAGAMENTOS</div><h1>Configuração Pix</h1><p className="module-subtitle">O QR Code de cada pedido usa a chave deste servidor e o valor da compra.</p></div></div><section className="card" style={{maxWidth:650,padding:24,display:'grid',gap:16}}>
 {!guild&&<p>Selecione um servidor no seu perfil Discord.</p>}
 <label className="form-field"><span>Chave Pix</span><input value={form.key} maxLength={140} placeholder="CPF, e-mail, telefone ou chave aleatória" onChange={e=>setForm({...form,key:e.target.value})}/></label>
 <label className="form-field"><span>Nome do recebedor (até 25 caracteres)</span><input value={form.name} maxLength={25} placeholder="Nome da conta Pix" onChange={e=>setForm({...form,name:e.target.value})}/></label>
 <label className="form-field"><span>Cidade do recebedor (até 15 caracteres)</span><input value={form.city} maxLength={15} placeholder="Cidade" onChange={e=>setForm({...form,city:e.target.value})}/></label>
 <p style={{opacity:.7}}>A chave é usada para gerar o código Pix Copia e Cola. Confirme os dados bancários antes de liberar vendas.</p>
 {error&&<p role="alert" style={{color:'#e57373'}}>{error}</p>}
 <button className="pill primary" disabled={busy||!guild} onClick={save}>{busy?'Aguarde…':'Salvar configurações Pix'}</button>
 </section></div>
}
