ARG BUILD_FROM
FROM ${BUILD_FROM}

# Pillow from apk rather than pip: the wheel would need a compiler toolchain
# and the Alpine package is already built against the right libs.
RUN apk add --no-cache python3 py3-pip py3-pillow tzdata \
    font-noto font-noto-cjk font-noto-arabic font-noto-hebrew font-dejavu \
 && pip3 install --no-cache-dir --break-system-packages aiohttp aiomqtt==2.3.0 paho-mqtt==2.1.0

COPY app /opt/epaper
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/epaper
CMD ["/run.sh"]
