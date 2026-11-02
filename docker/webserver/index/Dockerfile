FROM node:24-alpine
WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.js ./
RUN if [ -e /usr/local/lib/node_modules/npm ] || [ -L /usr/local/lib/node_modules/npm ]; then \
      rm -r -- /usr/local/lib/node_modules/npm || exit 1; \
    fi \
  && for entry in /usr/local/bin/npm /usr/local/bin/npx; do \
      if [ -e "$entry" ] || [ -L "$entry" ]; then rm -- "${entry:?}" || exit 1; fi; \
    done
CMD ["node", "server.js"]
