FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY init_db.py ./init_db.py
CMD ["sh", "-c", "python init_db.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
