import React,{useEffect,useMemo,useState} from 'react';
import './message-editor.css';
const TYPES=[['shop','Painel de compras'],['cart','Carrinho'],['stock','Estoque'],['pix','Pagamento Pix'],['review','Pagamento em análise'],['approved','Pagamento aprovado'],['rejected','Pagamento rejeitado'],['delivery','Entregas'],['ticket','Ticket de compra'],['logs','Logs'],['expired','Pedido expirado'],['order','Resumo do pedido'],['purchase_confirmed','Compra confirmada (manual)'],['private_server','Servidor privado (link)']];
const BASE={title:'',description:'',color:'#C3A06B',footer:'',image:'',thumbnail:'',emojis:{}};
const EMOJI_FIELDS={
 shop:[['shop_buy','Botão: comprar MM2','🛒'],['shop_history','Botão: histórico','📜'],['shop_stock','Botão: visualizar estoque','📦']],
 cart:[['cart_title','Título do carrinho','🛒']],
 stock:[['stock_title','Título do estoque','📦']],
 pix:[['pix_title','Título do Pix','💠']],
 review:[['review_title','Título: pagamento em análise','🔎']],
 approved:[['approved_title','Título: pagamento aprovado','✅']],
 rejected:[['rejected_title','Título: pagamento rejeitado','❌']],
 delivery:[['delivery_title','Título: entregas','🛒']],
 logs:[['logs_title','Título: logs','📋']],
 expired:[['expired_title','Título: pedido expirado','⌛']],
 order:[['order_title','Título: pedido','🛒']],
 purchase_confirmed:[['confirmed_notice','Aviso de confirmação','✅'],['confirmed_products','Produtos adquiridos','🛍️'],['confirmed_item','Produto','📦'],['confirmed_total','Total','💰'],['confirmed_buyer','Comprador','👤'],['confirmed_delivery','Entrega','📦'],['staff_link','Menu: enviar link','🔗'],['staff_notify','Menu: notificar cliente','🔔'],['staff_delivered','Menu: produto entregue','📦']],
 private_server:[['private_button','Botão: entrar no servidor','🔰']],
 ticket:[['staff_approve','Menu: aprovar pagamento','✅'],['staff_reject','Menu: rejeitar pagamento','❌'],['ticket_copy','Botão: copiar Pix','🔗'],['ticket_paid','Botão: já paguei','💳']]
};
const emojiImage=(v)=>{const m=/^<a?:[A-Za-z0-9_]{2,32}:([0-9]{15,22})>$/.exec(v||'');return m?`https://cdn.discordapp.com/emojis/${m[1]}.png`:null};
// Exemplos de referência extraídos das mensagens conhecidas do bot; são editáveis e não alteram o bot até integração.
const DEFAULTS={
 shop:{title:'🛒 Loja MM2',description:'Escolha uma opção abaixo para começar.',color:'#C3A06B',footer:''},
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
 order:{title:'🛒 Pedido Store Control',description:'{produto}',footer:'Pagamento manual • a equipe confirma o recebimento'},
 purchase_confirmed:{title:'Compra Confirmada',description:'{emoji_confirmed_notice} Um dos produtos que você adquiriu possui entrega manual. Aguarde um entregador.\n\n**{emoji_confirmed_products} Produtos Adquiridos**\n{produto}\n\n**{emoji_confirmed_total} Total:** {valor}\n\n**{emoji_confirmed_buyer} Comprador**\n{cliente}\n\n**{emoji_confirmed_delivery} Entrega**\nAssim que um entregador assumir seu pedido, ele enviará uma mensagem neste canal.',color:'#D6B37A'},
 private_server:{title:'Store Control',description:'• Entre em um de nossos servidores VIP abaixo\n• Ao entrar, avise o entregador neste canal e aguarde seu produto!\n\n> {link}',color:'#D6B37A'}
};
const initial=(kind)=>({...BASE,...DEFAULTS[kind]});
export default function MessageEditor({notify}){
 const [emojiPicker,setEmojiPicker]=useState(null),[emojiSearch,setEmojiSearch]=useState(''),[emojiLoading,setEmojiLoading]=useState(false),[emojiError,setEmojiError]=useState('');
 const [channelId,setChannelId]=useState(''),[messageId,setMessageId]=useState(''),[publishStatus,setPublishStatus]=useState(''),[guild,setGuild]=useState(''),[templates,setTemplates]=useState({}),[kind,setKind]=useState('cart'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false),[appEmojis,setAppEmojis]=useState([]);
 const item=useMemo(()=>({...initial(kind),...templates[kind]}),[templates,kind]);
 const change=(key,value)=>{setSaved(false);setTemplates(old=>({...old,[kind]:{...initial(kind),...old[kind],[key]:value}}))};
 const get=async(url,id,opts={})=>{const r=await fetch(url,{credentials:'same-origin',headers:{'X-Store-Guild':id,...(opts.body?{'Content-Type':'application/json'}:{})},...opts});const d=await r.json();if(!r.ok)throw Error(d.detail||`HTTP ${r.status}`);return d};
 const load=async()=>{setBusy(true);setError('');try{const r=await fetch('/auth/selected-guild',{credentials:'same-origin'});const d=await r.json();if(!r.ok)throw Error(d.detail||'Faça login');const id=d.selected_guild_id||'';setGuild(id);if(!id){setTemplates({});setError('Selecione um servidor no perfil Discord');return}const t=await get('/api/store/message-templates',id);setTemplates(t.templates||{});setSaved(true)}catch(e){setError(e.message)}finally{setBusy(false)}};
 useEffect(()=>{load();window.addEventListener('store-guild-changed',load);return()=>window.removeEventListener('store-guild-changed',load)},[]);
 const refreshEmojis=async(id=guild)=>{
  if(!id)return;
  setEmojiLoading(true);setEmojiError('');
  try{const result=await get('/api/store/application-emojis',id);setAppEmojis(Array.isArray(result.emojis)?result.emojis:[])}
  catch(e){setAppEmojis([]);setEmojiError(e.message||'Falha ao carregar emojis')}
  finally{setEmojiLoading(false)}
 };
 useEffect(()=>{setAppEmojis([]);setEmojiError('');if(guild)void refreshEmojis(guild)},[guild]);
 const openEmojiPicker=(key,label,fallback)=>{setEmojiSearch('');setEmojiPicker({key,label,fallback});void refreshEmojis()};
 const selectEmoji=(value)=>{change('emojis',{...item.emojis,[emojiPicker.key]:value});setEmojiPicker(null)};
 const save=async()=>{if(!guild)return;setBusy(true);setError('');try{const result=await get('/api/store/message-templates',guild,{method:'PUT',body:JSON.stringify({templates})});const check=await get('/api/store/message-templates',guild);if(JSON.stringify(result.templates)!==JSON.stringify(check.templates))throw Error('O banco não confirmou o salvamento');setTemplates(check.templates);setSaved(true);notify?.('Modelos salvos no banco de dados')}catch(e){setError('Não foi possível salvar: '+e.message)}finally{setBusy(false)}};
 const publish=async()=>{
   if(!/^\d{17,22}$/.test(channelId)||!/^\d{17,22}$/.test(messageId)){setError('Informe os IDs numericos do canal e da mensagem');return}
   if(!saved){setError('Salve suas alteracoes antes de atualizar');return}
   setBusy(true);setError('');setPublishStatus('Solicitacao enviada ao bot…');
   try{
     await get('/api/store/panel-update',guild,{method:'POST',body:JSON.stringify({channel_id:channelId,message_id:messageId})});
     for(let i=0;i<12;i++){
       await new Promise(resolve=>setTimeout(resolve,1500));
       const result=await get('/api/store/panel-update',guild);
       if(result.status==='done'){setPublishStatus('Painel atualizado no Discord!');notify?.('Painel atualizado');return}
       if(result.status==='error')throw Error(result.detail||'Falha ao atualizar');
     }
     setPublishStatus('Bot ainda processando. Confira novamente em instantes.');
   }catch(e){setError('Falha na publicacao: '+e.message);setPublishStatus('')}finally{setBusy(false)}
 };
 const field=(label,key,multi=false,placeholder='')=><label className="msg-field"><span>{label}</span>{multi?<textarea rows={5} value={item[key]} placeholder={placeholder} onChange={e=>change(key,e.target.value)}/>:<input value={item[key]} placeholder={placeholder} onChange={e=>change(key,e.target.value)}/>}</label>;
 const preview=v=>(v||'').replace(/\{emoji_([a-z_]+)\}/g,(_,k)=>item.emojis?.[k]||EMOJI_FIELDS[kind]?.find(x=>x[0]===k)?.[2]||'📦').replaceAll('{link}','https://www.roblox.com/games/...').replaceAll('{cliente}','@cliente · @+100$').replaceAll('{valor}','R$ 100,00').replaceAll('{pedido}','1234').replaceAll('{produto}','🔪 Heartblade ×2 — R$ 16,00');
 const visual=v=>preview(v).split(/(<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>)/g).map((part,i)=>emojiImage(part)?<img key={i} src={emojiImage(part)} alt={part} style={{width:20,height:20,verticalAlign:'middle',objectFit:'contain'}}/>:part);
 return <><div className="msg-editor"><section className="card msg-editor-card"><div className="msg-header"><div><div className="msg-eyebrow">PERSONALIZAÇÃO DO DISCORD</div><h2>Mensagens e embeds</h2><p>Edite os modelos de cada setor com uma prévia visual.</p></div><span className="msg-status">{saved?'Salvo no banco':'Alterações não salvas'}</span></div>
 <div className="msg-fields"><label className="msg-field"><span>Mensagem</span><select value={kind} onChange={e=>setKind(e.target.value)}>{TYPES.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
 <div className="msg-hint">{kind==='shop'?'Painel público: após salvar, use /publicar_loja no canal desejado para publicar ou atualizar a mensagem existente. Os botões continuam funcionando.':'Os modelos iniciais são editáveis. Suas configurações salvas têm prioridade.'}</div>
 {field('Título','title',false,'Título da embed')}{field('Descrição','description',true,'Texto da mensagem')}
 <div className="msg-vars"><span>Variáveis disponíveis:</span>{['{cliente}','{valor}','{pedido}','{produto}',...(kind==='private_server'?['{link}']:[])].map(x=><button key={x} type="button" title="Copiar variável" onClick={()=>navigator.clipboard?.writeText(x)}>{x}</button>)}</div>
 <div className="msg-two"><label className="msg-field"><span>Cor da embed</span><div className="msg-color"><input type="color" aria-label="Escolher cor" value={/^#[\da-fA-F]{6}$/.test(item.color)?item.color:'#5865F2'} onChange={e=>change('color',e.target.value)}/><input value={item.color} onChange={e=>change('color',e.target.value)} placeholder="#5865F2"/></div></label>{field('Rodapé','footer')}</div>
 {field('Imagem (URL HTTPS)','image',false,'https://...')}{field('Miniatura (URL HTTPS)','thumbnail',false,'https://...')}
 {!!EMOJI_FIELDS[kind]&&<div className="msg-emoji-config"><h3>Emojis dos textos e componentes</h3><p>Selecione um emoji do aplicativo do bot ou mantenha o emoji padrão. As alterações valem para as novas mensagens.</p>{EMOJI_FIELDS[kind].map(([key,label,fallback])=><label className="msg-field" key={key}><span>{label}</span><div className="msg-emoji-row"><span className="msg-emoji-sample">{emojiImage(item.emojis?.[key])?<img src={emojiImage(item.emojis[key])} alt=""/>:item.emojis?.[key]||fallback}</span><button type="button" className="msg-emoji-open" onClick={()=>openEmojiPicker(key,label,fallback)}><span>{appEmojis.find(e=>e.code===item.emojis?.[key])?.name|| (item.emojis?.[key]?'Emoji selecionado':'Escolher emoji do bot')}</span><span aria-hidden="true">▦</span></button></div></label>)}</div>}
 {kind==='shop'&&<div className="msg-publish"><strong>Atualizar painel no Discord</strong><p>Informe o ID do canal e o ID da mensagem publica ja existente. O bot atualiza sem duplicar.</p><div className="msg-two"><label className="msg-field"><span>ID do canal</span><input value={channelId} onChange={e=>setChannelId(e.target.value.trim())} placeholder="ID do canal"/></label><label className="msg-field"><span>ID da mensagem</span><input value={messageId} onChange={e=>setMessageId(e.target.value.trim())} placeholder="ID da mensagem"/></label></div><button className="pill primary" disabled={busy||!guild||!saved} onClick={publish}>Atualizar no Discord</button>{publishStatus&&<p role="status">{publishStatus}</p>}</div>}
 <div className="msg-actions"><button className="pill" disabled={busy} onClick={()=>{setTemplates(old=>{const next={...old};delete next[kind];return next});setSaved(false)}}>Restaurar modelo inicial</button><button className="pill primary" disabled={busy||!guild} onClick={save}>{busy?'Salvando…':'Salvar mensagens'}</button></div>{error&&<p role="alert" className="msg-error">{error}</p>}</div></section>
 <section className="card msg-preview-card"><div className="msg-header"><div><div className="msg-eyebrow">VISUALIZAÇÃO</div><h2>Prévia da embed</h2><p>Exemplo de como a mensagem pode aparecer no Discord.</p></div></div><div className="msg-preview" style={{borderLeftColor:/^#[\da-fA-F]{6}$/.test(item.color)?item.color:'#5865F2'}}>{item.thumbnail&&<img className="msg-thumbnail" src={item.thumbnail} alt="Miniatura"/>}<strong>{visual(item.title)||'Sem título'}</strong><p>{visual(item.description)||'Sem descrição'}</p>{item.image&&<img className="msg-image" src={item.image} alt="Imagem da embed"/>}{item.footer&&<div className="msg-footer">{visual(item.footer)}</div>}</div>{kind==='private_server'&&<div className="msg-shop-buttons"><span>{item.emojis?.private_button||'🔰'} Entrar no Servidor</span></div>}{kind==='shop'&&<div className="msg-shop-buttons"><span>🛒 Comprar MM2</span><span>📜 Histórico de Compras</span><span>📦 Visualizar Estoque</span></div>}<p className="msg-disclaimer">{kind==='shop'?'Salve e execute /publicar_loja no canal público para atualizar o painel. O comando reutiliza o painel encontrado entre as 100 mensagens recentes do canal.':'Modelos salvos são usados nas mensagens já integradas (Carrinho, Resumo e Entregas). Outros setores serão conectados gradualmente.'}</p></section></div>
 {emojiPicker&&<div className="msg-emoji-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)setEmojiPicker(null)}}><section className="msg-emoji-dialog" role="dialog" aria-modal="true" aria-label={'Escolher emoji: '+emojiPicker.label}>
  <div className="msg-emoji-dialog-head"><div><h2>Selecionar emoji</h2><p>{emojiPicker.label} · Emojis do aplicativo Eleve</p></div><button type="button" onClick={()=>setEmojiPicker(null)} aria-label="Fechar">✕</button></div>
  <div className="msg-emoji-dialog-content"><input className="msg-emoji-search" value={emojiSearch} onChange={e=>setEmojiSearch(e.target.value)} placeholder="Buscar emoji pelo nome..." autoFocus/>
  {emojiLoading&&<p role="status">Carregando emojis do bot…</p>}
  {emojiError&&<div className="msg-emoji-alert" role="alert"><p>Não foi possível carregar os emojis: {emojiError}</p><button type="button" onClick={()=>refreshEmojis()}>Tentar novamente</button></div>}
  {!emojiLoading&&!emojiError&&<><div className="msg-emoji-grid">{appEmojis.filter(e=>e.name.toLowerCase().includes(emojiSearch.trim().toLowerCase())).map(e=><button type="button" key={e.id} title={e.name} className={item.emojis?.[emojiPicker.key]===e.code?'selected':''} onClick={()=>selectEmoji(e.code)}><img src={e.url} alt="" loading="lazy"/><span>{e.name}</span></button>)}</div>{!appEmojis.length&&<p className="msg-emoji-empty">Nenhum emoji cadastrado no aplicativo. Envie imagens na aba Emojis e volte aqui.</p>}{appEmojis.length>0&&!appEmojis.some(e=>e.name.toLowerCase().includes(emojiSearch.trim().toLowerCase()))&&<p className="msg-emoji-empty">Nenhum emoji encontrado com esse nome.</p>}</>}
  </div><div className="msg-emoji-dialog-footer"><button type="button" onClick={()=>selectEmoji('')}>Usar padrão ({emojiPicker.fallback})</button><button type="button" onClick={()=>setEmojiPicker(null)}>Cancelar</button></div>
 </section></div>}
 </>
}
