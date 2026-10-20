# The runtime of the bench host tool: Python with pyserial, PyYAML and Textual.
# The image holds only the dependencies. scripts/bench_docker.sh mounts the
# repository, so a code change needs no new image.
FROM python:3.13-slim

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml /tmp/pyproject.toml

# Install the dependencies listed in pyproject.toml, not the package itself.
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('/tmp/pyproject.toml', 'rb'))['project']['dependencies']))" \
      > /tmp/requirements.txt \
  && pip install -r /tmp/requirements.txt \
  && rm /tmp/pyproject.toml /tmp/requirements.txt
