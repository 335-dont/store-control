import React,{useMemo,useState} from 'react';
import {Search,Users,X,Download,ChevronRight} from 'lucide-react';
import {useInsights,moneyCents,dateTime,exportCsv} from './useInsights.js';
import {Buyer,State,ProductIcon} from './CommerceVisuals.jsx';
import './support.css';
import './orders.css';
import './commerce.css';
export default function Clients(){
 const {data,loading,error}=useInsights(),[query,setQuery]=useState(''),[selected,setSelected]=useState(null);
 const clients=data.clients||[];
 const rows=useMemo(()=>clients.filter(c=>`${c.name} ${c.buyer_id}`.toLowerCase().includes(query.toLowerCase())),[clients,query]);
 const person=clients.find(c=>c.buyer_id===selected);
 const history=person?(data.orders||[]).filter(o=>o.buyer_id===person.buyer_id):[];
 return <div className="module-page"><div className="module-heading"><div><div className="eyebrow">ELEVE / CLIENTES</div><h1>Clientes</h1><p className="module-subtitle">Compradores identificados pelo ID do Discord, com foto de perfil e histórico real.</p></div><button className="pill" onClick={()=>exportCsv([['Discord ID','Cliente','Pedidos','Compras aprovadas','Total gasto (R$)','Último pedido'],...rows.map(p=>[p.buyer_id,p.name,p.orders,p.paid_orders,(p.total_cents/100).toFixed(2),p.last_order])],'eleve-clientes.csv')}><Download size={15}/> Exportar CSV</button></div>
 <div className="support-metrics">{[['Clientes identificados',clients.length],['Clientes compradores',clients.filter(c=>c.paid_orders>0).length],['Pedidos registrados',data.summary?.orders||0],['Faturamento aprovado',moneyCents(data.summary?.revenue_cents||0)]].map(([k,v])=><div className="card support-metric" key={k}><span>{k}</span><strong>{v}</strong><small>Dados reais da loja</small></div>)}</div>
 <section className="card support-panel"><div className="support-top"><div><h2>Lista de clientes</h2><p>Fotos e nomes do Discord, com atualização automática quando disponíveis.</p></div><span className="order-local">Servidor selecionado</span></div><div className="support-tools"><div className="support-search"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Buscar cliente ou ID do Discord"/></div></div>
 {error&&<div className="commerce-error">{error}</div>}{loading&&<p className="commerce-loading">Carregando clientes…</p>}
 <div className="support-tablewrap"><table className="support-table"><thead><tr><th>Cliente</th><th>Pedidos</th><th>Compras aprovadas</th><th>Total gasto</th><th>Último pedido</th><th/></tr></thead><tbody>{rows.map(c=><tr key={c.buyer_id} onClick={()=>setSelected(c.buyer_id)}><td><Buyer name={c.name} avatar={c.avatar_url} id={c.buyer_id}/></td><td>{c.orders}</td><td>{c.paid_orders}</td><td>{moneyCents(c.total_cents)}</td><td>{dateTime(c.last_order)}</td><td><ChevronRight size={16}/></td></tr>)}</tbody></table></div>
 {!rows.length&&!error&&!loading&&<div className="support-empty"><Users size={26}/><h3>Nenhum cliente encontrado</h3><p>Os compradores aparecerão após realizarem pedidos pelo bot.</p></div>}
 <div className="support-foot">{rows.length} cliente(s) · identificados pelo ID do Discord{data.truncated?' · Histórico limitado aos pedidos mais recentes':''}</div></section>
 {person&&<div className="order-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)setSelected(null)}}><section className="order-modal support-detail" role="dialog" aria-modal="true" aria-label="Histórico do cliente"><header><div><h2>Histórico do cliente</h2><p>{person.orders} pedido(s) registrado(s)</p></div><button onClick={()=>setSelected(null)}><X size={18}/></button></header><div className="order-body"><Buyer name={person.name} avatar={person.avatar_url} id={person.buyer_id}/><div className="support-clientstats"><div><span>Pedidos</span><strong>{person.orders}</strong></div><div><span>Compras aprovadas</span><strong>{person.paid_orders}</strong></div><div><span>Total gasto</span><strong>{moneyCents(person.total_cents)}</strong></div></div><h3>Pedidos</h3>{history.map(o=><div key={o.id} className="commerce-history"><div><strong>#{o.id.slice(0,8)}</strong><small>{dateTime(o.created_at)}</small><div className="commerce-history-lines">{o.items.map((p,i)=><span key={i}><ProductIcon emoji={p.emoji}/>{p.quantity}× {p.name}</span>)}</div></div><div><State value={o.status}/><strong>{moneyCents(o.total_cents)}</strong></div></div>)}</div><footer><button className="pill" onClick={()=>setSelected(null)}>Fechar</button></footer></section></div>}
 </div>;
}
