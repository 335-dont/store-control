/* Eleve: push-only service worker. Authenticated API responses are never cached. */
self.addEventListener('push', event => {
 let data={};try{data=event.data?.json()||{}}catch{}
 const title=typeof data.title==='string'?data.title:'Eleve — Novo aviso';
 const body=typeof data.body==='string'?data.body:'Há uma atualização na loja.';
 const url=data.url==='/?view=pedidos'?data.url:'/';
 event.waitUntil(self.registration.showNotification(title,{
  body,icon:'/eleve-192.png',badge:'/eleve-192.png',tag:typeof data.tag==='string'?data.tag:'eleve',
  data:{url},renotify:false
 }));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();
 event.waitUntil((async()=>{
  const link=new URL(event.notification.data?.url||'/',self.location.origin).href;
  const clients=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  const existing=clients.find(c=>new URL(c.url).origin===self.location.origin);
  if(existing){await existing.navigate(link);return existing.focus()}
  return self.clients.openWindow(link)
 })());
});
