FROM debian:stretch AS builder

# Dec 13, 2015
ENV NGSOFTFM_VERSION=3e6e6d57eb9c0f7d51458624a1fdfcca8dd5fa55
ENV FFMPEG_VERSION=n4.0.2

RUN apt-get update && apt-get install -y \
    # common dependencies
    build-essential \
    cmake \
    git \
    pkg-config \
    # ngsoftfm
    libairspy-dev \
    libasound2-dev \
    libboost-all-dev \
    libbladerf-dev \
    libhackrf-dev \
    librtlsdr-dev \
    libusb-1.0-0-dev \
    # ffmpeg
    autoconf \
    automake \
    libtool \
    libva-dev \
    texinfo \
    yasm \
    wget \
    zlib1g-dev    

WORKDIR /

RUN git clone https://github.com/f4exb/ngsoftfm.git && \
    cd ngsoftfm && \
    git checkout ${NGSOFTFM_VERSION} && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make -j8

WORKDIR /
RUN git clone --progress https://github.com/FFmpeg/FFmpeg.git
RUN cd /FFmpeg && \
    git checkout ${FFMPEG_VERSION} && \
    ./configure \
        --disable-everything \
        --enable-encoder=aac \
        --enable-decoder=pcm_s16le \
        --enable-muxer=mpegts \
        --enable-muxer=hls \
        --enable-muxer=stream_segment \
        --enable-demuxer=pcm_s16le \
        --enable-protocol=pipe \
        --enable-protocol=file \
        --enable-filter=aresample \
        && \
    make -j8

FROM debian:stretch

RUN apt-get update && apt-get install -y \
    apache2 \
    libasound2 \
    libbladerf1 \
    libc-bin \
    libc6 \
    libstdc++6 \
    libva-drm1 \
    python3 \
    python3-pip \
    rtl-sdr
RUN pip3 install pipenv

COPY --from=builder /ngsoftfm/build/softfm /usr/bin/
COPY --from=builder /FFmpeg/ffmpeg /usr/bin/

# Web server config
RUN cd /etc/apache2 && \
    rm -rf sites-enabled/* && \
    cd mods-enabled && \
        ln -s ../mods-available/cgid.load cgid.load && \
        ln -s ../mods-available/rewrite.load rewrite.load 
COPY fm-hls.conf /etc/apache2/sites-enabled/
# TODO Is having extra stuff in cgi-bin an issue?
COPY *.py /var/www/cgi-bin/
COPY Pipfile* /var/www/cgi-bin/
WORKDIR /var/www/cgi-bin/
RUN export LC_ALL=C.UTF-8 && export LANG=C.UTF-8 && \
    pipenv install --system --deploy

EXPOSE 80

# TODO Run as correct user and from correct location
CMD ["apachectl", "-DFOREGROUND"]
