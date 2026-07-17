FROM node:24-alpine
WORKDIR /srv
COPY package.json ./
RUN npm install --omit=dev --no-package-lock
COPY server.js ./
RUN rm -rf /usr/local/lib/node_modules/npm \
  && rm -f /usr/local/bin/npm /usr/local/bin/npx
CMD ["node", "server.js"]
