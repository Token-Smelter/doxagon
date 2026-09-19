# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY apps/web/frontend/package*.json ./
RUN npm ci
COPY apps/web/frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim
WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY apps/ ./apps/
COPY scripts/ ./scripts/

# Install dependencies including the web backend
# We use --system to install into the global python environment in the container
RUN uv pip install --system -e ".[web]"

# Copy frontend build from stage 1
COPY --from=frontend-builder /app/frontend/build ./apps/web/frontend/build

# Expose port
EXPOSE 8000

# Run server
# We use the module syntax to run the app
CMD ["uvicorn", "apps.web.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
