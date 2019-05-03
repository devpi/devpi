FROM python:3-alpine

ENV DEVPI_PORT 3141

# devpi user
RUN addgroup -S -g 1000 devpi \
    && adduser -S -D -u 1000 -h /data -s /sbin/nologin -G devpi devpi

RUN mkdir -p /data ; chown -R devpi:devpi /data
VOLUME /data

RUN apk add --no-cache tini su-exec bash ca-certificates \
    && update-ca-certificates

ADD ./common /src/common
ADD ./server /src/server
ADD ./client /src/client
ADD ./web /src/web

RUN apk add --no-cache --virtual .build-deps gcc libffi-dev musl-dev \
    && pip install --no-cache-dir --disable-pip-version-check /src/common/. \
    && pip install --no-cache-dir --disable-pip-version-check /src/server/. \
    && pip install --no-cache-dir --disable-pip-version-check /src/client/. \
    && pip install --no-cache-dir --disable-pip-version-check /src/web/. \
    && apk del .build-deps \
    && rm -r /root/.cache \
    && rm -r /src

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE $DEVPI_PORT

ENTRYPOINT ["/sbin/tini", "--", "/docker-entrypoint.sh"]
CMD ["devpi"]
