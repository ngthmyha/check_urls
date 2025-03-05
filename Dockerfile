# Use x86 Ubuntu base image for compatibility
FROM ubuntu:24.04

# Update the system and install necessary tools and dependencies
RUN apt-get update && apt-get install -y \
    software-properties-common \
    wget \
    curl \
    unzip \
    build-essential \
    python3-pip \
    python3-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Add the Deadsnakes repository for newer Python versions
RUN add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update

# Set Python 3 as the default
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Copy project files
WORKDIR /app
COPY . /app

# Khởi tạo Poetry nếu chưa có pyproject.toml
RUN test -f pyproject.toml || poetry init -n --dependency scrapy --dependency pymysql --dependency pandas
RUN poetry install --no-root

# Copy dependency management files
COPY pyproject.toml poetry.lock /app/

WORKDIR /app/crawler

# Install dependencies using Poetry
RUN poetry add scrapy pymysql pandas python-whois beautifulsoup4
RUN poetry update scrapy pymysql pandas python-whois beautifulsoup4