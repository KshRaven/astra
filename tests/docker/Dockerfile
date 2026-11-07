# OPTIONAL: only for testing. The panel itself never needs Docker.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nodejs procps iproute2 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
CMD ["tests/run.sh"]
