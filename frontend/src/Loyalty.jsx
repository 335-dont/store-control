import React,{useEffect,useState} from 'react';
const money=cents=>(Number(cents||0)/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
export default function Loyalty({notify}){
 const [guild,setGuild]=useState(''),[tiers,setTiers]=useState([]),[clients,setClients]=useState([]),[roles,setRoles]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [minimum,setMinimum]=useState(''),[role,setRole]=useState('');
 const request=async(url,opts={})=>{const r=await fetch(url,{credentials:'same-origin',headers:{'X-Store-Guild':guild,...(opts.body?{'Content-Type':'application/json'}:{})},...opts});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Falha na API');return data};
 const load=async()=>{setBusy(true);setError('');try{
  const gr=await fetch('/auth/selected-guild',{credentials:'same-origin'});
  const g=await gr.json();if(!gr.ok)throw Error(g.detail||'Faça login no Discord');
  const id=g.selected_guild_id||'';setGuild(id);
  if(!id){setTiers([]);setClients([]);setRoles([]);setError('Selecione um servidor no perfil Discord.');return}
  const headers={'X-Store-Guild':id};
  const get=async u=>{const r=await fetch(u,{credentials:'same-origin',headers});const d=await r.json();if(!r.ok)throw Error(d.detail||`Falha HTTP ${r.status}`);return d};
  const a=await get('/api/store/loyalty');setTiers(a.tiers||[]);
  const [b,c]=await Promise.allSettled([get('/api/store/loyalty/clients'),get('/api/store/loyalty/roles')]);
  if(b.status==='fulfilled')setClients(b.value.clients||[]);
  if(c.status==='fulfilled')setRoles(c.value.roles||[]);
  else setError('Faixas carregadas, mas os cargos não puderam ser listados: '+c.reason.message);
 }catch(e){setError('Não foi possível carregar as configurações: '+e.message)}finally{setBusy(false)}};
 useEffect(()=>{load();window.addEventListener('store-guild-changed',load);return()=>window.removeEventListener('store-guild-changed',load)},[]);
 const save=async(next)=>{setBusy(true);setError('');try{
  if(!guild)throw Error('Selecione um servidor antes de salvar');
  const data=await request('/api/store/loyalty',{method:'PUT',body:JSON.stringify({tiers:next})});
  const check=await request('/api/store/loyalty');
  if(JSON.stringify(check.tiers)!==JSON.stringify(data.tiers))throw Error('Servidor não confirmou as faixas salvas');
  setTiers(check.tiers);notify?.('Faixas confirmadas no banco de dados');return true;
 }catch(e){setError('Falha ao salvar: '+e.message);return false}finally{setBusy(false)}};
 const add=async()=>{const amount=Number(minimum.replace(',','.'));if(!/^\d{15,22}$/.test(role)||!Number.isFinite(amount)||amount<=0)return setError('Selecione um cargo e informe um valor maior que zero.');const cents=Math.round(amount*100);if(tiers.some(t=>t.role_id===role||t.minimum_cents===cents))return setError('Cargo ou valor já cadastrado.');if(await save([...tiers,{role_id:role,minimum_cents:cents}])){setRole('');setMinimum('')}};
 const rank=total=>[...tiers].filter(t=>total>=t.minimum_cents).sort((a,b)=>b.minimum_cents-a.minimum_cents)[0];
 return <div className="module-page"><div className="module-heading"><div><div className="eyebrow">STORE CONTROL / FIDELIDADE</div><h1>Cargos de Compras</h1><p className="module-subtitle">Cargos automáticos por total acumulado de pedidos entregues.</p></div></div>
 {!guild&&<p>Selecione um servidor Discord para configurar os cargos.</p>}
 <section className="card" style={{padding:24,display:'grid',gap:16,maxWidth:800}}><h2>Nova faixa de compras</h2><div style={{display:'flex',flexWrap:'wrap',gap:12}}><label className="form-field" style={{flex:'1 1 200px'}}><span>Valor mínimo (R$)</span><input type="text" inputMode="decimal" value={minimum} placeholder="50,00" onChange={e=>setMinimum(e.target.value)}/></label><label className="form-field" style={{flex:'1 1 240px'}}><span>ID do cargo Discord</span><select value={role} onChange={e=>setRole(e.target.value)}><option value="">Selecione um cargo Discord</option>{roles.slice().sort((a,b)=>b.position-a.position).map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>{!roles.length&&<small>Lista indisponível. Confira a conexão do Discord e o token do bot no serviço web.</small>}</label></div><button className="pill primary" disabled={!guild||busy} onClick={add}>Adicionar faixa</button><p style={{opacity:.7}}>Ative Gerenciar Cargos no Discord e posicione o cargo do bot acima dos cargos de compras.</p></section>
 <section className="card" style={{padding:24,marginTop:18,maxWidth:800}}><h2>Faixas configuradas</h2>{tiers.length===0?<p>Nenhuma faixa cadastrada.</p>:<div style={{display:'grid',gap:12,marginTop:16}}>{tiers.map(t=><div key={t.role_id} style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,flexWrap:'wrap'}}><span><strong>{money(t.minimum_cents)}</strong> · Cargo <strong>{roles.find(r=>r.id===t.role_id)?.name||t.role_id}</strong></span><button className="pill" disabled={busy} onClick={()=>save(tiers.filter(x=>x.role_id!==t.role_id))}>Remover</button></div>)}</div>}</section>
 <section className="card" style={{padding:24,marginTop:18,maxWidth:800}}><h2>Clientes e níveis</h2><p>Mostrando até 200 clientes com pedidos entregues. Para aplicar cargos a clientes antigos, use o comando /sincronizar_cargos no Discord (administradores).</p><div style={{overflowX:'auto',marginTop:12}}><table className="records-table"><thead><tr><th>Discord ID</th><th>Total gasto</th><th>Cargo</th></tr></thead><tbody>{clients.map(c=><tr key={c.buyer_id}><td>{c.buyer_id}</td><td>{money(c.total_cents)}</td><td>{rank(c.total_cents)?.role_id||'Sem faixa'}</td></tr>)}</tbody></table></div></section>
 {error&&<p role="alert" style={{color:'#e57373',marginTop:14}}>{error}</p>}{busy&&<p>Carregando…</p>}</div>;
}
