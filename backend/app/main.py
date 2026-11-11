from decimal import Decimal
import os
import secrets
from pathlib import Path
from fastapi import Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import get_db
from .models import Catalog, Product
from .auth import router as auth_router, session_user
from .store import router as store_router
from .bot_stock import router as bot_stock_router
from .orders_api import router as orders_router
from .pix_settings import router as pix_router
from .loyalty import router as loyalty_router
from .message_templates import router as message_templates_router
from .emoji_api import router as emoji_router

app = FastAPI(title='Store Control API', version='0.2.0', docs_url=None if os.getenv('APP_ENV') == 'production' else '/docs', redoc_url=None if os.getenv('APP_ENV') == 'production' else '/redoc', openapi_url=None if os.getenv('APP_ENV') == 'production' else '/openapi.json')

app.include_router(auth_router)
app.include_router(store_router)
app.include_router(bot_stock_router)
app.include_router(orders_router)
app.include_router(pix_router)
app.include_router(loyalty_router)
app.include_router(message_templates_router)
app.include_router(emoji_router)

@app.middleware('http')
async def protect_api(request: Request, call_next):
    if request.url.path.startswith('/api/'):
        if os.getenv('APP_ENV') == 'production' and not request.url.path.startswith(('/api/store/', '/api/bot/')):
            # Fase de transição: não expor dados de todos os servidores a qualquer usuário logado.
            # API de catálogo permanece bloqueada até adicionar guild_id e autorização por servidor.
            return JSONResponse({'detail': 'API de catálogo indisponível até implementar isolamento por servidor'}, status_code=503)
        if request.url.path.startswith(('/api/store/', '/api/bot/')):
            return await call_next(request)
        key = os.getenv('API_ACCESS_KEY', '')
        if key and not secrets.compare_digest(request.headers.get('X-API-Key', ''), key):
            return JSONResponse({'detail': 'Não autorizado'}, status_code=401)
    return await call_next(request)

# Somente para o frontend de desenvolvimento local; não habilitar origens públicas sem autenticação.
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

class CatalogIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default='📁', max_length=500)

class CatalogOut(CatalogIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    position: int

class ProductIn(BaseModel):
    catalog_id: int
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default='📦', max_length=500)
    price: Decimal = Field(ge=Decimal('0.10'), max_digits=12, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    unlimited: bool = False
    active: bool = True

class ProductOut(ProductIn):
    model_config = ConfigDict(from_attributes=True)
    id: int

class ImportCatalog(CatalogIn):
    local_id: str = Field(min_length=1, max_length=100)

class ImportProduct(BaseModel):
    catalog_local_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default='📦', max_length=500)
    price: Decimal = Field(ge=Decimal('0.10'), max_digits=12, decimal_places=2)
    stock: int = Field(ge=0)
    unlimited: bool = False
    active: bool = True

class ImportSnapshot(BaseModel):
    catalogs: list[ImportCatalog] = Field(max_length=1000)
    products: list[ImportProduct] = Field(max_length=10000)

@app.get('/health')
def health():
    return {'status': 'ok', 'phase': 'catalog-migration-preview'}

@app.get('/api/catalogs', response_model=list[CatalogOut])
def list_catalogs(db: Session = Depends(get_db)):
    return db.scalars(select(Catalog).order_by(Catalog.position, Catalog.id)).all()

@app.post('/api/catalogs', response_model=CatalogOut, status_code=status.HTTP_201_CREATED)
def create_catalog(payload: CatalogIn, db: Session = Depends(get_db)):
    obj = Catalog(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@app.get('/api/products', response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.scalars(select(Product).order_by(Product.id)).all()

@app.post('/api/products', response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    if db.get(Catalog, payload.catalog_id) is None:
        raise HTTPException(404, 'Catálogo não encontrado')
    obj = Product(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@app.get('/api/snapshot')
def get_snapshot(db: Session = Depends(get_db)):
    catalogs = db.scalars(select(Catalog).order_by(Catalog.position, Catalog.id)).all()
    products = db.scalars(select(Product).order_by(Product.id)).all()
    return {'catalogs': [CatalogOut.model_validate(c).model_dump(mode='json') for c in catalogs],
            'products': [ProductOut.model_validate(p).model_dump(mode='json') for p in products]}

@app.post('/api/migration/import', status_code=201)
def import_snapshot(payload: ImportSnapshot, db: Session = Depends(get_db)):
    # Importação somente em banco vazio, sem exclusão ou substituição de registros.
    if db.scalar(select(func.count()).select_from(Catalog)) or db.scalar(select(func.count()).select_from(Product)):
        raise HTTPException(409, 'Banco não está vazio. Importação bloqueada para proteger dados existentes.')
    keys = [c.local_id for c in payload.catalogs]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, 'IDs de catálogos duplicados')
    if any(p.catalog_local_id not in set(keys) for p in payload.products):
        raise HTTPException(422, 'Produto com catálogo inexistente')
    try:
        mapping = {}
        for i, cat in enumerate(payload.catalogs):
            obj = Catalog(name=cat.name, emoji=cat.emoji, position=i)
            db.add(obj)
            db.flush()
            mapping[cat.local_id] = obj.id
        for product in payload.products:
            db.add(Product(catalog_id=mapping[product.catalog_local_id], **product.model_dump(exclude={'catalog_local_id'})))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'catalogs_imported': len(payload.catalogs), 'products_imported': len(payload.products)}

# Serve a interface compilada no mesmo domínio, sem expor credenciais no navegador.
PUBLIC_DIR = Path(__file__).resolve().parent.parent / 'public'

@app.get('/', include_in_schema=False)
def index():
    if not (PUBLIC_DIR / 'index.html').exists():
        raise HTTPException(404, 'Frontend não compilado')
    return FileResponse(PUBLIC_DIR / 'index.html')

@app.get('/{path:path}', include_in_schema=False)
def frontend_asset(path: str):
    target = (PUBLIC_DIR / path).resolve()
    if not target.is_relative_to(PUBLIC_DIR.resolve()):
        raise HTTPException(404)
    if target.is_file():
        return FileResponse(target)
    if (PUBLIC_DIR / 'index.html').exists():
        return FileResponse(PUBLIC_DIR / 'index.html')
    raise HTTPException(404)
