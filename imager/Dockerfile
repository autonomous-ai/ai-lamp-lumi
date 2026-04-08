FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    btrfs-progs \
    dosfstools \
    parted \
    qemu-utils \
    qemu-user-static \
    wget \
    wpasupplicant \
    xz-utils \
    rsync \
    util-linux \
    openssl \
    && rm -rf /var/lib/apt/lists/*

RUN which wpa_passphrase

WORKDIR /work
COPY build.sh /work/build.sh
RUN chmod +x /work/build.sh

CMD ["/work/build.sh"]