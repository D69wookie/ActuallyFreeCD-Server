FROM debian:bookworm

RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        cdparanoia \
        flac \
        udev \
        file \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt

COPY server.py .
COPY drive_discovery.py .

CMD ["python3", "server.py"]