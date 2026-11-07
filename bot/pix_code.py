"""Gera Pix BR Code estático (EMV) para a chave configurada, com valor exato."""
import unicodedata
from decimal import Decimal

def field(tag, value):
    value=str(value)
    if len(value)>99: raise ValueError('Campo Pix muito longo')
    return f'{tag}{len(value):02d}{value}'

def normalize(value, limit):
    text=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().upper()
    return ''.join(c for c in text if c.isalnum() or c in ' .-/')[:limit].strip()

def pix_code(key,name,city,amount):
    key=key.strip()
    if not key or len(key)>77: raise ValueError('Chave Pix não configurada ou inválida')
    name=normalize(name,25)
    city=normalize(city,15)
    if not name or not city: raise ValueError('Nome e cidade Pix são obrigatórios')
    amount=Decimal(str(amount))
    if amount<=0: raise ValueError('Valor Pix inválido')
    merchant=field('00','br.gov.bcb.pix')+field('01',key)
    payload=(field('00','01')+field('26',merchant)+field('52','0000')+
             field('53','986')+field('54',f'{amount:.2f}')+field('58','BR')+
             field('59',name)+field('60',city)+field('62',field('05','***'))+'6304')
    crc=0xFFFF
    for byte in payload.encode('utf-8'):
        crc^=byte<<8
        for _ in range(8):crc=((crc<<1)^0x1021 if crc&0x8000 else crc<<1)&0xFFFF
    return payload+f'{crc:04X}'
