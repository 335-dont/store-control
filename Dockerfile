# Site + API em um único serviço Railway (staging)
FROM node:22-alpine AS webbuild
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/init_db.py ./init_db.py
COPY --from=webbuild /web/dist ./public
CMD ["sh", "-c", "python init_db.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
