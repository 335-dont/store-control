import React,{useEffect,useRef,useState} from 'react';

const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
const rgb=(hex)=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));

export default function EmojiRecolor({file,onReady}){
 const canvas=useRef(null),source=useRef(null),[target,setTarget]=useState(null),[color,setColor]=useState('#3b82f6'),[tolerance,setTolerance]=useState(65),[strength,setStrength]=useState(100),[error,setError]=useState('');
 useEffect(()=>{
  if(!file){source.current=null;setTarget(null);onReady(null);return}
  let active=true;const url=URL.createObjectURL(file);const image=new Image();
  image.onload=()=>{if(!active)return;const c=document.createElement('canvas');c.width=image.naturalWidth;c.height=image.naturalHeight;const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0);source.current=ctx.getImageData(0,0,c.width,c.height);const x=Math.floor(c.width/2),y=Math.floor(c.height/2),i=(y*c.width+x)*4;const p=source.current.data;setTarget([p[i],p[i+1],p[i+2]]);setError('');};
  image.onerror=()=>setError('Não foi possível abrir esta imagem');image.src=url;
  return()=>{active=false;URL.revokeObjectURL(url);source.current=null};
 },[file]);
 useEffect(()=>{
  const original=source.current;if(!original||!target||!canvas.current)return;
  const c=canvas.current;c.width=original.width;c.height=original.height;const ctx=c.getContext('2d');const output=new ImageData(new Uint8ClampedArray(original.data),original.width,original.height);
  const d=output.data,originalPixels=original.data,desired=rgb(color);
  for(let i=0;i<d.length;i+=4){
   if(originalPixels[i+3]<8)continue;
   const p=[originalPixels[i],originalPixels[i+1],originalPixels[i+2]];
   const delta=distance(p,target);
   const weight=Math.max(0,Math.min(1,(tolerance+22-delta)/22))*strength/100;
   if(weight===0)continue;
   const brightness=(p[0]+p[1]+p[2])/3;
   const reference=(target[0]+target[1]+target[2])/3;
   const ratio=Math.max(.55,Math.min(1.45,reference?brightness/reference:1));
   for(let j=0;j<3;j++)d[i+j]=p[j]*(1-weight)+Math.min(255,desired[j]*ratio)*weight;
  }
  ctx.putImageData(output,0,0);
  c.toBlob(blob=>{if(!blob){setError('Falha ao gerar PNG');onReady(null);return}if(blob.size>256*1024){setError('PNG recolorido excedeu 256 KB. Reduza a imagem antes do envio.');onReady(null);return}setError('');const reader=new FileReader();reader.onload=()=>onReady(reader.result);reader.readAsDataURL(blob)},'image/png');
 },[target,color,tolerance,strength,file]);
 const pick=(e)=>{const c=canvas.current,src=source.current;if(!c||!src)return;const rect=c.getBoundingClientRect();const x=Math.max(0,Math.min(c.width-1,Math.floor((e.clientX-rect.left)*c.width/rect.width))),y=Math.max(0,Math.min(c.height-1,Math.floor((e.clientY-rect.top)*c.height/rect.height)));const i=(y*c.width+x)*4;if(src.data[i+3]<8){setError('Clique numa área visível da imagem');return}setTarget([src.data[i],src.data[i+1],src.data[i+2]])};
 return <div className="emoji-recolor"><div className="emoji-recolor-top"><div><strong>Editor de cores</strong><p>Clique na parte da imagem que deseja recolorir (por exemplo, a seta). O fundo permanece intacto quando tem outra cor.</p></div><canvas ref={canvas} onClick={pick} title="Clique na cor original que deseja substituir"/></div><div className="emoji-recolor-controls"><label>Nova cor <input type="color" value={color} onChange={e=>setColor(e.target.value)}/><input className="emoji-hex" value={color} maxLength={7} onChange={e=>{if(/^#[0-9a-fA-F]{6}$/.test(e.target.value))setColor(e.target.value)}}/></label><label>Tolerância de cores: {tolerance}<input type="range" min="10" max="150" value={tolerance} onChange={e=>setTolerance(Number(e.target.value))}/></label><label>Intensidade: {strength}%<input type="range" min="0" max="100" value={strength} onChange={e=>setStrength(Number(e.target.value))}/></label></div>{error&&<p className="emoji-error" role="alert">{error}</p>}<small>Prévia gerada no navegador. Ao enviar, a versão PNG recolorida será cadastrada como novo emoji do aplicativo. O original não será alterado.</small></div>
}
