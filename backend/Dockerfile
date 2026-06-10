# Use an official Python slim runtime as the base image
FROM python:3.11-slim

# Set environment variables
# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies
# - libzbar0: Required by pyzbar to perform barcode/QR code decoding
# - libgl1 & libglib2.0-0: Required by OpenCV (cv2) for image preprocessing
# - build-essential & libpq-dev: Required if any package needs compilation (like database adapters)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt /app/

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . /app/

# Expose the port (Railway binds to $PORT dynamically)
EXPOSE 8000

# Collect static files during the build phase
# We provide a dummy SECRET_KEY so Django settings initialization doesn't complain
ENV SECRET_KEY=build_time_dummy_key_12345
RUN python manage.py collectstatic --no-input

# Run database migrations and start the Gunicorn server
CMD python manage.py migrate && gunicorn examflow_project.wsgi:application --bind 0.0.0.0:$PORT
