FROM certbot/certbot:latest

# Plugin DNS-01 para DuckDNS (renovación automática sin necesidad de abrir puerto 80)
RUN pip install certbot-dns-duckdns

ENTRYPOINT ["certbot"]
