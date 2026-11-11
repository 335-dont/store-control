import React,{useEffect,useState} from 'react';
import './emojis.css';
import EmojiRecolor from './EmojiRecolor.jsx';
async function request(method,body){
 const selected=await fetch('/auth/selected-guild',{credentials:'same-origin'}).then(r=>r.json());
 const guild=selected.selected_guild_id;
 if(!guild)throw Error('Selecione um servidor no perfil');
 const r=await fetch('/api/store/application-emojis',{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Store-Guild':guild},...(body?{body:JSON.stringify(body)}:{})});
 const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.detail||'Falha ao consultar Discord');return data;
}
export async function fetchApplicationEmojis(){return (await request('GET')).emojis}
export default function Emojis(){
 const [items,setItems]=useState([]),[name,setName]=useState(''),[file,setFile]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[recolor,setRecolor]=useState(false),[recolored,setRecolored]=useState(null);
 const refresh=async()=>{setBusy(true);setError('');try{setItems(await fetchApplicationEmojis())}catch(e){setError(e.message)}finally{setBusy(false)}};
 useEffect(()=>{refresh();const cb=()=>refresh();window.addEventListener('store-guild-changed',cb);return()=>window.removeEventListener('store-guild-changed',cb)},[]);
 const upload=async()=>{if(!file)return;setBusy(true);setError('');setMessage('');try{
 if(file.size>256*1024)throw Error('O arquivo deve ter até 256 KB');
 const data=recolor?recolored:await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Falha ao ler imagem'));reader.readAsDataURL(file)});
 if(!data)throw Error('Aguarde a geração da imagem recolorida');
 await request('POST',{name,data});setFile(null);setName('');setRecolor(false);setRecolored(null);setMessage('Emoji criado no aplicativo do bot');await refresh();
 }catch(e){setError(e.message)}finally{setBusy(false)}};
 const remove=async(item)=>{if(!window.confirm(`Excluir ${item.name} do aplicativo? Produtos que usam esse emoji perderão a imagem.`))return;setBusy(true);setError('');try{const selected=await fetch('/auth/selected-guild',{credentials:'same-origin'}).then(r=>r.json());const r=await fetch('/api/store/application-emojis/'+item.id,{method:'DELETE',credentials:'same-origin',headers:{'X-Store-Guild':selected.selected_guild_id}});if(!r.ok)throw Error((await r.json()).detail||'Falha ao excluir');await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}};
 return <div className="module-page eleve-emojis"><h1>Emojis do bot</h1><p>Emojis do aplicativo Eleve: disponíveis para o bot em todos os servidores, sem ocupar vagas de emojis dos servidores.</p>
 <section className="card emoji-upload"><h2>Adicionar emoji</h2><div className="emoji-upload-fields"><label>Nome<input value={name} maxLength={32} placeholder="heartblade" onChange={e=>setName(e.target.value)}/></label><label>Imagem PNG, GIF ou WebP (até 256 KB)<input type="file" accept="image/png,image/gif,image/webp" onChange={e=>{setFile(e.target.files?.[0]||null);setRecolor(false);setRecolored(null)}}/></label><button className="pill primary" disabled={busy||!file||(recolor&&!recolored)||!/^[a-zA-Z0-9_]{2,32}$/.test(name)} onClick={upload}>Enviar para o bot</button></div>{file&&file.type!=='image/gif'&&<div className="emoji-recolor-switch"><label><input type="checkbox" checked={recolor} onChange={e=>{setRecolor(e.target.checked);setRecolored(null)}}/> Recolorir antes de enviar</label>{recolor&&<EmojiRecolor file={file} onReady={setRecolored}/>}</div>}{file&&file.type==='image/gif'&&<p>GIF animado: enviado sem recoloração para preservar a animação.</p>}</section>
 <section className="card emoji-library"><div className="emoji-heading"><h2>Biblioteca do aplicativo ({items.length})</h2><button className="pill" disabled={busy} onClick={refresh}>Atualizar</button></div>{error&&<p role="alert" className="emoji-error">{error}</p>}{message&&<p role="status">{message}</p>}<div className="emoji-grid">{items.map(e=><div className="emoji-item" key={e.id}><img src={e.url} alt={e.name}/><strong>{e.name}</strong><small>{e.animated?'Animado':'Estático'}</small><button className="pill" onClick={()=>navigator.clipboard.writeText(e.code)}>Copiar emoji</button><button className="pill" disabled={busy} onClick={()=>remove(e)}>Excluir</button></div>)}</div>{!items.length&&!busy&&<p>Nenhum emoji encontrado. Envie o primeiro acima.</p>}</section></div>
}
