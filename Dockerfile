FROM ubuntu:22.04 AS package

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pyproject.toml setup.py _build_backend.py MANIFEST.in README.md LICENSE ./
COPY modules/ modules/
COPY mypyconsole/ mypyconsole/
COPY mypylib/ mypylib/
COPY mytoncore/ mytoncore/
COPY mytonctrl/ mytonctrl/
COPY mytoninstaller/ mytoninstaller/
ARG MYTONCTRL_COMMIT=unknown
ARG MYTONCTRL_VERSION=unknown
RUN python3 -c 'import os; from pathlib import Path; Path("mytonctrl/_version.py").write_text("__commit__ = " + repr(os.environ["MYTONCTRL_COMMIT"]) + "\n__version__ = " + repr(os.environ["MYTONCTRL_VERSION"]) + "\n")' \
    && python3 -m pip wheel --no-deps --wheel-dir /wheels .

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MYTONCTRL_CONTAINER=1 \
    PATH=/opt/mytonctrl/bin:/opt/mytonctrl/venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv supervisor sudo ca-certificates curl wget git \
        libatomic1 libstdc++6 libgcc-s1 libssl3 libsodium23 liblz4-1 \
        libjemalloc2 libmicrohttpd12 \
        fio iproute2 plzip pv aria2 rocksdb-tools sysstat iotop \
        iputils-ping nload jq bc xxd htop procps \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/mytonctrl/venv \
    && touch /etc/mytonctrl-container \
    && useradd --create-home --shell /bin/bash validator
COPY --from=package /wheels /wheels
RUN /opt/mytonctrl/venv/bin/pip install --only-binary=:all: /wheels/*.whl \
    && rm -rf /wheels
COPY docker/entrypoint.py docker/console.py docker/run-service.py docker/mytonctrl_docker_args.py /usr/local/lib/mytonctrl/
COPY docker/export-ton.sh /usr/local/lib/mytonctrl/export-ton.sh
COPY docker/systemctl.py /usr/local/bin/systemctl
COPY docker/supervisord.conf /etc/supervisor/mytonctrl.conf
RUN chmod 755 /usr/local/bin/systemctl \
    && mkdir -p /opt/mytonctrl/bin \
    && ln -s /usr/local/lib/mytonctrl/console.py /opt/mytonctrl/bin/mytonctrl \
    && chmod 755 /usr/local/lib/mytonctrl/console.py
WORKDIR /var/ton-work
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/mytonctrl/venv/bin/python", "/usr/local/lib/mytonctrl/entrypoint.py"]
CMD ["run"]
