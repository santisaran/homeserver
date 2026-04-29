FROM python:3.14-alpine AS builder

# Dependencias de compilación solo para construir wheels/paquetes.
RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.14-alpine AS runtime

WORKDIR /app

# Solo artefactos de Python ya instalados desde el stage de build.
COPY --from=builder /install /usr/local
COPY . .

CMD ["python", "worker.py"]