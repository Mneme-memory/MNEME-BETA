FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project (no config.json — triggers setup mode)
COPY src/ src/
COPY config.example.json .
COPY system_instructions.example.txt .

EXPOSE 8080

CMD ["python", "src/backend/server.py"]
