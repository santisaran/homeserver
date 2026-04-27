FROM python:3.14-alpine

# Instalamos dependencias de sistema necesarias para compilación de algunos paquetes de Python si fuera necesario
RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "worker.py"]