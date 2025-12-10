# Soccer Rig Processing Server
# GPU-enabled container for video stitching and ML

FROM nvidia/cuda:12.2-runtime-ubuntu22.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install Python and FFmpeg with NVENC support
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install PyTorch with CUDA support
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Copy application
COPY . .

# Create directories
RUN mkdir -p /app/input /app/output /app/models

# Download YOLO model on build
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

EXPOSE 5100

CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:5100", "--workers", "2", "--timeout", "300", "src.processing_server:create_app()"]
