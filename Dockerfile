# --- build the React app ---
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Python API + static frontend in one container ---
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/static
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
RUN useradd -m appuser
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app_factory --factory --host 0.0.0.0 --port ${PORT:-8000}"]
