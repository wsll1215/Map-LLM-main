FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10

WORKDIR /app

RUN sed -i \
    -e 's|deb.debian.org/debian|mirrors.aliyun.com/debian|g' \
    -e 's|deb.debian.org/debian-security|mirrors.aliyun.com/debian-security|g' \
    /etc/apt/sources.list.d/debian.sources && \
    apt-get -o Acquire::Retries=10 update && apt-get -o Acquire::Retries=10 install -y --no-install-recommends \
    fontconfig \
    fonts-noto-cjk \
    libgdal32 \
    libgeos-c1v5 \
    && rm -rf /var/lib/apt/lists/*

ENV GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgdal.so.32 \
    GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgeos_c.so.1

COPY requirements.txt /app/requirements.txt
RUN pip install --retries 10 --timeout 120 \
        --index-url http://mirrors.aliyun.com/pypi/simple \
        --trusted-host mirrors.aliyun.com \
        -r requirements.txt

COPY . /app

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
