FROM python:3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dante-server \
        iproute2 \
        iptables \
        miniupnpc \
        wireguard-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

RUN chmod +x /app/scripts/setup_fallback_node.sh
RUN cp /app/scripts/danted.conf.template /etc/danted.conf.template

CMD ["python", "-m", "app.main"]
