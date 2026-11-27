FROM python:3.11-slim-bookworm@sha256:ef56ae98435cc40d8a27020b0b32a9941515acd5840f0fba34858bb34dd362d1 AS base
FROM base AS build
WORKDIR /build
COPY pyproject.toml ./
COPY sau_gateway ./sau_gateway
RUN python -m venv /opt/gateway && /opt/gateway/bin/pip install --no-cache-dir .

FROM base
COPY --from=build /opt/gateway /opt/gateway
ENV PATH="/opt/gateway/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["social-media-web-api"]
CMD ["serve"]
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
