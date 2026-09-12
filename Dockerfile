FROM debian:bookworm AS lame-builder

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        ca-certificates \
        nasm \
    && rm -rf /var/lib/apt/lists/*

COPY lame-3.100.tar.gz /tmp/lame-3.100.tar.gz

RUN cd /tmp && \
    tar -xzf lame-3.100.tar.gz && \
    cd lame-3.100 && \
    ./configure \
        --prefix=/opt/lame \
        --disable-shared \
        --enable-static && \
    make -j"$(nproc)" && \
    make install


FROM debian:bookworm

RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        cdparanoia \
        libcdio-utils \
        flac \
        udev \
        file \
        gosu \
        passwd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=lame-builder /opt/lame/bin/lame /usr/local/bin/lame

WORKDIR /app

COPY requirements.txt .

RUN pip3 install \
    --break-system-packages \
    -r requirements.txt

COPY server.py .
COPY drive_discovery.py .
COPY musicbrainz.py .
COPY cdtext.py .
COPY accuraterip.py .
COPY ripper.py .

COPY templates ./templates
COPY static ./static

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python3", "server.py"]
