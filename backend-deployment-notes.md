# RecipeGen Backend — Deployment Guide

This document explains how to build and run the **FastAPI backend** for RecipeGen using Docker.

---

## Prerequisites

* Docker (or Docker Desktop) installed
* Access to this repository (with `Dockerfile.api`, `.dockerignore`, and `requirements.txt` present)
* A processed dataset file: `data/processed/recipes.parquet`

  * If it doesn’t exist, run:

    ```bash
    python scripts/etl_clean.py --in data/raw/13k-recipes.csv --out data/processed/recipes.parquet
    ```

---

## Build the image

From the repo root:

```bash
docker build -t recipegen-api -f Dockerfile.api .
```

---

### Environment variables

* **`DATA_PROCESSED`** → path to the parquet file (default: `/srv/data/processed/recipes.parquet`)
* **`K_MAX`** → maximum number of recipes returned (default: `10`)
* **`CORS_ORIGINS`** → allowed frontend origins (e.g. `http://localhost:3000` for dev, your domain in prod)

---

## Access the API

* Swagger docs: `http://<host>/docs`
* Health check: `http://<host>/health`
* Readiness probe: `http://<host>/ready`

---

## 🔍 Testing

Example request:

```bash
curl -X POST http://<host>/recommend \
  -H "content-type: application/json" \
  -d '{"ingredients":["eggs","tomato","cheese"], "k": 5}'
```
