# Dockerfile

# pull the official docker image
FROM python:3.11.1-slim

# set work directory
WORKDIR /upstream

# set env variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

# copy project
COPY . /upstream
RUN chmod +x /upstream/scripts/docker-entrypoint.sh /upstream/scripts/run.sh

ENTRYPOINT ["/upstream/scripts/docker-entrypoint.sh"]
CMD ["/upstream/scripts/run.sh", "--host", "0.0.0.0", "--port", "8000"]
