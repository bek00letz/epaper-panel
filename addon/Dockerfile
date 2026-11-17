ARG BUILD_FROM
FROM ${BUILD_FROM}

# Python packages from requirements.txt, the same list the tests install, so pages are
# drawn here with the Pillow the tests check. Ready-built wheels only: if one is ever
# missing, the build stops here instead of trying to compile without a compiler.
COPY requirements.txt /tmp/requirements.txt
RUN apk add --no-cache python3 py3-pip tzdata \
    font-noto font-noto-cjk font-noto-arabic font-noto-hebrew font-dejavu \
 && pip3 install --no-cache-dir --break-system-packages --only-binary=:all: -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

COPY app /opt/epaper
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/epaper
CMD ["/run.sh"]
