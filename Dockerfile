FROM python:3.11-slim

# Ensure we have a predictable workdir
WORKDIR /app

# Install adb (Android Debug Bridge) for TCP control of Fire TV devices
RUN apt-get update \
 && apt-get install -y --no-install-recommends adb \
 && rm -rf /var/lib/apt/lists/*

# Install runtime dependencies first (if requirements.txt exists)
# This keeps rebuilds fast when only app code changes.
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application source tree into the image, including
# firestick_minder.py, config.py, and any future helpers.
COPY . /app

# Default command: run the minder daemon
CMD ["python", "-u", "/app/firestick_minder.py"]
