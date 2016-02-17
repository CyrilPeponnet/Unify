FROM gliderlabs/alpine

RUN apk add --update \
    python python-dev\
    py-pip \
    bash \
    git \
    build-base libffi-dev \
    openssl-dev \
    && rm -rf /var/cache/apk/* \
    && /usr/bin/pip install --upgrade pip

RUN mkdir -p /app /app/certs/

VOLUME /app/certs

WORKDIR /app

COPY requirements.txt /app/

RUN /usr/bin/pip install -r /app/requirements.txt

COPY whisper.py /app/

ENV CONSUL consul
ENV KV_PATH whisper/updated
ENV ACME_REGISTER_EMAIL needtochange@docker.run

CMD ["sh", "-c", "/usr/bin/python whisper.py -c ${CONSUL} -n ${KV_PATH} ${DEBUG} ${STAGING} ${DOMAIN} /app/certs"]