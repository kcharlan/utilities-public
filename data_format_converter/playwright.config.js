const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  testMatch: 'browser.spec.js',
  use: {
    baseURL: 'http://127.0.0.1:4175',
  },
  webServer: {
    command: './node_modules/.bin/http-server . -a 127.0.0.1 -p 4175 -c-1',
    url: 'http://127.0.0.1:4175',
    reuseExistingServer: false,
  },
});
