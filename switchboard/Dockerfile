FROM gliderlabs/alpine

RUN apk add haproxy --update-cache --repository http://dl-3.alpinelinux.org/alpine/edge/main/ --allow-untrusted \
    && apk add --update \
    python \
    py-pip \
    bash \
    haproxy \
    ca-certificates \
    unzip \
    && rm -rf /var/cache/apk/*

RUN mkdir -p /haproxy/certs /app

WORKDIR /app

COPY switchboard.py requirements.txt haproxy.conf.jinja2 /app/
COPY example.pem /haproxy/certs/example.pem

RUN /usr/bin/pip install -r /app/requirements.txt

ENV CONSUL consul.service

EXPOSE 80 443 5080

CMD ["sh", "-c", "/usr/bin/python switchboard.py --consul ${CONSUL} haproxy.conf.jinja2 -o /haproxy/haproxy.cfg --run-cmd '/usr/sbin/haproxy -D -p /var/run/haproxy.pid -f /haproxy/haproxy.cfg -sf $(cat /var/run/haproxy.pid) || true'"]
