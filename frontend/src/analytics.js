export const KEYS={orders:'store-control-orders-v1',catalog:'store-control-catalogs-v3',tickets:'store-control-tickets-v1'};
export function readStore(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}}
export const currency=value=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(value)||0);
export const dateKey=value=>{const d=new Date(value);if(Number.isNaN(d.getTime()))return '';return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
export function getAnalytics(){
 const orders=readStore(KEYS.orders,[]),catalog=readStore(KEYS.catalog,{catalogs:[],products:[]}),tickets=readStore(KEYS.tickets,[]);
 const products=Array.isArray(catalog.products)?catalog.products:[];
 const paid=orders.filter(o=>['paid','delivered'].includes(o.status));
 const revenue=paid.reduce((n,o)=>n+(Number(o.total)||0),0);
 const clients=new Set([...orders.map(o=>o.buyer),...tickets.map(t=>t.buyer)].filter(Boolean).map(s=>s.trim().toLocaleLowerCase('pt-BR')));
 const daily={};paid.forEach(o=>{const k=dateKey(o.createdAt);if(k)daily[k]=(daily[k]||0)+(Number(o.total)||0)});
 const inventoryValue=products.filter(p=>!p.unlimited).reduce((n,p)=>n+(Number(p.stock)||0)*(Number(p.price)||0),0);
 return {orders,tickets,products,paid,revenue,daily,clients:clients.size,avgTicket:paid.length?revenue/paid.length:0,available:products.filter(p=>p.active).reduce((n,p)=>n+(p.unlimited?0:Math.max(0,Number(p.stock)||0)),0),activeProducts:products.filter(p=>p.active).length,unlimited:products.filter(p=>p.active&&p.unlimited).length,outOfStock:products.filter(p=>!p.unlimited&&Number(p.stock)<=0).length,inventoryValue,awaiting:orders.filter(o=>o.status==='awaiting').length,review:orders.filter(o=>o.status==='review').length,approved:paid.length,openTickets:tickets.filter(t=>t.status!=='closed').length};
}
export function chartDays(days,daily){const now=new Date();now.setHours(12,0,0,0);return Array.from({length:days},(_,i)=>{const d=new Date(now);d.setDate(now.getDate()-(days-1-i));const k=dateKey(d);return {day:d.toLocaleDateString('pt-BR',{day:'2-digit',month:'short'}),value:daily[k]||0,date:k}})}
export function downloadCSV(rows,filename){const text='\uFEFF'+rows.map(row=>row.map(value=>'"'+String(value??'').replaceAll('"','""')+'"').join(';')).join('\r\n');const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
