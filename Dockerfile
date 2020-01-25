FROM debian:buster AS builder

ARG NGSOFTFM_VERSION=90d7685

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    pkg-config \
    libairspy-dev \
    libasound2-dev \
    libboost-all-dev \
    libbladerf-dev \
    libhackrf-dev \
    librtlsdr-dev \
    libusb-1.0-0-dev \
    yasm

WORKDIR /

RUN git clone https://github.com/f4exb/ngsoftfm.git && \
    cd ngsoftfm && \
    git checkout ${NGSOFTFM_VERSION} && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make -j8

FROM python:3.8-buster

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libbladerf1 \
    rtl-sdr

COPY --from=builder /ngsoftfm/build/softfm /usr/bin/

WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8080

CMD ["python", "web_server.py"]
