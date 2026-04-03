FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Non-interactive installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
# - python3, pip
# - ffmpeg (basic)
# - chromedriver/chrome (REMOVED - Not used)
# - xvfb (for headless display)
# - libsm6, libxext6 (opencv deps)
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    python3.11-venv \
    python3.11-dev \
    ffmpeg \
    git \
    wget \
    curl \
    gnupg \
    unzip \
    xvfb \
    libsm6 \
    libxext6 \
    libgl1-mesa-glx \
    libvulkan1 \
    mesa-vulkan-drivers \
    vulkan-tools \
    && rm -rf /var/lib/apt/lists/*

# Alias python to python3.11
RUN ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app

# Upgrade pip
RUN python -m pip install --no-cache-dir --upgrade pip

# Copy the SANITIZED requirements file
COPY requirements_docker.txt .

# Install Dependencies
# REMOVED: PyTorch extra index url since we removed torch dependence
RUN pip install --no-cache-dir -r requirements_docker.txt

# Copy the rest of the application
COPY . .

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV PIPELINE_AUTOMATIC=1
ENV MPLBACKEND=Agg
# Xvfb setup envs for SeleniumBase if needed (SB handles some, but good to have)
ENV DISPLAY=:99

# Create the start script directly in /app
RUN echo '#!/bin/bash\nXvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &\npython /app/bootstrapper.py' > /app/start.sh && chmod +x /app/start.sh

# Use the absolute path for the CMD
CMD ["/bin/bash", "/app/start.sh"]