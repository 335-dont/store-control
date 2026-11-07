from app.db import Base, engine
from app import models  # noqa: F401
from app import store  # noqa: F401
from app import orders_api  # noqa: F401
Base.metadata.create_all(bind=engine)
print('Tabelas iniciais criadas.')
