import React,{useEffect,useMemo,useState} from 'react';
import './message-editor.css';
const TYPES=[['shop','Painel de compras'],['cart','Carrinho'],['stock','Estoque'],['pix','Pagamento Pix'],['review','Pagamento em análise'],['approved','Pagamento aprovado'],['rejected','Pagamento rejeitado'],['delivery','Entregas'],['ticket','Ticket de compra'],['logs','Logs'],['expired','Pedido expirado'],['order','Resumo do pedido']];
const BASE={title:'',description:'',color:'#C3A06B',footer:'',image:'',thumbnail:''};
// Exemplos de referência extraídos das mensagens conhecidas do bot; são editáveis e não alteram o bot até integração.
const DEFAULTS={
 shop:{title:'🛒 Comprar MM2',description:'Clique no botão abaixo para abrir seu carrinho e escolher seus produtos.',color:'#C3A06B'},
 cart:{title:'🛒 Seu carrinho',description:'Selecione uma categoria para visualizar os produtos disponíveis.\n\nTotal estimado: {valor}',footer:'Prévia • sem cobrança, pedido ou reserva de estoque'},
 stock:{title:'📦 Estoque disponível',description:'Confira os itens disponíveis na loja.'},
 pix:{title:'💠 Pagamento Pix',description:'Pedido: {pedido}\nValor: {valor}\n\nUtilize a chave ou o QR Code para pagar.'},
 review:{title:'🔎 Pagamento em análise',description:'Recebemos a confirmação do pagamento do pedido {pedido}. Aguarde a equipe.'},
 approved:{title:'✅ Pagamento aprovado',description:'O pagamento do pedido {pedido} foi aprovado.'},
 rejected:{title:'❌ Pagamento rejeitado',description:'O pagamento do pedido {pedido} não foi aprovado.'},
 delivery:{title:'🛒 Novo Pedido Entregue',description:'👤 **Cliente**\n{cliente}\n\n💵 **Valor Pago**\n{valor}\n\n🛍️ **Produtos Adquiridos**\n{produto}',color:'#D6B37A',footer:'Agradecemos pela sua preferência!'},
 ticket:{title:'🛒 Pedido Store Control',description:'Pedido {pedido}\nCliente: {cliente}\nTotal: {valor}',footer:'Pagamento manual • a equipe confirma o recebimento'},
 logs:{title:'📋 Registro de pedido',description:'Pedido: {pedido}\nCliente: {cliente}\nValor: {valor}'},
 expired:{title:'⌛ Pedido expirado',description:'O prazo de pagamento do pedido {pedido} terminou.'},
 order:{title:'🛒 Pedido Store Control',description:'{produto}',footer:'Pagamento manual • a equipe confirma o recebimento'}
};
const initial=(kind)=>({...BASE,...DEFAULTS[kind]});
export default function MessageEditor({notify}){
 const [guild,setGuild]=useState(''),[templates,setTemplates]=useState({}),[kind,setKind]=useState('cart'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false);
 const item=useMemo(()=>({...initial(kind),...templates[kind]}),[templates,kind]);
 const change=(key,value)=>{setSaved(false);setTemplates(old=>({...old,[kind]:{...initial(kind),...old[kind],[key]:value}}))};
 const get=async(url,id,opts={})=>{const r=await fetch(url,{credentials:'same-origin',headers:{'X-Store-Guild':id,...(opts.body?{'Content-Type':'application/json'}:{})},...opts});const d=await r.json();if(!r.ok)throw Error(d.detail||`HTTP ${r.status}`);return d};
 const load=async()=>{setBusy(true);setError('');try{const r=await fetch('/auth/selected-guild',{credentials:'same-origin'});const d=await r.json();if(!r.ok)throw Error(d.detail||'Faça login');const id=d.selected_guild_id||'';setGuild(id);if(!id){setTemplates({});setError('Selecione um servidor no perfil Discord');return}const t=await get('/api/store/message-templates',id);setTemplates(t.templates||{});setSaved(true)}catch(e){setError(e.message)}finally{setBusy(false)}};
 useEffect(()=>{load();window.addEventListener('store-guild-changed',load);return()=>window.removeEventListener('store-guild-changed',load)},[]);
 const save=async()=>{if(!guild)return;setBusy(true);setError('');try{const result=await get('/api/store/message-templates',guild,{method:'PUT',body:JSON.stringify({templates})});const check=await get('/api/store/message-templates',guild);if(JSON.stringify(result.templates)!==JSON.stringify(check.templates))throw Error('O banco não confirmou o salvamento');setTemplates(check.templates);setSaved(true);notify?.('Modelos salvos no banco de dados')}catch(e){setError('Não foi possível salvar: '+e.message)}finally{setBusy(false)}};
 const field=(label,key,multi=false,placeholder='')=><label className="msg-field"><span>{label}</span>{multi?<textarea rows={5} value={item[key]} placeholder={placeholder} onChange={e=>change(key,e.target.value)}/>:<input value={item[key]} placeholder={placeholder} onChange={e=>change(key,e.target.value)}/>}</label>;
 const preview=v=>(v||'').replaceAll('{cliente}','@cliente · @+100$').replaceAll('{valor}','R$ 100,00').replaceAll('{pedido}','1234').replaceAll('{produto}','🔪 Heartblade ×2 — R$ 16,00');
 return <div className="msg-editor"><section className="card msg-editor-card"><div className="msg-header"><div><div className="msg-eyebrow">PERSONALIZAÇÃO DO DISCORD</div><h2>Mensagens e embeds</h2><p>Edite os modelos de cada setor com uma prévia visual.</p></div><span className="msg-status">{saved?'Salvo no banco':'Alterações não salvas'}</span></div>
 <div className="msg-fields"><label className="msg-field"><span>Mensagem</span><select value={kind} onChange={e=>setKind(e.target.value)}>{TYPES.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
 <div className="msg-hint">O modelo inicial é uma referência editável. Seus dados já salvos têm prioridade e não são substituídos.</div>
 {field('Título','title',false,'Título da embed')}{field('Descrição','description',true,'Texto da mensagem')}
 <div className="msg-vars"><span>Variáveis disponíveis:</span>{['{cliente}','{valor}','{pedido}','{produto}'].map(x=><button key={x} type="button" title="Copiar variável" onClick={()=>navigator.clipboard?.writeText(x)}>{x}</button>)}</div>
 <div className="msg-two"><label className="msg-field"><span>Cor da embed</span><div className="msg-color"><input type="color" aria-label="Escolher cor" value={/^#[\da-fA-F]{6}$/.test(item.color)?item.color:'#5865F2'} onChange={e=>change('color',e.target.value)}/><input value={item.color} onChange={e=>change('color',e.target.value)} placeholder="#5865F2"/></div></label>{field('Rodapé','footer')}</div>
 {field('Imagem (URL HTTPS)','image',false,'https://...')}{field('Miniatura (URL HTTPS)','thumbnail',false,'https://...')}
 <div className="msg-actions"><button className="pill" disabled={busy} onClick={()=>{setTemplates(old=>{const next={...old};delete next[kind];return next});setSaved(false)}}>Restaurar modelo inicial</button><button className="pill primary" disabled={busy||!guild} onClick={save}>{busy?'Salvando…':'Salvar mensagens'}</button></div>{error&&<p role="alert" className="msg-error">{error}</p>}</div></section>
 <section className="card msg-preview-card"><div className="msg-header"><div><div className="msg-eyebrow">VISUALIZAÇÃO</div><h2>Prévia da embed</h2><p>Exemplo de como a mensagem pode aparecer no Discord.</p></div></div><div className="msg-preview" style={{borderLeftColor:/^#[\da-fA-F]{6}$/.test(item.color)?item.color:'#5865F2'}}>{item.thumbnail&&<img className="msg-thumbnail" src={item.thumbnail} alt="Miniatura"/>}<strong>{preview(item.title)||'Sem título'}</strong><p>{preview(item.description)||'Sem descrição'}</p>{item.image&&<img className="msg-image" src={item.image} alt="Imagem da embed"/>}{item.footer&&<div className="msg-footer">{preview(item.footer)}</div>}</div><p className="msg-disclaimer">Os modelos ficam salvos por servidor. O bot ainda não usa estes modelos automaticamente; essa integração será feita separadamente.</p></section></div>
}
