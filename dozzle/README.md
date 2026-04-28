# Dozzle + Metrics

Stack liviano y on-demand para logs y metricas de Docker + host.

## Uso on-demand

Levantar todo el stack cuando quieras revisar:

```bash
cd dozzle
docker compose up -d
```

Abrir en el navegador:

```text
http://IP_DEL_SERVIDOR:20000
http://IP_DEL_SERVIDOR:20001
http://IP_DEL_SERVIDOR:61208
```

Apagar cuando termines:

```bash
cd dozzle
docker compose down
```

Levantar solo servicios puntuales:

```bash
cd dozzle
docker compose up -d dozzle cadvisor
docker compose up -d glances
```

Servicios incluidos:

- Dozzle: logs unificados de contenedores (`:9999`).
- cAdvisor: metricas de contenedores (`:8888`).
- Glances: metricas del host (CPU, RAM, disco, red) y vista Docker (`:61208`).

## Notas

- Lee informacion a traves de `/var/run/docker.sock`.
- Si no queres exponer interfaces fuera del host, puedes bindear a localhost,
  por ejemplo `127.0.0.1:9999:8080`, `127.0.0.1:8888:8080` y `127.0.0.1:61208:61208`.