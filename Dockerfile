# =============================================================================
# Multi-stage Production Dockerfile for AI Weapon Detection System
# Optimized for security, performance, and minimal attack surface
# =============================================================================

# Stage 1: Base builder with system dependencies
FROM python:3.10-slim as base-builder

LABEL maintainer="DevOps Engineer <devops@company.com>" \
      description="AI-Powered Real-time Weapon Detection System" \
      version="1.0" \
      vendor="SecureVision AI"

# Security: Create non-root user early
RUN groupadd -r appuser && useradd -r -g appuser -s /bin/false appuser

# Install system dependencies in single layer to reduce image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    protobuf-compiler \
    libprotobuf-dev \
    libgl1-mesa-glx \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libglib2.0-0 \
    libgtk-3-0 \
    libavcodec59 \
    libavformat59 \
    libswscale6 \
    libjpeg-dev \
    libpng-dev \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Stage 2: Python dependencies builder
FROM base-builder as python-builder

# Set environment variables for optimal Python behavior
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create virtual environment for dependency isolation
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip for security and performance
RUN pip install --upgrade pip setuptools wheel

# Copy requirements first for better Docker layer caching
COPY requirements.txt /tmp/requirements.txt

# Install Python dependencies with optimizations
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir \
    opencv-python-headless \
    gunicorn \
    gevent \
    prometheus-client \
    structlog

# Stage 3: TensorFlow Object Detection API setup
FROM python-builder as tf-builder

# Install TensorFlow Object Detection API
WORKDIR /build
RUN git clone --depth 1 --branch master https://github.com/tensorflow/models.git \
    && cd models/research \
    && protoc object_detection/protos/*.proto --python_out=. \
    && cp object_detection/meta_architectures/*.py /opt/venv/lib/python3.10/site-packages/ || true

# Preserve the object_detection directory in a persistent location
RUN mv build/models/research/object_detection /object_detection

# Stage 4: Final production image
FROM python:3.10-slim as production

# Security and performance environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    WORKERS=4 \
    WORKER_CLASS=gevent \
    WORKER_CONNECTIONS=1000 \
    MAX_REQUESTS=1000 \
    MAX_REQUESTS_JITTER=50 \
    TIMEOUT=30 \
    KEEP_ALIVE=2 \
    PRELOAD_APP=true

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libglib2.0-0 \
    libavcodec59 \
    libavformat59 \
    libswscale6 \
    libjpeg62-turbo \
    libpng16-16 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -s /bin/false appuser

# Copy virtual environment from builder stage
COPY --from=tf-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create application directory structure
RUN mkdir -p /app/{uploads,logs,models,static,templates} \
    && mkdir -p /app/object_detection \
    && chown -R appuser:appuser /app

# Copy TensorFlow Object Detection API
# COPY --from=tf-builder /tmp/models/research/object_detection /app/object_detection
COPY --from=tf-builder /object_detection /app/object_detection

# Set working directory
WORKDIR /app

# Copy application code with proper ownership
COPY --chown=appuser:appuser . .

# Create directory for model files if they don't exist
RUN mkdir -p model && chown -R appuser:appuser model

# Set PYTHONPATH for TensorFlow Object Detection API
ENV PYTHONPATH="/app:/app/object_detection:${PYTHONPATH}"

# Security: Set proper file permissions
RUN chmod -R 755 /app \
    && chmod -R 777 /app/uploads \
    && chmod -R 777 /app/logs \
    && find /app -name "*.py" -exec chmod 644 {} \;

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Expose port
EXPOSE 5000

# Switch to non-root user
USER appuser

# Production startup with Gunicorn
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "4", \
     "--worker-class", "gevent", \
     "--worker-connections", "1000", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--timeout", "30", \
     "--keep-alive", "2", \
     "--preload", \
     "--access-logfile", "/app/logs/access.log", \
     "--error-logfile", "/app/logs/error.log", \
     "--log-level", "info", \
     "--capture-output", \
     "app.app:app"]
