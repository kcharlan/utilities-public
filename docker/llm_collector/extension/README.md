# Browser Extension

This directory contains the browser extension that captures LLM usage data.

## Functionality

The extension is a simple browser extension that monitors your browsing activity for LLM usage. It works by injecting a content script into web pages and looking for specific patterns in the network requests that indicate LLM activity. When usage is detected, the extension sends the data to the collection server.

The extension is designed to be lightweight and unobtrusive. It only activates on specific websites (e.g., `chat.openai.com`) and only sends the minimum amount of data necessary to track usage.

## Supported Providers

The extension currently supports tracking usage on the following platforms:

*   **OpenAI (ChatGPT):** `chatgpt.com`, `chat.openai.com`
*   **Perplexity:** `perplexity.ai`
*   **Google Gemini:** `gemini.google.com`
*   **Abacus.ai:** `abacus.ai`
*   **T3 Chat:** `t3.chat`

## Installation

1.  Open your web browser's extension management page (e.g., `chrome://extensions`).
2.  Enable "Developer mode".
3.  Run `../setup.sh` from the project root so it generates `extension/config.local.js`.
4.  Click "Load unpacked" and select this `extension` directory.

## Configuration

Do not edit `background.js` for local secrets. Run `../setup.sh` from the project root. It reads `~/.config/llm_collector/secret.env` and generates `config.local.js` with:

*   `API_KEY`: Must match the collector server API key.
*   `COLLECTOR_URL`: The collector server URL, usually `http://127.0.0.1:9000`.

## How it Works

The extension's `background.js` script is the core of the extension. It performs the following functions:

1.  **Client ID Management:** The extension assigns a unique client ID to your browser to distinguish it from other instances. This ID is stored in local storage.

2.  **Request Interception:** The extension uses the `chrome.webRequest` API to intercept network requests. It specifically looks for requests to LLM APIs.

3.  **Usage Detection:** When a request to an LLM API is detected, the extension parses the response to extract the number of tokens used.

4.  **Data Buffering:** The extension buffers the collected usage data locally and sends it to the collector server in batches. This is to minimize the number of requests sent to the server.

5.  **Idempotent Submissions:** The extension uses a sequence number to ensure that usage data is not counted more than once, even if the request to the collector server is retried.

## Customization

The extension is designed to be easily customizable for different LLM providers. To add support for a new provider, you will need to modify the `background.js` file to:

1.  Add a new pattern to the `chrome.webRequest` listener to match the new provider's API endpoint.
2.  Add a new function to parse the provider's response and extract the token usage.
