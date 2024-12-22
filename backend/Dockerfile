FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY requirements.txt .
COPY config.py .
COPY main.py .
COPY database.py .
COPY video_routes.py .
COPY metadata_routes.py .
COPY heatmap.py .
COPY service-account-key.json .

# Copy models directory
COPY models/ /app/models/

# Create temporary directory
RUN mkdir -p temp

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]