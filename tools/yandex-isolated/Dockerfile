# The official Linux package is amd64-only. Docker Desktop emulates it on Apple Silicon.
FROM --platform=linux/amd64 debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils ca-certificates fonts-liberation jq libasound2 libatk-bridge2.0-0 \
    libatk1.0-0 libatspi2.0-0 libcairo2 libcups2 libcurl4 libdbus-1-3 \
    libexpat1 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 \
    libpango-1.0-0 libudev1 libvulkan1 libx11-6 libxcb1 libxcomposite1 \
    libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 \
    squashfs-tools socat wget xdg-utils xvfb x11vnc fluxbox x11-utils \
    && rm -rf /var/lib/apt/lists/*

# SHA256 is from the signed Yandex APT repository's Packages index, checked 2026-11-10.
ADD --checksum=sha256:27cdc3d0619281c5d0da1ae342c3bb4752c7b0a741c6bac62bc4e58664154cb9 \
    https://repo.yandex.ru/yandex-browser/deb/pool/main/y/yandex-browser-stable/yandex-browser-stable_26.10.0.1882-1_amd64.deb \
    /tmp/yandex-browser.deb

COPY certs/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
RUN echo '936a43fea6e8e525bcc0f81acd9c3d21b4fc4b9b68acea7906d698005afc6504  /usr/local/share/ca-certificates/russian_trusted_root_ca.crt' | sha256sum -c -

# Extract files only: do not execute the vendor's installation scripts.
RUN dpkg-deb -x /tmp/yandex-browser.deb / \
    && rm /tmp/yandex-browser.deb \
    && update-ca-certificates \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin browser \
    && mkdir -p /home/browser/profile \
    && chown -R browser:browser /home/browser

COPY --chmod=755 start.sh /usr/local/bin/start-yandex
USER 10001:10001
WORKDIR /home/browser
ENTRYPOINT ["/usr/local/bin/start-yandex"]
