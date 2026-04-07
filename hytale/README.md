# Hytale (Plantilla Docker Compose)

Esta carpeta deja preparada una base para correr un servidor de Hytale cuando exista binario/imagen oficial estable.

## Primer uso

1. Copia variables:

```bash
cp .env.example .env
```

2. Levanta la plantilla:

```bash
docker compose up -d
```

3. Verifica logs:

```bash
docker compose logs -f hytale
```

## Cuando salga el servidor oficial

1. Reemplaza `image` en `docker-compose.yaml`.
2. Cambia `command` por el comando real de arranque.
3. Ajusta puertos `HYTALE_GAME_PORT` según la documentación oficial.
4. Si usas Pterodactyl, crea un egg con la misma imagen/comando.
