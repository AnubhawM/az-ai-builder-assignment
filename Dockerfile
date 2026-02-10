FROM node:22-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install OpenClaw globally
RUN npm install -g openclaw@latest

# Link the binary explicitly to ensure it's in the standard path
RUN ln -s $(npm config get prefix)/bin/openclaw /usr/local/bin/openclaw || true

# Install python-pptx
RUN pip3 install --break-system-packages python-pptx

# Set working directory
WORKDIR /root/.openclaw/workspace

# Expose the gateway port
EXPOSE 18789

# Default command
CMD ["openclaw", "gateway", "run"]
