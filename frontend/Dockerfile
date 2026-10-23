# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
# Optional builder-only CA; never COPY a local trust certificate into an image.
RUN --mount=type=secret,id=corporate_ca,required=false \
    if [ -s /run/secrets/corporate_ca ]; then \
      NODE_EXTRA_CA_CERTS=/run/secrets/corporate_ca npm ci; \
    else npm ci; fi
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN --mount=type=secret,id=corporate_ca,required=false \
    if [ -s /run/secrets/corporate_ca ]; then \
      NODE_EXTRA_CA_CERTS=/run/secrets/corporate_ca npm run build; \
    else npm run build; fi
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
