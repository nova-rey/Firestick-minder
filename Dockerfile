FROM python:3.11-slim

# Install adb (Android platform-tools)
RUN apt-get update && \
    apt-get install -y --no-install-recommends android-sdk-platform-tools && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir pyyaml paho-mqtt

# Set working directory
WORKDIR /app

# Copy main script into the image
COPY firestick_minder.py /app/firestick_minder.py

# Default config path inside the container will be /config/config.yml
# Users are expected to bind-mount a config file there.
ENV FIRESTICK_MINDER_CONFIG=/config/config.yml
ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/firestick_minder.py"]
