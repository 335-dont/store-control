import React from 'react';
import './commerce.css';
export function Buyer({name,avatar,id}){
 return <div className="commerce-buyer"><img src={avatar} alt="" loading="lazy" onError={e=>{e.currentTarget.src='https://cdn.discordapp.com/embed/avatars/0.png'}}/><div><strong>{name||`Usuário ${String(id||'').slice(-6)}`}</strong><small>ID: {id}</small></div></div>;
}
export function ProductIcon({emoji}){
 const e=String(emoji||'');const match=/^<a?:[\w]+:(\d{15,22})>$/.exec(e);
 if(match)return <img className="commerce-product-icon" src={`https://cdn.discordapp.com/emojis/${match[1]}.${e.startsWith('<a:')?'gif':'png'}`} alt=""/>;
 if(e.startsWith('https://'))return <img className="commerce-product-icon" src={e} alt=""/>;
 return <span className="commerce-product-icon">{e||'📦'}</span>;
}
export const statusLabel={awaiting_payment:'Aguardando pagamento',payment_review:'Em análise',approved:'Pagamento aprovado',delivered:'Entregue',rejected:'Rejeitado',cancelled:'Cancelado',expired:'Expirado'};
export function State({value}){return <span className={'commerce-status '+(value||'')}>{statusLabel[value]||value}</span>}
