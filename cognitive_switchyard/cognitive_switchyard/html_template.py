from __future__ import annotations

import json
from textwrap import dedent
from typing import Any


DESIGN_TOKENS_BLOCK = """
:root {
  /* === Background === */
  --bg-base: #0f1117;           /* Main page background - very dark blue-gray */
  --bg-surface: #161922;        /* Card/panel backgrounds */
  --bg-surface-raised: #1c1f2e; /* Elevated surfaces (modals, dropdowns) */
  --bg-surface-hover: #232738;  /* Hover state on interactive surfaces */
  --bg-input: #0c0e14;          /* Input field backgrounds */
  --bg-log: #0a0c10;            /* Log viewer background (darkest) */

  /* === Text === */
  --text-primary: #e8eaed;      /* Primary text - slightly warm white */
  --text-secondary: #8b8fa3;    /* Secondary/dimmed text */
  --text-muted: #4a4e63;        /* Very dimmed text (idle labels, timestamps) */
  --text-inverse: #0f1117;      /* Text on bright backgrounds */

  /* === Status Colors === */
  --status-done: #34d399;       /* Green - completed/healthy */
  --status-active: #f59e0b;     /* Amber - in progress */
  --status-ready: #3b82f6;      /* Blue - queued/ready */
  --status-blocked: #ef4444;    /* Red - error/blocked */
  --status-staged: #a78bfa;     /* Purple - staged/planning */
  --status-idle: #374151;       /* Dark gray - idle/inactive */
  --status-review: #f97316;     /* Orange - needs human review */

  /* === Status Glows (for box-shadow) === */
  --glow-done: rgba(52, 211, 153, 0.15);
  --glow-active: rgba(245, 158, 11, 0.15);
  --glow-blocked: rgba(239, 68, 68, 0.25);
  --glow-ready: rgba(59, 130, 246, 0.1);

  /* === Borders === */
  --border-subtle: #1e2231;     /* Default card/panel borders */
  --border-medium: #2a2f42;     /* Stronger separation */
  --border-focus: #3b82f6;      /* Focus ring color */

  /* === Typography === */
  --font-display: 'Space Grotesk', 'DM Sans', sans-serif;    /* Headers, labels */
  --font-mono: 'JetBrains Mono', 'IBM Plex Mono', monospace; /* Data, logs, IDs */
  --font-body: 'DM Sans', 'Space Grotesk', sans-serif;       /* Body text */

  /* === Font Sizes === */
  --text-xs: 0.6875rem;    /* 11px - timestamps, fine print */
  --text-sm: 0.75rem;      /* 12px - secondary labels */
  --text-base: 0.8125rem;  /* 13px - body text (dense UI) */
  --text-md: 0.875rem;     /* 14px - primary labels */
  --text-lg: 1rem;         /* 16px - section headers */
  --text-xl: 1.25rem;      /* 20px - page headers */
  --text-2xl: 1.5rem;      /* 24px - view titles */

  /* === Spacing === */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  /* === Border Radius === */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;

  /* === Transitions === */
  --transition-fast: 150ms ease;
  --transition-base: 250ms ease;
  --transition-slow: 400ms ease;

  /* === Z-index layers === */
  --z-base: 0;
  --z-cards: 10;
  --z-sticky: 20;
  --z-overlay: 30;
  --z-modal: 40;
  --z-tooltip: 50;

  /* === Layout === */
  --topbar-height: 48px;
  --pipeline-strip-height: 44px;
  --worker-card-min-height: 220px;
  --log-tail-lines: 5;          /* Number of visible lines in worker card log tail */
  --sidebar-width: 280px;       /* For views that use sidebar layout */
}
""".strip()


def render_app_html(bootstrap: dict[str, Any]) -> str:
    template = dedent(
        """\
        <!DOCTYPE html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Cognitive Switchyard</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
            <link rel="stylesheet" href="https://unpkg.com/reactflow@11.11.4/dist/style.css">
            <style>
              __DESIGN_TOKENS_BLOCK__

              * {
                box-sizing: border-box;
              }

              html, body {
                margin: 0;
                min-height: 100%;
              }

              body {
                font-family: var(--font-body);
                color: var(--text-primary);
                background-color: var(--bg-base);
                background-image:
                  radial-gradient(ellipse at 20% 50%, rgba(59, 130, 246, 0.03) 0%, transparent 50%),
                  radial-gradient(ellipse at 80% 20%, rgba(139, 92, 246, 0.02) 0%, transparent 40%);
              }

              body::before {
                content: "";
                position: fixed;
                inset: 0;
                opacity: 0.025;
                background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
                pointer-events: none;
                z-index: -1;
              }

              @keyframes pulse-active {
                0%, 100% { box-shadow: 0 0 0 1px var(--status-active), 0 0 8px var(--glow-active); }
                50% { box-shadow: 0 0 0 1px var(--status-active), 0 0 16px var(--glow-active); }
              }

              @keyframes pulse-error {
                0%, 100% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 12px var(--glow-blocked); }
                50% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 24px var(--glow-blocked); }
              }

              @keyframes breathe {
                0%, 100% { opacity: 0.4; }
                50% { opacity: 0.6; }
              }

              @keyframes log-slide-in {
                from { opacity: 0; transform: translateY(4px); }
                to { opacity: 1; transform: translateY(0); }
              }

              @keyframes count-bump {
                0% { transform: scale(1); }
                50% { transform: scale(1.15); }
                100% { transform: scale(1); }
              }

              @keyframes fade-in-up {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
              }

              @keyframes segment-fill {
                from { width: 0%; }
                to { width: 100%; }
              }

              a {
                color: inherit;
                text-decoration: none;
              }

              button, input, select, textarea {
                font: inherit;
              }

              #switchyard-app {
                min-height: 100vh;
              }

              .app-shell {
                min-height: 100vh;
              }

              .topbar {
                position: sticky;
                top: 0;
                z-index: var(--z-sticky);
                min-height: var(--topbar-height);
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: var(--space-4);
                padding: 0 var(--space-4);
                background: rgba(22, 25, 34, 0.92);
                backdrop-filter: blur(12px);
                border-bottom: 1px solid var(--border-subtle);
                animation: fade-in-up 400ms ease forwards;
              }

              .brand {
                font-family: var(--font-display);
                font-size: var(--text-md);
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
              }

              .topbar-center,
              .topbar-nav,
              .row,
              .action-row {
                display: flex;
                align-items: center;
                gap: var(--space-3);
              }

              .topbar-center {
                flex: 1;
                min-width: 0;
              }

              .topbar-nav {
                flex-wrap: wrap;
                justify-content: flex-end;
              }

              .session-text,
              .mono,
              .log-panel,
              .log-tail,
              .intake-list,
              .stage-badge,
              .status-badge,
              .pill,
              .field-hint {
                font-family: var(--font-mono);
              }

              .secondary {
                color: var(--text-secondary);
              }

              .muted {
                color: var(--text-muted);
              }

              .nav-link,
              .icon-button,
              .action-button,
              .secondary-button,
              .danger-button {
                border-radius: var(--radius-sm);
                transition: var(--transition-fast);
              }

              .nav-link,
              .icon-button,
              .secondary-button,
              .danger-button {
                border: 1px solid transparent;
                background: transparent;
                color: var(--text-secondary);
                cursor: pointer;
              }

              .nav-link,
              .icon-button {
                padding: 6px 10px;
              }

              .nav-link:hover,
              .icon-button:hover,
              .secondary-button:hover,
              .danger-button:hover {
                color: var(--text-primary);
                background: var(--bg-surface-hover);
              }

              .nav-link.active {
                color: var(--text-primary);
                border-bottom: 2px solid var(--border-focus);
              }

              .action-button {
                border: none;
                padding: 10px 14px;
                background: var(--status-done);
                color: var(--text-inverse);
                font-family: var(--font-display);
                font-size: var(--text-md);
                font-weight: 700;
                letter-spacing: 0.05em;
                text-transform: uppercase;
                cursor: pointer;
              }

              .action-button:hover {
                filter: brightness(1.08);
              }

              .action-button:disabled {
                opacity: 0.3;
                cursor: not-allowed;
              }

              .secondary-button,
              .danger-button {
                padding: 8px 12px;
              }

              .secondary-button {
                border-color: var(--border-medium);
                color: var(--text-primary);
              }

              .danger-button {
                border-color: var(--status-blocked);
                color: var(--status-blocked);
              }

              .danger-button:hover {
                background: rgba(239, 68, 68, 0.14);
              }

              .pause-button {
                border-left: 3px solid var(--status-active);
              }

              .pausing-button {
                padding: 8px 12px;
                border: 1px solid var(--border-medium);
                border-left: 3px solid var(--status-active);
                border-radius: var(--radius-sm);
                background: transparent;
                color: var(--text-muted);
                cursor: not-allowed;
                pointer-events: none;
                opacity: 0.7;
                animation: pausing-pulse 1.5s ease-in-out infinite;
                font-family: var(--font-display);
                font-size: var(--text-sm);
                font-weight: 600;
                letter-spacing: 0.02em;
                text-transform: uppercase;
              }

              @keyframes pausing-pulse {
                0%, 100% { opacity: 0.5; }
                50% { opacity: 0.85; }
              }

              .resume-entrance {
                animation: resume-pop 200ms ease-out;
              }

              @keyframes resume-pop {
                from { transform: scale(0.92); opacity: 0.6; }
                to { transform: scale(1); opacity: 1; }
              }
              @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
              }

              .page {
                padding: var(--space-6);
                animation: fade-in-up 400ms ease forwards;
              }

              .section-card,
              .worker-card,
              .session-card,
              .setup-card,
              .history-card,
              .task-feed {
                background: var(--bg-surface);
                border: 1px solid var(--border-subtle);
                border-radius: var(--radius-lg);
                box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
              }

              .banner {
                margin: var(--space-4);
                padding: var(--space-3) var(--space-4);
                border-radius: var(--radius-md);
                border: 1px solid var(--border-subtle);
                background: rgba(59, 130, 246, 0.12);
                color: var(--text-primary);
              }

              .banner.error {
                border-color: rgba(239, 68, 68, 0.5);
                background: rgba(239, 68, 68, 0.12);
              }

              .banner.warning {
                border-color: rgba(245, 158, 11, 0.5);
                background: rgba(245, 158, 11, 0.12);
              }

              .pipeline-strip {
                display: flex;
                align-items: center;
                gap: var(--space-2);
                padding: var(--space-3) var(--space-4);
                background: var(--bg-surface);
                border-bottom: 1px solid var(--border-subtle);
                min-height: var(--pipeline-strip-height);
                animation: fade-in-up 400ms ease forwards;
                animation-delay: 80ms;
                overflow-x: auto;
              }

              .event-feed {
                padding: var(--space-2) var(--space-4);
                background: var(--bg-surface);
                border-bottom: 1px solid var(--border-subtle);
                max-height: 220px;
                overflow-y: auto;
              }

              .event-row {
                display: flex;
                gap: var(--space-3);
                align-items: baseline;
                padding: 2px 0;
              }

              .event-row.error {
                color: var(--status-blocked);
              }

              .event-row.warning {
                color: var(--status-review);
              }

              .stage-badge,
              .status-badge,
              .pill {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 2px 10px;
                border-radius: var(--radius-sm);
                font-size: var(--text-sm);
                font-weight: 500;
              }

              .stage-separator {
                color: var(--text-muted);
                font-size: var(--text-xs);
              }

              .worker-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: var(--space-4);
                margin-top: var(--space-6);
              }

              .worker-card {
                min-height: var(--worker-card-min-height);
                padding: var(--space-4);
                cursor: pointer;
                animation: fade-in-up 400ms ease forwards;
              }

              .worker-card:hover,
              .session-card:hover {
                background: var(--bg-surface-hover);
              }

              .worker-card.active {
                animation: pulse-active 3s ease-in-out infinite;
              }

              .worker-card.warning {
                border-color: rgba(245, 158, 11, 0.5);
                animation: pulse-warning 2s ease-in-out infinite;
              }

              @keyframes pulse-warning {
                0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); border-color: rgba(245, 158, 11, 0.5); }
                50% { box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12); border-color: rgba(245, 158, 11, 0.8); }
              }

              @keyframes pulse-idle-amber {
                0%, 100% { opacity: 0.6; }
                50% { opacity: 1.0; }
              }

              @keyframes pulse-idle-red {
                0%, 100% { opacity: 0.7; }
                50% { opacity: 1.0; text-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
              }

              .worker-card.problem {
                animation: pulse-error 1.5s ease-in-out infinite;
              }

              .worker-card.idle {
                opacity: 0.4;
                min-height: auto;
                padding: var(--space-2) var(--space-3);
                animation: breathe 4s ease-in-out infinite;
              }

              .worker-card-header {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: var(--space-3);
              }

              .worker-card-title {
                display: flex;
                flex-direction: column;
                gap: 4px;
                min-width: 0;
              }

              .worker-card-title .secondary {
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              }

              .detail-line {
                margin-top: var(--space-3);
                font-family: var(--font-mono);
                font-size: var(--text-sm);
                color: var(--text-secondary);
              }

              .progress-bar {
                margin-top: var(--space-3);
                display: grid;
                gap: 1px;
                height: 6px;
                border-radius: 3px;
                overflow: hidden;
                background: var(--bg-input);
              }

              .progress-bar span {
                display: block;
                background: var(--bg-input);
              }

              .progress-bar span.done {
                background: var(--status-done);
              }

              .progress-bar span.active {
                background: var(--status-active);
                animation: segment-fill 400ms ease forwards;
              }

              .progress-bar span.future {
                background: rgba(59, 130, 246, 0.08);
              }

              .log-tail,
              .log-panel,
              .intake-list,
              .preflight-panel {
                margin-top: var(--space-4);
                background: var(--bg-log);
                border-radius: var(--radius-sm);
                padding: var(--space-2) var(--space-3);
                font-size: var(--text-xs);
                line-height: 1.5;
                color: var(--text-secondary);
              }

              .log-tail {
                min-height: 104px;
                max-height: 124px;
                overflow: hidden;
              }

              .log-panel {
                margin: 0;
                border-radius: 0;
                min-height: calc(100vh - var(--topbar-height));
                padding-bottom: 96px;
                overflow: auto;
              }

              .log-line {
                animation: log-slide-in 200ms ease;
                white-space: pre-wrap;
                word-break: break-word;
              }

              .log-line.progress {
                margin: 2px 0;
                padding: 4px 8px;
                border-left: 2px solid var(--status-active);
                background: rgba(245, 158, 11, 0.1);
              }

              .log-line.error {
                color: var(--status-blocked);
              }

              .log-line.separator {
                color: var(--status-active);
                text-align: center;
                opacity: 0.7;
                padding: 8px 0;
              }

              .task-feed {
                margin-top: var(--space-6);
                overflow: hidden;
              }

              .task-row {
                display: flex;
                align-items: center;
                gap: var(--space-3);
                min-height: 36px;
                padding: 0 var(--space-4);
                border-bottom: 1px solid var(--border-subtle);
                cursor: pointer;
              }

              .task-row:last-child {
                border-bottom: none;
              }

              .task-row:hover {
                background: var(--bg-surface-hover);
              }

              .task-row.blocked {
                background: rgba(239, 68, 68, 0.08);
                border-left: 3px solid var(--status-blocked);
              }

              .task-row.active {
                border-left: 3px solid var(--status-active);
              }

              .task-row .task-actions {
                display: none;
                gap: 4px;
                margin-left: auto;
              }
              .task-row:hover .task-actions {
                display: flex;
              }

              .task-title {
                flex: 1;
                min-width: 0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              }

              .setup-shell {
                min-height: calc(100vh - var(--topbar-height));
                display: flex;
                align-items: center;
                justify-content: center;
                padding: var(--space-6);
              }

              .setup-card {
                width: min(760px, 100%);
                padding: var(--space-8);
                border-radius: var(--radius-xl);
              }

              .view-title {
                margin: 0 0 var(--space-6);
                font-family: var(--font-display);
                font-size: var(--text-2xl);
              }

              .form-grid,
              .settings-grid {
                display: grid;
                gap: var(--space-4);
              }

              .field-label {
                display: block;
                margin-bottom: var(--space-1);
                font-size: var(--text-xs);
                color: var(--text-muted);
                text-transform: uppercase;
                letter-spacing: 0.05em;
              }

              .field-hint {
                margin-top: 6px;
                font-size: var(--text-xs);
                color: var(--text-muted);
              }

              .text-input,
              .select-input,
              .search-input {
                width: 100%;
                padding: var(--space-2) var(--space-3);
                border: 1px solid var(--border-subtle);
                border-radius: var(--radius-md);
                background: var(--bg-input);
                color: var(--text-primary);
                font-family: var(--font-mono);
                font-size: var(--text-base);
              }

              .text-input:focus,
              .select-input:focus,
              .search-input:focus {
                outline: none;
                border-color: var(--border-focus);
              }

              .split-view {
                display: grid;
                grid-template-columns: 40% 60%;
                min-height: calc(100vh - var(--topbar-height));
              }

              .detail-panel {
                padding: var(--space-6);
                overflow: auto;
              }

              .metadata-grid {
                display: grid;
                gap: var(--space-4);
                margin-top: var(--space-6);
              }

              .metadata-value {
                color: var(--text-primary);
                word-break: break-word;
              }

              .constraint-list,
              .preflight-list,
              .history-list {
                display: grid;
                gap: var(--space-3);
              }

              .preflight-row,
              .intake-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: var(--space-3);
                padding: 8px 0;
                border-bottom: 1px solid rgba(255, 255, 255, 0.04);
              }

              .preflight-row:last-child,
              .intake-row:last-child {
                border-bottom: none;
              }

              .preflight-output {
                margin: 0 0 var(--space-2) 22px;
                padding: var(--space-2) var(--space-3);
                background: rgba(255, 60, 60, 0.08);
                border-left: 3px solid var(--status-blocked);
                border-radius: var(--radius-sm);
                font-family: var(--font-mono);
                font-size: var(--text-xs);
                color: var(--text-secondary);
                white-space: pre-wrap;
                word-break: break-word;
                max-height: 200px;
                overflow-y: auto;
              }

              .status-dot {
                width: 10px;
                height: 10px;
                border-radius: 999px;
                flex: 0 0 auto;
              }

              .advanced-panel {
                margin-top: var(--space-3);
                padding-top: var(--space-3);
                border-top: 1px solid var(--border-subtle);
              }

              .dag-shell {
                min-height: calc(100vh - var(--topbar-height));
                background-image:
                  linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
                  linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
                background-size: 40px 40px;
              }

              .dag-canvas {
                height: calc(100vh - var(--topbar-height) - 88px);
              }

              .history-list {
                margin-top: var(--space-4);
              }

              .session-card {
                padding: var(--space-4);
                cursor: pointer;
              }

              .session-card-header {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: var(--space-4);
              }

              .retention-line {
                margin-top: var(--space-6);
                color: var(--text-muted);
                font-size: var(--text-sm);
              }

              .empty-state {
                padding: var(--space-8);
                text-align: center;
                color: var(--text-muted);
              }

              .stack {
                display: grid;
                gap: var(--space-3);
              }

              .hidden-mobile {
                display: inline-flex;
              }

              @media (max-width: 960px) {
                .split-view {
                  grid-template-columns: 1fr;
                }

                .topbar {
                  padding-top: var(--space-2);
                  padding-bottom: var(--space-2);
                  flex-direction: column;
                  align-items: flex-start;
                }

                .topbar-center,
                .topbar-nav,
                .action-row,
                .row {
                  flex-wrap: wrap;
                }

                .dag-canvas {
                  height: 60vh;
                }

                .hidden-mobile {
                  display: none;
                }
              }

              .completion-card-section {
                margin-top: var(--space-4);
              }

              .completion-card-section h4 {
                font-family: var(--font-mono);
                font-size: var(--text-sm);
                color: var(--text-secondary);
                margin-bottom: var(--space-2);
                text-transform: uppercase;
                letter-spacing: 0.05em;
              }

              .completion-code-block {
                background: var(--bg-log);
                border: 1px solid var(--border-subtle);
                border-radius: 6px;
                padding: var(--space-3);
                font-family: var(--font-mono);
                font-size: var(--text-xs);
                overflow-x: auto;
                white-space: pre;
                position: relative;
                color: var(--text-primary);
              }

              .completion-code-block .copy-btn {
                position: absolute;
                top: var(--space-2);
                right: var(--space-2);
                background: var(--bg-surface);
                border: 1px solid var(--border-subtle);
                border-radius: 4px;
                padding: 4px 8px;
                cursor: pointer;
                color: var(--text-secondary);
                font-size: var(--text-xs);
                font-family: var(--font-mono);
              }

              .completion-code-block .copy-btn:hover {
                background: var(--bg-surface-hover);
                color: var(--text-primary);
              }

              .commit-msg-textarea {
                width: 100%;
                min-height: 120px;
                background: var(--bg-log);
                border: 1px solid var(--border-subtle);
                border-radius: 6px;
                padding: var(--space-3);
                font-family: var(--font-mono);
                font-size: var(--text-xs);
                color: var(--text-primary);
                resize: vertical;
                box-sizing: border-box;
              }
            </style>
          </head>
          <body>
            <div id="switchyard-app"></div>
            <script id="switchyard-bootstrap" type="application/json">__BOOTSTRAP_JSON__</script>
            <script src="https://unpkg.com/react@18.3.1/umd/react.development.js"></script>
            <script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js"></script>
            <script src="https://unpkg.com/@babel/standalone@7.28.4/babel.min.js"></script>
            <script src="https://unpkg.com/lucide@0.542.0/dist/umd/lucide.min.js"></script>
            <script src="https://unpkg.com/reactflow@11.11.4/dist/umd/index.js"></script>
            <script type="text/babel" data-presets="env,react">
              const bootstrap = JSON.parse(document.getElementById("switchyard-bootstrap").textContent);
              const { useEffect, useMemo, useRef, useState } = React;
              const ReactFlowLib = window.ReactFlow || null;
              const OPERABLE_STATUSES = new Set(["created", "idle", "running", "paused", "planning", "resolving", "verifying", "auto_fixing"]);
              const ACTIVE_STATUSES = new Set(["running", "idle", "paused", "planning", "resolving", "verifying", "auto_fixing"]);
              const STATUS_COLORS = {
                done: "var(--status-done)",
                active: "var(--status-active)",
                ready: "var(--status-ready)",
                blocked: "var(--status-blocked)",
                staged: "var(--status-staged)",
                review: "var(--status-review)",
                idle: "var(--status-idle)",
                running: "var(--status-active)",
                idle: "var(--status-staged)",
                paused: "var(--status-review)",
                created: "var(--status-ready)",
                completed: "var(--status-done)",
                aborted: "var(--status-blocked)",
                verifying: "var(--status-active)",
                auto_fixing: "var(--status-review)",
                warning: "rgba(245, 158, 11, 0.9)"
              };
              const TASK_STATUS_ORDER = {
                blocked: 0,
                active: 1,
                ready: 2,
                review: 3,
                staged: 4,
                done: 5
              };

              function statusBadgeStyle(status) {
                const color = STATUS_COLORS[status] || "var(--text-secondary)";
                return {
                  color,
                  background: `${color}22`,
                  border: `1px solid ${color}55`
                };
              }

              function formatElapsed(seconds) {
                if (!seconds) {
                  return "0s";
                }
                const totalSeconds = Math.max(0, Number(seconds) || 0);
                const hours = Math.floor(totalSeconds / 3600);
                const minutes = Math.floor((totalSeconds % 3600) / 60);
                const secs = Math.floor(totalSeconds % 60);
                if (hours > 0) {
                  return `${hours}h ${minutes}m`;
                }
                if (minutes > 0) {
                  return `${minutes}m ${secs}s`;
                }
                return `${secs}s`;
              }

              function isProblemLine(line) {
                return /ERROR|FAIL|Traceback|Exception/i.test(line);
              }

              function isProgressLine(line) {
                return line.includes("##PROGRESS##");
              }

              function splitLogContent(content) {
                if (!content) {
                  return [];
                }
                return content.replace(/\\n$/, "").split("\\n").filter((line) => line.length > 0);
              }

              function dedupeSessionList(sessions, session) {
                const others = (sessions || []).filter((item) => item.id !== session.id);
                return [session, ...others];
              }

              function buildInitialSetupDraft(currentSession, settings, packs) {
                const today = new Date().toISOString().slice(0, 10);
                const config = currentSession?.config || {};
                const env = config.environment || {};
                const packName = currentSession?.pack || settings?.default_pack || packs?.[0]?.name || "";
                const selectedPackDraft = packs?.find(p => p.name === packName);
                return {
                  id: currentSession?.id || `session-${today}`,
                  name: currentSession?.name || `coding-run-${today}`,
                  pack: packName,
                  repo_root: env.COGNITIVE_SWITCHYARD_REPO_ROOT || "",
                  project_dir: env.COGNITIVE_SWITCHYARD_PROJECT_DIR || "",
                  branch: env.COGNITIVE_SWITCHYARD_BRANCH || "",
                  planner_count: config.planner_count ?? settings?.default_planners ?? 1,
                  worker_count: config.worker_count ?? selectedPackDraft?.max_workers ?? settings?.default_workers ?? 1,
                  verification_interval: config.verification_interval ?? 4,
                  auto_fix_enabled: config.auto_fix_enabled ?? true,
                  auto_fix_max_attempts: config.auto_fix_max_attempts ?? 2,
                  poll_interval: config.poll_interval ?? 0.05,
                  task_idle_timeout: config.task_idle_timeout ?? "",
                  task_max_timeout: config.task_max_timeout ?? "",
                  session_max_timeout: config.session_max_timeout ?? ""
                };
              }

              function buildSessionRuntimeDraft(currentSession, settings, packs) {
                return buildInitialSetupDraft(currentSession, settings, packs);
              }

              function sortTasks(tasks) {
                return [...(tasks || [])].sort((left, right) => {
                  const leftRank = TASK_STATUS_ORDER[left.status] ?? 99;
                  const rightRank = TASK_STATUS_ORDER[right.status] ?? 99;
                  if (leftRank !== rightRank) {
                    return leftRank - rightRank;
                  }
                  const leftOrder = left.exec_order ?? 0;
                  const rightOrder = right.exec_order ?? 0;
                  if (leftOrder !== rightOrder) {
                    return leftOrder - rightOrder;
                  }
                  return String(left.task_id).localeCompare(String(right.task_id));
                });
              }

              function requestJson(path, options = {}) {
                return fetch(path, options).then(async (response) => {
                  if (!response.ok) {
                    const text = await response.text();
                    throw new Error(text || `${response.status} ${response.statusText}`);
                  }
                  if (response.status === 204) {
                    return null;
                  }
                  return response.json();
                });
              }

              function icon(name, attrs = {}) {
                return <i data-lucide={name} {...attrs} />;
              }

              function verificationReasonLabel(reason, sessionStatus) {
                const isAutoFix = sessionStatus === "auto_fixing";
                if (reason === "interval") return "Periodic interval check";
                if (reason === "task_failure" || reason === "task_auto_fix") {
                  return isAutoFix ? "Auto-fixing task failure" : "Re-verifying after task fix";
                }
                if (reason === "verification_failure") {
                  return isAutoFix ? "Auto-fixing verification failures" : "Re-verifying after auto-fix";
                }
                if (reason === "recovery_replay") return "Recovery verification";
                if (reason === "full_test_after") return "Task requires full test after completion";
                if (reason === "final") return "Final verification";
                return reason || "Scheduled verification";
              }

              function App() {
                const initialCurrentSession = OPERABLE_STATUSES.has(bootstrap.current_session?.status)
                  ? bootstrap.current_session
                  : null;
                const [view, setView] = useState(
                  initialCurrentSession
                    ? (initialCurrentSession.status === "created" ? "setup" : "monitor")
                    : "setup"
                );
                const [packs, setPacks] = useState(bootstrap.packs || []);
                const [sessions, setSessions] = useState(bootstrap.sessions || []);
                const [settings, setSettings] = useState(bootstrap.settings || {});
                const [settingsDraft, setSettingsDraft] = useState(bootstrap.settings || {});
                const [currentSession, setCurrentSession] = useState(initialCurrentSession);
                const [dashboard, setDashboard] = useState(initialCurrentSession ? (bootstrap.dashboard || null) : null);
                // No client-side idle tracking — the server computes last_activity_ago
                // from the authoritative last_output_at in the worker manager.
                const [tasks, setTasks] = useState([]);
                const [historyTasks, setHistoryTasks] = useState([]);
                const [intake, setIntake] = useState(bootstrap.intake || { locked: false, files: [] });
                const [preflight, setPreflight] = useState(null);
                const [setupDraft, setSetupDraft] = useState(
                  buildInitialSetupDraft(initialCurrentSession, bootstrap.settings || {}, bootstrap.packs || [])
                );
                const [showAdvanced, setShowAdvanced] = useState(false);
                const [repoRootInfo, setRepoRootInfo] = useState(null);
                const [repoBranches, setRepoBranches] = useState([]);
                const [selectedTask, setSelectedTask] = useState(null);
                const [taskLogs, setTaskLogs] = useState({});
                const [phaseDetail, setPhaseDetail] = useState({});
                const [taskSearch, setTaskSearch] = useState("");
                const [dag, setDag] = useState(null);
                const [message, setMessage] = useState(null);
                const [isBusy, setIsBusy] = useState(false);

                // Auto-dismiss non-error banners after 8 seconds
                React.useEffect(() => {
                  if (!message || message.level === "error") return;
                  const timer = setTimeout(() => setMessage(null), 8000);
                  return () => clearTimeout(timer);
                }, [message]);

                // Clear banner on view navigation
                React.useEffect(() => { setMessage(null); }, [view]);
                const [isPausing, setIsPausing] = useState(false);
                const wsRef = useRef(null);
                const subscribedSlotsRef = useRef(new Set());

                useEffect(() => {
                  if (window.lucide && typeof window.lucide.createIcons === "function") {
                    window.lucide.createIcons();
                  }
                });

                useEffect(() => {
                  refreshPacks();
                  refreshSessions();
                }, []);

                useEffect(() => {
                  if (!currentSession || !OPERABLE_STATUSES.has(currentSession.status)) {
                    return;
                  }
                  loadSessionData(currentSession.id, { includePreflight: currentSession.status === "created" });
                }, [currentSession?.id, currentSession?.status]);

                useEffect(() => {
                  if (!currentSession || !OPERABLE_STATUSES.has(currentSession.status)) {
                    closeSocket();
                    return undefined;
                  }
                  let unmounted = false;
                  let reconnectTimer = null;
                  let reconnectDelay = 1000;
                  const MAX_RECONNECT_DELAY = 30000;

                  function connectWebSocket() {
                    if (unmounted) return;
                    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
                    const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
                    socket.onopen = () => {
                      reconnectDelay = 1000;
                      setMessage(null);
                      syncLogSubscriptions(socket, dashboard, selectedTask);
                    };
                    socket.onmessage = (event) => {
                      const payload = JSON.parse(event.data);
                      handleSocketMessage(payload);
                    };
                    socket.onclose = () => {
                      if (unmounted) return;
                      setMessage({
                        level: "warning",
                        text: `Live connection lost. Reconnecting in ${Math.round(reconnectDelay / 1000)}s...`
                      });
                      wsRef.current = null;
                      subscribedSlotsRef.current = new Set();
                      reconnectTimer = setTimeout(() => {
                        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
                        connectWebSocket();
                      }, reconnectDelay);
                    };
                    socket.onerror = () => {};
                    wsRef.current = socket;
                  }

                  connectWebSocket();
                  return () => {
                    unmounted = true;
                    if (reconnectTimer) clearTimeout(reconnectTimer);
                    if (wsRef.current) {
                      wsRef.current.close();
                      wsRef.current = null;
                    }
                    subscribedSlotsRef.current = new Set();
                  };
                }, [currentSession?.id]);

                useEffect(() => {
                  syncLogSubscriptions(wsRef.current, dashboard, selectedTask);
                }, [dashboard, selectedTask?.worker_slot, currentSession?.id]);

                useEffect(() => {
                  if (!currentSession) {
                    setSetupDraft(buildSessionRuntimeDraft(null, settings, packs));
                    return;
                  }
                  if (currentSession.status === "created") {
                    setSetupDraft(buildSessionRuntimeDraft(currentSession, settings, packs));
                  }
                }, [currentSession?.id, currentSession?.status]);

                // Client-side timer: increments elapsed every second for active workers, tasks, and session.
                // The server's elapsed values are authoritative; state_update resets them. This fills the gap between pushes.
                useEffect(() => {
                  const interval = setInterval(() => {
                    setDashboard((current) => {
                      if (!current) return current;
                      const sessionStatus = current.session?.status;
                      const isSessionActive = ["planning", "resolving", "running", "verifying", "auto_fixing"].includes(sessionStatus);
                      return {
                        ...current,
                        session: isSessionActive
                          ? { ...current.session, elapsed: (current.session.elapsed || 0) + 1, run_elapsed: (current.session.run_elapsed || 0) + 1 }
                          : current.session,
                        workers: (current.workers || []).map((w) =>
                          w.status === "active"
                            ? { ...w, elapsed: (w.elapsed || 0) + 1 }
                            : w
                        ),
                      };
                    });
                  }, 1000);
                  return () => clearInterval(interval);
                }, []);

                const activeWorkers = (dashboard?.workers || []).filter((worker) => worker.status === "active").length;
                const workerCount = dashboard?.session?.effective_runtime_config?.worker_count || 0;
                const selectedPack = packs.find((pack) => pack.name === setupDraft.pack) || packs[0] || null;
                const appSessionStatus = dashboard?.session?.status || currentSession?.status || "created";
                const appRuntimeState = dashboard?.runtime_state || {};
                const filteredTaskLog = useMemo(() => {
                  if (!selectedTask) {
                    return [];
                  }
                  const lines = taskLogs[selectedTask.task_id] || [];
                  if (!taskSearch.trim()) {
                    return lines;
                  }
                  return lines.filter((entry) => entry.line.toLowerCase().includes(taskSearch.toLowerCase()));
                }, [selectedTask, taskLogs, taskSearch]);

                function closeSocket() {
                  if (wsRef.current) {
                    wsRef.current.close();
                    wsRef.current = null;
                  }
                  subscribedSlotsRef.current = new Set();
                }

                function syncLogSubscriptions(socket, nextDashboard, nextSelectedTask) {
                  if (!socket || socket.readyState !== WebSocket.OPEN) {
                    return;
                  }
                  const desired = new Set(
                    (nextDashboard?.workers || [])
                      .filter((worker) => worker.task_id && typeof worker.slot === "number")
                      .map((worker) => worker.slot)
                  );
                  if (nextSelectedTask && typeof nextSelectedTask.worker_slot === "number") {
                    desired.add(nextSelectedTask.worker_slot);
                  }
                  subscribedSlotsRef.current.forEach((slot) => {
                    if (!desired.has(slot)) {
                      socket.send(JSON.stringify({ type: "unsubscribe_logs", worker_slot: slot }));
                    }
                  });
                  desired.forEach((slot) => {
                    if (!subscribedSlotsRef.current.has(slot)) {
                      socket.send(JSON.stringify({ type: "subscribe_logs", worker_slot: slot }));
                    }
                  });
                  subscribedSlotsRef.current = desired;
                }

                async function refreshPacks() {
                  const payload = await requestJson("/api/packs");
                  setPacks(payload.packs);
                  return payload.packs;
                }

                async function refreshSessions() {
                  const payload = await requestJson("/api/sessions");
                  setSessions(payload.sessions);
                  return payload.sessions;
                }

                async function loadSessionData(sessionId, options = {}) {
                  const includePreflight = options.includePreflight ?? false;
                  try {
                    const [sessionPayload, dashboardPayload, tasksPayload, intakePayload] = await Promise.all([
                      requestJson(`/api/sessions/${sessionId}`),
                      requestJson(`/api/sessions/${sessionId}/dashboard`),
                      requestJson(`/api/sessions/${sessionId}/tasks`),
                      requestJson(`/api/sessions/${sessionId}/intake`)
                    ]);
                    setMessage(null);
                    setCurrentSession(sessionPayload.session);
                    setSessions((current) => dedupeSessionList(current, sessionPayload.session));
                    setDashboard(dashboardPayload);
                    setTasks(sortTasks(tasksPayload.tasks));
                    setHistoryTasks([]);
                    setIntake(intakePayload);
                    if (includePreflight && sessionPayload.session.status === "created") {
                      await refreshPreflight(sessionId);
                    } else if (sessionPayload.session.status !== "created") {
                      setPreflight(null);
                    }
                  } catch (error) {
                    setMessage({ level: "error", text: `Failed to load session data: ${error.message}` });
                  }
                }

                async function loadHistorySession(sessionId) {
                  try {
                    const [sessionPayload, tasksPayload] = await Promise.all([
                      requestJson(`/api/sessions/${sessionId}`),
                      requestJson(`/api/sessions/${sessionId}/tasks`)
                    ]);
                    setMessage(null);
                    setCurrentSession(sessionPayload.session);
                    setSessions((current) => dedupeSessionList(current, sessionPayload.session));
                    setDashboard(null);
                    setTasks([]);
                    setHistoryTasks(sortTasks(tasksPayload.tasks));
                    setIntake({ locked: false, files: [] });
                    setPreflight(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Failed to load history session: ${error.message}` });
                  }
                }

                async function refreshPreflight(sessionId = currentSession?.id) {
                  if (!sessionId) {
                    return null;
                  }
                  try {
                    const payload = await requestJson(`/api/sessions/${sessionId}/preflight`, { method: "POST" });
                    setMessage(null);
                    setPreflight(payload);
                    return payload;
                  } catch (error) {
                    setMessage({ level: "error", text: `Preflight failed: ${error.message}` });
                    return null;
                  }
                }

                async function openTaskDetail(taskId) {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    const [taskPayload, logPayload] = await Promise.all([
                      requestJson(`/api/sessions/${currentSession.id}/tasks/${taskId}`),
                      requestJson(`/api/sessions/${currentSession.id}/tasks/${taskId}/log?offset=0&limit=400`)
                    ]);
                    setMessage(null);
                    setSelectedTask(taskPayload.task);
                    setTaskLogs((current) => ({
                      ...current,
                      [taskId]: splitLogContent(logPayload.content).map((line) => ({ line, ts: logPayload.mtime_iso || null }))
                    }));
                    setTaskSearch("");
                    setView("task-detail");
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to open task detail: ${error.message}` });
                  }
                }

                async function openDag() {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    const payload = await requestJson(`/api/sessions/${currentSession.id}/dag`);
                    setMessage(null);
                    setDag(payload);
                    setView("dag");
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to load DAG: ${error.message}` });
                  }
                }

                async function fetchBranches(repoPath) {
                  try {
                    const data = await requestJson("/api/repo-branches", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ path: repoPath })
                    });
                    setRepoBranches(data.branches || []);
                    if (data.current) {
                      setSetupDraft((draft) => ({ ...draft, branch: draft.branch || data.current }));
                    }
                  } catch {
                    setRepoBranches([]);
                  }
                }

                async function resolveRepoRoot(rawPath) {
                  if (!rawPath || !rawPath.trim()) {
                    setRepoRootInfo(null);
                    setRepoBranches([]);
                    return;
                  }
                  try {
                    const info = await requestJson("/api/resolve-path", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ path: rawPath })
                    });
                    setRepoRootInfo(info);
                    const resolvedPath = info.resolved || rawPath;
                    if (info.resolved && info.resolved !== rawPath) {
                      setSetupDraft((draft) => ({ ...draft, repo_root: info.resolved }));
                    }
                    if (info.is_git) {
                      fetchBranches(resolvedPath);
                    } else {
                      setRepoBranches([]);
                    }
                  } catch {
                    setRepoRootInfo(null);
                    setRepoBranches([]);
                  }
                }

                async function handleBrowseRepoRoot() {
                  try {
                    const result = await requestJson("/api/browse-directory", { method: "POST" });
                    if (result.path) {
                      setMessage(null);
                      setSetupDraft((draft) => ({ ...draft, repo_root: result.path }));
                      resolveRepoRoot(result.path);
                    }
                  } catch (error) {
                    setMessage({ level: "error", text: `Browse failed: ${error.message}` });
                  }
                }

                async function handleBrowseProjectDir() {
                  try {
                    const result = await requestJson("/api/browse-directory", { method: "POST" });
                    if (result.path) {
                      const repoRoot = setupDraft.repo_root;
                      if (repoRoot && result.path.startsWith(repoRoot + "/")) {
                        setMessage(null);
                        setSetupDraft((draft) => ({ ...draft, project_dir: result.path.slice(repoRoot.length + 1) }));
                      } else if (repoRoot && result.path === repoRoot) {
                        setMessage({ level: "warning", text: "Selected directory is the repo root itself — leave Project Directory blank for single-project repos." });
                      } else {
                        setMessage({ level: "error", text: "Selected directory is not inside the Repository Root." });
                      }
                    }
                  } catch (error) {
                    setMessage({ level: "error", text: `Browse failed: ${error.message}` });
                  }
                }

                async function handleCreateBranch(repoPath, branchName, fromBranch) {
                  await requestJson("/api/repo-create-branch", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ repo_path: repoPath, branch_name: branchName, from_branch: fromBranch })
                  });
                  await fetchBranches(repoPath);
                  setSetupDraft((draft) => ({ ...draft, branch: branchName }));
                }

                async function handleDiscardDraft() {
                  if (!currentSession) return;
                  setIsBusy(true);
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}`, { method: "DELETE" });
                    setCurrentSession(null);
                    setSessions((current) => current.filter((s) => s.id !== currentSession.id));
                    setSetupDraft(buildInitialSetupDraft(null, settings, packs));
                    setIntake({ locked: false, files: [] });
                    setPreflight(null);
                    setRepoRootInfo(null);
                    setMessage({ level: "info", text: "Session reset." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to discard draft: ${error.message}` });
                  } finally {
                    setIsBusy(false);
                  }
                }

                async function handleCreateDraftSession() {
                  setIsBusy(true);
                  try {
                    // Build config with only valid overrides — omit NaN/0/null so
                    // the backend uses pack defaults for unset fields.
                    const config = {};
                    const env = {};
                    if (setupDraft.repo_root) env.COGNITIVE_SWITCHYARD_REPO_ROOT = setupDraft.repo_root;
                    if (setupDraft.project_dir) env.COGNITIVE_SWITCHYARD_PROJECT_DIR = setupDraft.project_dir;
                    if (setupDraft.branch && setupDraft.branch !== "__new__") env.COGNITIVE_SWITCHYARD_BRANCH = setupDraft.branch;
                    if (Object.keys(env).length > 0) config.environment = env;
                    const intField = (key, val) => { const n = parseInt(val, 10); if (n > 0) config[key] = n; };
                    const floatField = (key, val) => { const n = parseFloat(val); if (n > 0) config[key] = n; };
                    intField("planner_count", setupDraft.planner_count);
                    intField("worker_count", setupDraft.worker_count);
                    intField("verification_interval", setupDraft.verification_interval);
                    intField("auto_fix_max_attempts", setupDraft.auto_fix_max_attempts);
                    floatField("poll_interval", setupDraft.poll_interval);
                    if (typeof setupDraft.auto_fix_enabled === "boolean") {
                      config.auto_fix_enabled = setupDraft.auto_fix_enabled;
                    }
                    const payload = await requestJson("/api/sessions", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        id: setupDraft.id,
                        name: setupDraft.name,
                        pack: setupDraft.pack,
                        config: Object.keys(config).length > 0 ? config : undefined
                      })
                    });
                    setCurrentSession(payload.session);
                    setSessions((current) => dedupeSessionList(current, payload.session));
                    setMessage({ level: "info", text: "Session created. Add intake files, run preflight, then start." });
                    setView("setup");
                    await loadSessionData(payload.session.id, { includePreflight: true });
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to create session: ${error.message}`, sessionId: setupDraft.id });
                  } finally {
                    setIsBusy(false);
                  }
                }

                async function handleStartSession() {
                  if (!currentSession) {
                    await handleCreateDraftSession();
                    return;
                  }
                  setIsBusy(true);
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/start`, { method: "POST" });
                    setMessage({ level: "info", text: "Session started." });
                    // Load dashboard data first so monitor has content when we switch
                    await loadSessionData(currentSession.id, { includePreflight: false });
                    setView("monitor");
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to start session: ${error.message}`, sessionId: currentSession?.id });
                  } finally {
                    setIsBusy(false);
                  }
                }

                async function handleSessionControl(action) {
                  if (!currentSession) {
                    return;
                  }
                  const needsConfirm = action === "abort" || action === "end";
                  const confirmMsg = action === "abort" ? `Abort session ${currentSession.name}?` : `End session ${currentSession.name}? This will clean up the worktree and write the summary.`;
                  const confirmed = !needsConfirm || window.confirm(confirmMsg);
                  if (!confirmed) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/${action}`, { method: "POST" });
                    setMessage(null);
                    if (action === "pause") {
                      setIsPausing(true);
                    }
                    await loadSessionData(currentSession.id, { includePreflight: currentSession.status === "created" });
                    await refreshSessions();
                    // If the session is already paused/terminal after refetch, clear the transitional state
                    if (action === "pause") {
                      setCurrentSession((s) => {
                        if (s && (s.status === "paused" || s.status === "completed" || s.status === "aborted")) {
                          setIsPausing(false);
                        }
                        return s;
                      });
                    }
                  } catch (error) {
                    setIsPausing(false);
                    setMessage({ level: "error", text: `Unable to ${action} session: ${error.message}`, sessionId: currentSession?.id });
                  }
                }

                async function handleSettingsSave() {
                  try {
                    const payload = await requestJson("/api/settings", {
                      method: "PUT",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify(settingsDraft)
                    });
                    setSettings(payload.settings);
                    setSettingsDraft(payload.settings);
                    setMessage({ level: "info", text: "Settings saved." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to save settings: ${error.message}` });
                  }
                }

                async function handleOpenIntake() {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/open-intake`, { method: 'POST' });
                    setMessage(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to open intake folder: ${error.message}` });
                  }
                }

                async function handleOpenIntakeTerminal() {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/open-intake-terminal`, { method: 'POST' });
                    setMessage(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to open intake terminal: ${error.message}` });
                  }
                }

                async function handleRevealFile(path) {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    await requestJson(
                      `/api/sessions/${currentSession.id}/reveal-file?path=${encodeURIComponent(path)}`,
                      { method: 'POST' }
                    );
                    setMessage(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to reveal file: ${error.message}` });
                  }
                }

                async function handleMoveTask(taskId, targetStatus) {
                  if (!currentSession) return;
                  try {
                    await requestJson(
                      `/api/sessions/${currentSession.id}/tasks/${taskId}/move`,
                      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_status: targetStatus }) }
                    );
                    setMessage({ level: "info", text: `Task ${taskId} moved to ${targetStatus}` });
                  } catch (err) {
                    setMessage({ level: "error", text: `Move failed: ${err.message}` });
                  }
                }

                const [isRescanning, setIsRescanning] = useState(false);

                async function handleRescan() {
                  if (!currentSession) return;
                  setIsRescanning(true);
                  try {
                    const res = await fetch(`/api/sessions/${currentSession.id}/rescan`, { method: "POST" });
                    if (!res.ok) throw new Error(await res.text());
                    const data = await res.json();
                    const count = data.reconciled.length;
                    const orphaned = data.orphaned.length;
                    let text = "Rescan: no changes";
                    if (count > 0 || orphaned > 0) {
                      const parts = [];
                      if (count > 0) parts.push(`${count} task${count !== 1 ? "s" : ""} reconciled`);
                      if (orphaned > 0) parts.push(`${orphaned} orphaned`);
                      text = "Rescan: " + parts.join(", ");
                    }
                    setMessage({ level: "info", text });
                  } catch (error) {
                    setMessage({ level: "error", text: `Rescan failed: ${error.message}` });
                  } finally {
                    setIsRescanning(false);
                  }
                }

                const [isReprocessing, setIsReprocessing] = useState(false);

                async function handleReprocess() {
                  if (!currentSession) return;
                  setIsReprocessing(true);
                  try {
                    await fetch(`/api/sessions/${currentSession.id}/rescan`, { method: "POST" });
                    const res = await fetch(`/api/sessions/${currentSession.id}/reprocess`, { method: "POST" });
                    if (!res.ok) {
                      const body = await res.json().catch(() => ({ detail: res.statusText }));
                      throw new Error(body.detail || res.statusText);
                    }
                    setMessage({ level: "info", text: "Reprocessing started — pipeline will re-run from current state." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Reprocess failed: ${error.message}` });
                  } finally {
                    setIsReprocessing(false);
                  }
                }

                async function handleOpenHistorySession(session) {
                  setSelectedTask(null);
                  setDag(null);
                  setView("history");
                  await loadHistorySession(session.id);
                }

                async function handlePurgeSession(sessionId) {
                  const target = sessions.find((session) => session.id === sessionId);
                  if (!target) {
                    return;
                  }
                  const confirmed = window.confirm(`Delete session ${target.name} and all its artifacts?`);
                  if (!confirmed) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${sessionId}`, { method: "DELETE" });
                    setMessage(null);
                    const nextSessions = (await refreshSessions()).filter((session) => session.id !== sessionId);
                    if (currentSession?.id === sessionId) {
                      setCurrentSession(null);
                      setDashboard(null);
                      setTasks([]);
                      setHistoryTasks([]);
                      setIntake({ locked: false, files: [] });
                      setPreflight(null);
                      setView("setup");
                    }
                    setSessions(nextSessions);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to purge session: ${error.message}` });
                  }
                }

                async function handlePurgeAll() {
                  const completedCount = sessions.filter((session) =>
                    session.status === "completed" || session.status === "aborted"
                  ).length;
                  if (completedCount === 0) {
                    return;
                  }
                  const confirmed = window.confirm(`Delete ${completedCount} completed sessions?`);
                  if (!confirmed) {
                    return;
                  }
                  try {
                    await requestJson("/api/sessions", { method: "DELETE" });
                    setMessage(null);
                    await refreshSessions();
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to purge sessions: ${error.message}` });
                  }
                }

                async function handleForceReset(sessionId) {
                  const confirmed = window.confirm(
                    "Force reset will abort the session (if running), tear down its worktree, " +
                    "and delete all data. This cannot be undone. Continue?"
                  );
                  if (!confirmed) return;
                  setIsBusy(true);
                  try {
                    await requestJson(`/api/sessions/${sessionId}/force-reset`, { method: "POST" });
                    setCurrentSession(null);
                    setDashboard(null);
                    setTasks([]);
                    setHistoryTasks([]);
                    setIntake({ locked: false, files: [] });
                    setPreflight(null);
                    setRepoRootInfo(null);
                    setSessions((current) => current.filter((s) => s.id !== sessionId));
                    setSetupDraft(buildInitialSetupDraft(null, settings, packs));
                    setView("setup");
                    setMessage({ level: "info", text: "Session force-reset complete." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Force reset failed: ${error.message}` });
                  } finally {
                    setIsBusy(false);
                  }
                }

                function handleSocketMessage(messagePayload) {
                  if (messagePayload.type === "state_update") {
                    const incomingStatus = messagePayload.data?.session?.status;
                    if (incomingStatus === "paused" || incomingStatus === "completed" || incomingStatus === "aborted") {
                      setIsPausing(false);
                    }
                    setDashboard(messagePayload.data);
                    setCurrentSession((current) => {
                      if (!current) {
                        return current;
                      }
                      const nextSession = {
                        ...current,
                        status: incomingStatus,
                        effective_runtime_config: messagePayload.data.session.effective_runtime_config,
                        config: messagePayload.data.session.config
                      };
                      setSessions((sessionsState) => dedupeSessionList(sessionsState, nextSession));
                      return nextSession;
                    });
                    // Auto-navigate to monitor when session transitions to active state
                    if (ACTIVE_STATUSES.has(incomingStatus)) {
                      setView((currentView) => currentView === "setup" ? "monitor" : currentView);
                    }
                    // Clear stale streaming logs when verification/auto-fix phases start fresh
                    if (incomingStatus === "verifying") {
                      setTaskLogs(current => {
                        const next = { ...current };
                        delete next["__phase_verification__"];
                        delete next["__phase_auto_fix__"];
                        return next;
                      });
                    }
                    if (incomingStatus === "auto_fixing") {
                      setTaskLogs(current => {
                        const next = { ...current };
                        delete next["__phase_auto_fix__"];
                        delete next["__phase_verification__"];
                        return next;
                      });
                    }
                    return;
                  }
                  if (messagePayload.type === "log_line") {
                    const workerSlot = messagePayload.data.worker_slot;
                    const taskId = messagePayload.data.task_id;
                    // Auto-clear idle warning if this worker resumed output
                    setMessage((current) => {
                      if (current && current.level === "warning" && current.workerSlot === workerSlot) {
                        return null;
                      }
                      return current;
                    });
                    setDashboard((current) => {
                      if (!current) {
                        return current;
                      }
                      const workers = (current.workers || []).map((worker) => (
                        worker.slot === workerSlot
                          ? { ...worker, last_log_line: messagePayload.data.line }
                          : worker
                      ));
                      return { ...current, workers };
                    });
                    setTaskLogs((current) => ({
                      ...current,
                      [taskId]: [...(current[taskId] || []), { line: messagePayload.data.line, ts: messagePayload.data.timestamp || null }].slice(-400)
                    }));
                    return;
                  }
                  if (messagePayload.type === "progress_detail") {
                    if (messagePayload.data.worker_slot === -1) {
                      setPhaseDetail((current) => ({
                        ...current,
                        [messagePayload.data.task_id]: messagePayload.data.detail,
                      }));
                    } else {
                      const detailSlot = messagePayload.data.worker_slot;
                      const detailContent = messagePayload.data.detail || "";
                      setDashboard((current) => {
                        if (!current) {
                          return current;
                        }
                        const workers = (current.workers || []).map((worker) => (
                          worker.slot === detailSlot
                            ? { ...worker, detail: detailContent }
                            : worker
                        ));
                        return { ...current, workers };
                      });
                    }
                    return;
                  }
                  if (messagePayload.type === "task_status_change") {
                    setTasks((current) => sortTasks(
                      current.map((task) => (
                        task.task_id === messagePayload.data.task_id
                          ? {
                              ...task,
                              status: messagePayload.data.new_status,
                              worker_slot: messagePayload.data.worker_slot ?? task.worker_slot,
                              elapsed: messagePayload.data.elapsed ?? task.elapsed,
                              started_at: messagePayload.data.started_at ?? task.started_at,
                              completed_at: messagePayload.data.completed_at ?? task.completed_at,
                            }
                          : task
                      ))
                    ));
                    return;
                  }
                  if (messagePayload.type === "alert") {
                    setMessage({
                      level: messagePayload.data.severity === "error" ? "error" : "warning",
                      text: messagePayload.data.message,
                      workerSlot: messagePayload.data.worker_slot ?? null
                    });
                  }
                }

                return (
                  <div className="app-shell">
                    <TopBar
                      currentSession={currentSession}
                      currentView={view}
                      workerCount={workerCount}
                      activeWorkers={activeWorkers}
                      elapsed={dashboard?.session?.elapsed || 0}
                      runElapsed={dashboard?.session?.run_elapsed || 0}
                      runNumber={dashboard?.session?.run_number || 0}
                      onNavigate={setView}
                      isPausing={isPausing}
                      onPause={() => handleSessionControl("pause")}
                      onResume={() => handleSessionControl("resume")}
                      onAbort={() => handleSessionControl("abort")}
                      onEnd={() => handleSessionControl("end")}
                      onNewRun={() => handleSessionControl("resume")}
                    />
                    {message ? (
                      <div className={`banner ${message.level === "error" ? "error" : message.level === "warning" ? "warning" : ""}`}
                           style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ flex: 1 }}>
                          <span>{message.text}</span>
                          {message.level === "error" && message.sessionId ? (
                            <button
                              type="button"
                              className="secondary-button"
                              style={{ marginLeft: '12px', fontSize: 'var(--text-xs)', padding: '2px 8px' }}
                              onClick={() => handleForceReset(message.sessionId)}
                            >
                              Force Reset
                            </button>
                          ) : null}
                        </div>
                        <button
                          type="button"
                          onClick={() => setMessage(null)}
                          style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer',
                                   fontSize: '18px', padding: '0 0 0 12px', lineHeight: 1, opacity: 0.7 }}
                          title="Dismiss"
                          onMouseOver={(e) => e.currentTarget.style.opacity = '1'}
                          onMouseOut={(e) => e.currentTarget.style.opacity = '0.7'}>
                          ×
                        </button>
                      </div>
                    ) : null}
                    {view === "monitor" ? (
                      <MonitorView
                        dashboard={dashboard}
                        currentSession={currentSession}
                        tasks={tasks}
                        taskLogs={taskLogs}
                        phaseDetail={phaseDetail}
                        onOpenTask={openTaskDetail}
                        onOpenDag={openDag}
                        onRevealFile={handleRevealFile}
                        onMoveTask={handleMoveTask}
                        onRescan={handleRescan}
                        isRescanning={isRescanning}
                        onReprocess={handleReprocess}
                        isReprocessing={isReprocessing}
                      />
                    ) : null}
                    {view === "setup" ? (
                      <SetupView
                        currentSession={currentSession}
                        setupDraft={setupDraft}
                        setSetupDraft={setSetupDraft}
                        selectedPack={selectedPack}
                        packs={packs}
                        intake={intake}
                        preflight={preflight}
                        settings={settings}
                        showAdvanced={showAdvanced}
                        setShowAdvanced={setShowAdvanced}
                        isBusy={isBusy}
                        repoRootInfo={repoRootInfo}
                        repoBranches={repoBranches}
                        onCreateDraft={handleCreateDraftSession}
                        onStartSession={handleStartSession}
                        onRefreshIntake={() => currentSession && loadSessionData(currentSession.id, { includePreflight: true })}
                        onRunPreflight={async () => {
                  setIsBusy(true);
                  try { await refreshPreflight(); } finally { setIsBusy(false); }
                }}
                        onOpenIntake={handleOpenIntake}
                        onOpenIntakeTerminal={handleOpenIntakeTerminal}
                        onRevealFile={handleRevealFile}
                        onBrowseRepoRoot={handleBrowseRepoRoot}
                        onBrowseProjectDir={handleBrowseProjectDir}
                        onResolveRepoRoot={resolveRepoRoot}
                        onCreateBranch={handleCreateBranch}
                        onDiscardDraft={handleDiscardDraft}
                        onNewRun={() => handleSessionControl("resume")}
                        onNavigate={setView}
                      />
                    ) : null}
                    {view === "history" ? (
                      <HistoryView
                        sessions={sessions}
                        settings={settings}
                        selectedSession={currentSession && !OPERABLE_STATUSES.has(currentSession.status) ? currentSession : null}
                        selectedTasks={historyTasks}
                        onOpenSession={handleOpenHistorySession}
                        onOpenSettings={() => setView("settings")}
                        onPurgeSession={handlePurgeSession}
                        onPurgeAll={handlePurgeAll}
                      />
                    ) : null}
                    {view === "settings" ? (
                      <SettingsView
                        settingsDraft={settingsDraft}
                        setSettingsDraft={setSettingsDraft}
                        packs={packs}
                        onSave={handleSettingsSave}
                      />
                    ) : null}
                    {view === "task-detail" ? (
                      <TaskDetailView
                        task={selectedTask}
                        currentSession={currentSession}
                        logLines={filteredTaskLog}
                        taskLogs={taskLogs}
                        sessionStatus={appSessionStatus}
                        runtimeState={appRuntimeState}
                        searchValue={taskSearch}
                        onSearchChange={setTaskSearch}
                        onBack={() => setView("monitor")}
                        onMoveTask={handleMoveTask}
                        onRevealFile={handleRevealFile}
                      />
                    ) : null}
                    {view === "dag" ? (
                      <DagView
                        dag={dag}
                        onBack={() => setView("monitor")}
                        onOpenTask={openTaskDetail}
                      />
                    ) : null}
                  </div>
                );
              }

              function TopBar({
                currentSession,
                currentView,
                workerCount,
                activeWorkers,
                elapsed,
                runElapsed,
                runNumber,
                onNavigate,
                isPausing,
                onPause,
                onResume,
                onAbort,
                onEnd,
                onNewRun
              }) {
                const sessionStatus = currentSession?.status || "none";
                const isActive = ["planning", "resolving", "running", "verifying", "auto_fixing"].includes(sessionStatus);
                // Client-side auto-increment timers
                const [sessionTick, setSessionTick] = useState(elapsed);
                const [runTick, setRunTick] = useState(runElapsed);
                useEffect(() => { setSessionTick(elapsed); }, [elapsed]);
                useEffect(() => { setRunTick(runElapsed); }, [runElapsed]);
                useEffect(() => {
                  if (!isActive) return;
                  const timer = setInterval(() => {
                    setSessionTick(prev => prev + 1);
                    setRunTick(prev => prev + 1);
                  }, 1000);
                  return () => clearInterval(timer);
                }, [isActive]);
                const displayedRunTime = isActive ? runTick : runElapsed;
                return (
                  <header className="topbar">
                    <div className="brand">Cognitive Switchyard</div>
                    <div className="topbar-center">
                      <span className="session-text secondary">
                        {currentSession ? (
                          <React.Fragment>
                            {currentSession.name}
                            {" | "}
                            <span className="status-badge" style={statusBadgeStyle(sessionStatus)}>{sessionStatus}</span>
                            {" | "}
                            {runNumber > 0 ? (
                              <span title="Current run time">
                                {"Run #"}{runNumber}{": "}{formatElapsed(displayedRunTime)}
                              </span>
                            ) : null}
                            {runNumber > 0 ? (
                              <span style={{ marginLeft: '0.75em', color: 'var(--text-primary)' }} title="Total active time across all runs">
                                {"("}{formatElapsed(sessionTick)}{" cumulative)"}
                              </span>
                            ) : null}
                          </React.Fragment>
                        ) : "No active session"}
                      </span>
                      {currentSession ? (
                        <span className="session-text muted hidden-mobile">{`${activeWorkers}/${workerCount} active`}</span>
                      ) : null}
                    </div>
                    <nav className="topbar-nav">
                      <button type="button" className={`nav-link${currentView === "setup" ? " active" : ""}`} onClick={() => onNavigate("setup")}>Setup</button>
                      <button type="button" className={`nav-link${currentView === "monitor" ? " active" : ""}`} onClick={() => onNavigate("monitor")}>Monitor</button>
                      <button type="button" className={`nav-link${currentView === "history" ? " active" : ""}`} onClick={() => onNavigate("history")}>History</button>
                      {isPausing ? (
                        <button type="button" className="pausing-button" disabled>⏸ Pausing…</button>
                      ) : ["planning", "resolving", "running", "verifying", "auto_fixing"].includes(currentSession?.status) ? (
                        <button type="button" className="secondary-button pause-button" onClick={onPause}>❚❚ Pause</button>
                      ) : currentSession?.status === "paused" ? (
                        <button type="button" className="action-button resume-entrance" onClick={onResume}>▶ Resume</button>
                      ) : null}
                      {currentSession?.status === "idle" ? (
                        <React.Fragment>
                          <button type="button" className="action-button" onClick={onNewRun}>New Run</button>
                          <button type="button" className="secondary-button" onClick={onEnd}>End Session</button>
                        </React.Fragment>
                      ) : null}
                      {currentSession && !["completed", "aborted", "idle"].includes(currentSession.status) ? (
                        <button type="button" className="danger-button" onClick={onAbort}>Abort</button>
                      ) : null}
                      <button type="button" className="icon-button" onClick={() => onNavigate("settings")} aria-label="Settings">
                        {icon("settings", { width: 18, height: 18 })}
                      </button>
                    </nav>
                  </header>
                );
              }

              function PipelineStrip({ pipeline, pipelineDirs, sessionStatus, currentSession, onRevealFile, onOpenDag, onRescan, isRescanning, onReprocess, isReprocessing, canReprocess }) {
                const stages = [
                  ["intake", "Intake"],
                  ["planning", "Planning"],
                  ["staged", "Staged"],
                  ["review", "Review"],
                  ["ready", "Ready"],
                  ["active", "Active"],
                  ["verifying", "Verify"],
                  ["done", "Done"],
                  ["blocked", "Blocked"]
                ];
                const STAGE_ORDER = { intake: 0, planning: 1, staged: 2, review: 3, ready: 4, active: 5, verifying: 6, done: 7, blocked: 8 };
                const STATUS_TO_ACTIVE_STAGE = {
                  planning: "planning",
                  resolving: "staged",
                  running: "active",
                  verifying: "verifying",
                  auto_fixing: "verifying",
                  completed: "done",
                  aborted: "blocked"
                };
                const activeStageKey = STATUS_TO_ACTIVE_STAGE[sessionStatus] || null;
                const activeStageOrder = activeStageKey ? STAGE_ORDER[activeStageKey] : -1;

                return (
                  <div className="pipeline-strip">
                    {stages.map(([key, label], index) => {
                      const count = pipeline[key] || 0;
                      const stageOrder = STAGE_ORDER[key];
                      const isActive = key === activeStageKey;
                      const isPast = activeStageOrder > 0 && stageOrder < activeStageOrder && count === 0;
                      const hasItems = count > 0;
                      const isReviewWithItems = key === "review" && hasItems;
                      const isBlocked = key === "blocked" && hasItems;
                      let badgeColor = "var(--text-muted)";
                      let badgeBg = "transparent";
                      let badgeAnimation = "none";
                      let badgeBorder = "1px solid var(--border-subtle)";
                      let badgeOpacity = 1;
                      if (isBlocked) {
                        badgeColor = "var(--status-blocked)";
                        badgeBg = "rgba(239, 68, 68, 0.15)";
                        badgeAnimation = "pulse-error 2s ease-in-out infinite";
                        badgeBorder = "1px solid rgba(239, 68, 68, 0.4)";
                      } else if (isActive) {
                        badgeColor = "var(--status-active)";
                        badgeBg = "rgba(245, 158, 11, 0.15)";
                        badgeAnimation = "pulse-active 3s ease-in-out infinite";
                        badgeBorder = "1px solid rgba(245, 158, 11, 0.4)";
                      } else if (isReviewWithItems) {
                        badgeColor = "var(--status-review)";
                        badgeBg = "rgba(249, 115, 22, 0.15)";
                        badgeBorder = "1px solid rgba(249, 115, 22, 0.4)";
                      } else if (hasItems) {
                        badgeColor = STATUS_COLORS[key] || "var(--text-secondary)";
                        badgeBg = `${STATUS_COLORS[key] || "var(--text-secondary)"}22`;
                      } else if (isPast) {
                        badgeOpacity = 0.35;
                      }
                      return (
                        <React.Fragment key={key}>
                          <button
                            type="button"
                            className="stage-badge"
                            title={pipelineDirs[key] ? `Open ${label} directory` : label}
                            onClick={() => pipelineDirs[key] && currentSession && onRevealFile(pipelineDirs[key])}
                            style={{
                              color: badgeColor,
                              background: badgeBg,
                              animation: badgeAnimation,
                              cursor: "pointer",
                              border: badgeBorder,
                              opacity: badgeOpacity,
                              transition: "all 300ms ease",
                            }}
                          >
                            {`${label}(${count})`}
                          </button>
                          {index < stages.length - 1 ? (
                            <span className="stage-separator" style={{ opacity: isPast ? 0.3 : 1 }}>{">"}</span>
                          ) : null}
                        </React.Fragment>
                      );
                    })}
                    <button type="button" className="icon-button" onClick={onOpenDag} aria-label="Open DAG">
                      {icon("git-branch", { width: 18, height: 18 })}
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      onClick={onRescan}
                      disabled={isRescanning || !currentSession}
                      aria-label="Rescan filesystem"
                      title="Rescan: reconcile filesystem state into database"
                      style={{ position: "relative" }}
                    >
                      {isRescanning
                        ? icon("loader", { width: 18, height: 18, style: { animation: "spin 1s linear infinite" } })
                        : icon("refresh-cw", { width: 18, height: 18 })
                      }
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      onClick={onReprocess}
                      disabled={!canReprocess || isReprocessing}
                      aria-label="Reprocess pipeline"
                      title="Reprocess: re-run planning, resolution, and execution on current filesystem state"
                      style={{ position: "relative" }}
                    >
                      {isReprocessing
                        ? icon("loader", { width: 18, height: 18, style: { animation: "spin 1s linear infinite" } })
                        : <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                      }
                    </button>
                  </div>
                );
              }

              function filterLogLine(line) {
                // Returns: { show: boolean, text: string }
                // - If line is not JSON: show as-is
                // - If line is JSON with extractable human text: show the extracted text
                // - If line is JSON with no useful text: suppress
                try {
                  const parsed = JSON.parse(line);
                  // Claude CLI assistant messages: extract content[].text
                  if (parsed.type === "assistant" && Array.isArray(parsed.message?.content)) {
                    const texts = parsed.message.content
                      .filter(block => block.type === "text" && block.text)
                      .map(block => block.text.trim())
                      .filter(Boolean);
                    if (texts.length > 0) {
                      return { show: true, text: texts.join(" ") };
                    }
                  }
                  // Tool use results or other messages with a top-level "text" field
                  if (typeof parsed.text === "string" && parsed.text.trim()) {
                    return { show: true, text: parsed.text.trim() };
                  }
                  // JSON with no extractable human-readable content — suppress
                  return { show: false, text: "" };
                } catch {
                  // Not JSON — show as-is
                  return { show: true, text: line };
                }
              }

              function PlannerAgentCard({ agent, logLines, detailMessage }) {
                const [elapsed, setElapsed] = useState(agent.elapsed || 0);
                const logTailRef = useRef(null);
                useEffect(() => {
                  setElapsed(agent.elapsed || 0);
                }, [agent.elapsed]);
                useEffect(() => {
                  const timer = setInterval(() => setElapsed((prev) => prev + 1), 1000);
                  return () => clearInterval(timer);
                }, []);
                useEffect(() => {
                  if (logTailRef.current) {
                    logTailRef.current.scrollTop = logTailRef.current.scrollHeight;
                  }
                }, [logLines.length]);
                return (
                  <div style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-medium)',
                    borderRadius: 'var(--radius-lg)',
                    padding: 'var(--space-4)',
                    display: 'flex',
                    flexDirection: 'column',
                    height: '280px',
                    minWidth: 0,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-2)', minWidth: 0 }}>
                      <span className="mono" style={{ fontSize: 'var(--text-sm)', color: 'var(--status-active)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }} title={agent.file}>
                        {agent.file}
                      </span>
                      <span className="mono muted" style={{ fontSize: 'var(--text-xs)', flexShrink: 0, whiteSpace: 'nowrap', marginLeft: 'var(--space-2)' }}>
                        {formatElapsed(elapsed)}
                      </span>
                    </div>
                    {detailMessage ? (
                      <div className="detail-line" style={{
                        marginBottom: 'var(--space-2)',
                        padding: 'var(--space-1) var(--space-2)',
                        background: 'rgba(59, 130, 246, 0.08)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: 'var(--text-xs)',
                        color: 'var(--status-active)',
                        fontFamily: 'monospace',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {detailMessage}
                      </div>
                    ) : null}
                    <div ref={logTailRef} className="log-tail" style={{ flex: 1, minHeight: 0, overflowY: 'auto', fontSize: 'var(--text-xs)' }}>
                      {logLines.length > 0
                        ? logLines.map(entry => filterLogLine(entry.line)).filter(r => r.show).slice(-10).map((r, idx) => (
                            <div key={idx} className="log-line">{r.text}</div>
                          ))
                        : <div className="log-line muted">Waiting for output...</div>
                      }
                    </div>
                  </div>
                );
              }

              function PhaseActivityCard({ title, subtitle, statusLabel, events, pipeline, phaseLogs, planningAgents, taskLogs, detailMessage, phaseDetail }) {
                const totalIn = pipeline?.intake || 0;
                const claimed = pipeline?.planning || 0;
                const staged = pipeline?.staged || 0;
                const review = pipeline?.review || 0;
                const total = totalIn + claimed + staged + review;
                const processed = staged + review;
                const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0;
                const logLines = phaseLogs || [];
                const logTailRef = useRef(null);
                const [elapsed, setElapsed] = useState(0);
                useEffect(() => {
                  const timer = setInterval(() => setElapsed((prev) => prev + 1), 1000);
                  return () => clearInterval(timer);
                }, []);
                useEffect(() => {
                  if (logTailRef.current) {
                    logTailRef.current.scrollTop = logTailRef.current.scrollHeight;
                  }
                }, [logLines.length]);
                return (
                  <article className="worker-card active" style={{ gridColumn: '1 / -1' }}>
                    <div className="worker-card-header">
                      <div className="worker-card-title">
                        <span className="mono" style={{ color: 'var(--status-active)', fontSize: 'var(--text-md)' }}>{title}</span>
                        <span className="secondary">{subtitle}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                        <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>{formatElapsed(elapsed)}</span>
                        <span className="status-badge" style={statusBadgeStyle("active")}>{statusLabel}</span>
                      </div>
                    </div>
                    {total > 0 ? (
                      <div style={{ marginTop: 'var(--space-3)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>{`${processed}/${total} processed`}</span>
                          <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>{`${progressPct}%`}</span>
                        </div>
                        <div className="progress-bar" style={{ gridTemplateColumns: '1fr' }}>
                          <span style={{
                            background: 'var(--status-active)',
                            width: `${progressPct}%`,
                            transition: 'width 400ms ease',
                            display: 'block',
                          }} />
                        </div>
                      </div>
                    ) : null}
                    {detailMessage ? (
                      <div className="detail-line" style={{
                        marginTop: 'var(--space-2)',
                        padding: 'var(--space-1) var(--space-2)',
                        background: 'rgba(59, 130, 246, 0.08)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: 'var(--text-xs)',
                        color: 'var(--status-active)',
                        fontFamily: 'monospace',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {detailMessage}
                      </div>
                    ) : null}
                    {(planningAgents || []).length > 0 ? (
                      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min((planningAgents || []).length, 4)}, minmax(0, 1fr))`, gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
                        {(planningAgents || []).map((agent) => (
                          <PlannerAgentCard
                            key={agent.planner_task_id}
                            agent={agent}
                            logLines={(taskLogs || {})[agent.planner_task_id] || []}
                            detailMessage={(phaseDetail || {})[agent.planner_task_id]}
                          />
                        ))}
                      </div>
                    ) : (
                      <div ref={logTailRef} className="log-tail" style={{ minHeight: '60px', maxHeight: '240px', overflowY: 'auto' }}>
                        {logLines.length > 0 ? (
                          logLines
                            .map(entry => filterLogLine(entry.line))
                            .filter(r => r.show)
                            .slice(-20)
                            .map((r, idx) => (
                              <div key={idx} className="log-line">{r.text}</div>
                            ))
                        ) : events.length === 0 ? (
                          <div className="log-line muted">Claude CLI running... ({formatElapsed(elapsed)})</div>
                        ) : events.slice(-8).map((evt, idx) => (
                          <div key={idx} className={`log-line ${evt.type?.includes("error") ? "error" : evt.type?.includes("fail") ? "error" : ""}`}>
                            <span className="muted" style={{ marginRight: '8px' }}>{evt.timestamp?.slice(11, 19) || ""}</span>
                            {evt.message}
                          </div>
                        ))}
                      </div>
                    )}
                  </article>
                );
              }

              function VerificationCard({ sessionStatus, runtimeState, effectiveConfig, recentEvents, taskLogs, onOpenTask }) {
                const isVerifying = sessionStatus === "verifying";
                const isAutoFix = sessionStatus === "auto_fixing";
                const reason = runtimeState.verification_reason;
                const attempt = runtimeState.auto_fix_attempt || 0;
                const maxAttempts = effectiveConfig.auto_fix?.max_attempts || 0;
                const fixContext = runtimeState.auto_fix_context;
                const fixTaskId = runtimeState.auto_fix_task_id;
                const lastSummary = runtimeState.last_fix_summary;

                // Live timer — syncs from server on each push, ticks locally between pushes
                const [elapsed, setElapsed] = useState(runtimeState.verification_elapsed || 0);
                const logTailRef = useRef(null);
                const [expanded, setExpanded] = useState(false);
                useEffect(() => {
                  setElapsed(runtimeState.verification_elapsed || 0);
                }, [runtimeState.verification_elapsed]);
                useEffect(() => {
                  if (!isVerifying && !isAutoFix) return;
                  const timer = setInterval(() => setElapsed(prev => prev + 1), 1000);
                  return () => clearInterval(timer);
                }, [isVerifying, isAutoFix]);

                // Auto-scroll log tail
                useEffect(() => {
                  if (logTailRef.current && !expanded) {
                    logTailRef.current.scrollTop = logTailRef.current.scrollHeight;
                  }
                });

                const reasonLabel = verificationReasonLabel(reason, sessionStatus);

                const borderColor = isAutoFix ? 'rgba(249, 115, 22, 0.4)' : 'rgba(245, 158, 11, 0.4)';
                const glowColor = isAutoFix ? 'rgba(249, 115, 22, 0.15)' : 'rgba(245, 158, 11, 0.15)';
                const accentColor = isAutoFix ? 'var(--status-review)' : 'var(--status-active)';

                // Streaming log lines from taskLogs
                const autoFixLines = (taskLogs || {})["__phase_auto_fix__"] || [];
                const verificationLines = (taskLogs || {})["__phase_verification__"] || [];
                const streamingLines = isAutoFix ? autoFixLines : verificationLines;
                const verificationStart = runtimeState?.verification_started_at;
                const eventLines = recentEvents.filter(e => {
                  const isRelevantType = e.type?.includes("verification") || e.type?.includes("auto_fix");
                  if (!isRelevantType) return false;
                  if (!verificationStart || !e.timestamp) return true;
                  return e.timestamp >= verificationStart;
                });
                const hasContent = streamingLines.length > 0 || eventLines.length > 0;

                return (
                  <article className="worker-card active" style={{
                    gridColumn: '1 / -1', borderColor, boxShadow: `0 0 12px ${glowColor}`,
                    cursor: 'pointer',
                  }} onClick={() => setExpanded(e => !e)}>
                    <div className="worker-card-header">
                      <div className="worker-card-title">
                        <span style={{ color: accentColor, fontSize: 'var(--text-md)', fontWeight: 600 }}>
                          {reasonLabel}
                        </span>
                        {fixContext === "task_failure" && fixTaskId ? (
                          <button
                            type="button"
                            className="nav-link"
                            style={{ padding: 0, fontSize: 'var(--text-xs)', textDecoration: 'underline' }}
                            onClick={(e) => { e.stopPropagation(); if (onOpenTask) onOpenTask(fixTaskId); }}
                          >
                            View task: {fixTaskId}
                          </button>
                        ) : null}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                        <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>{expanded ? "▲" : "▼"}</span>
                        <span className="status-badge" style={statusBadgeStyle(isAutoFix ? "review" : "active")}>
                          {isAutoFix ? `attempt ${attempt}/${maxAttempts}` : "running"}
                        </span>
                      </div>
                    </div>
                    {(isVerifying || isAutoFix) ? (
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                        marginTop: 'var(--space-2)',
                        fontSize: 'var(--text-xs)', color: 'var(--text-secondary)',
                      }}>
                        <span className="mono muted">Elapsed:</span>
                        <span className="mono">{formatElapsed(elapsed)}</span>
                      </div>
                    ) : null}
                    {isAutoFix && maxAttempts > 0 ? (
                      <div style={{ marginTop: 'var(--space-3)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>
                            {fixContext === "task_failure" && fixTaskId
                              ? `Fixing task: ${fixTaskId}`
                              : "Fixing verification failures"}
                          </span>
                          <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>
                            {`${attempt}/${maxAttempts}`}
                          </span>
                        </div>
                        <div className="progress-bar" style={{ gridTemplateColumns: `repeat(${maxAttempts}, 1fr)` }}>
                          {Array.from({ length: maxAttempts }).map((_, i) => (
                            <span key={i} className={i < attempt ? "done" : i === attempt ? "active" : "future"} />
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {lastSummary ? (
                      <div style={{
                        marginTop: 'var(--space-2)', padding: 'var(--space-2)',
                        background: 'var(--bg-surface)', borderRadius: '4px',
                        fontSize: 'var(--text-xs)', color: 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        maxHeight: '120px', overflowY: 'auto',
                      }}>
                        <span className="muted">Last fix: </span>{lastSummary}
                      </div>
                    ) : null}
                    {expanded ? (
                      <div className="log-tail" style={{ maxHeight: '400px', minHeight: '200px', overflowY: 'auto' }}>
                        {eventLines.map((evt, idx) => (
                          <div key={`evt-${idx}`} className={`log-line ${evt.type?.includes("fail") ? "error" : ""}`} style={{ whiteSpace: 'pre-wrap' }}>
                            <span className="muted" style={{ marginRight: '8px' }}>{evt.timestamp?.slice(11, 19) || ""}</span>
                            {evt.message}
                          </div>
                        ))}
                        {streamingLines.map(entry => filterLogLine(entry.line)).filter(r => r.show).map((r, idx) => (
                          <div key={`log-${idx}`} className="log-line">{r.text}</div>
                        ))}
                        {!hasContent ? (
                          <div className="log-line muted">
                            {isVerifying ? "Running verification command..." : "Running auto-fix agent..."}
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div ref={logTailRef} className="log-tail" style={{ minHeight: '60px', maxHeight: '250px', overflowY: 'auto' }}>
                        {eventLines.slice(-6).map((evt, idx) => (
                          <div key={`evt-${idx}`} className={`log-line ${evt.type?.includes("fail") ? "error" : ""}`} style={{ whiteSpace: 'pre-wrap' }}>
                            <span className="muted" style={{ marginRight: '8px' }}>{evt.timestamp?.slice(11, 19) || ""}</span>
                            {evt.message}
                          </div>
                        ))}
                        {streamingLines.map(entry => filterLogLine(entry.line)).filter(r => r.show).slice(-15).map((r, idx) => (
                          <div key={`log-${idx}`} className="log-line">{r.text}</div>
                        ))}
                        {!hasContent ? (
                          <div className="log-line muted">
                            {isVerifying ? "Running verification command..." : "Running auto-fix agent..."}
                          </div>
                        ) : null}
                      </div>
                    )}
                  </article>
                );
              }

              function copyToClipboard(text, setCopied) {
                navigator.clipboard.writeText(text).then(() => {
                  if (setCopied) {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                  }
                }).catch(() => {});
              }

              function CompletionCard({ currentSession, tasks, pipeline, onCleanup }) {
                const env = currentSession?.config?.environment || {};
                const sourceRepo = env.COGNITIVE_SWITCHYARD_SOURCE_REPO || "";
                const worktreeRoot = env.COGNITIVE_SWITCHYARD_REPO_ROOT || "";
                const branch = env.COGNITIVE_SWITCHYARD_BRANCH || "";
                const hasWorktree = !!(sourceRepo && worktreeRoot && sourceRepo !== worktreeRoot);

                const doneTasks = (tasks || []).filter(t => t.status === "done");
                const sessionName = currentSession?.name || currentSession?.id || "session";
                const defaultCommitMsg = [
                  "feat: " + sessionName,
                  "",
                  "Implemented:",
                  ...doneTasks.map(t => "- [" + t.task_id + "] " + t.title),
                  ...(pipeline.blocked > 0 ? ["", "Blocked: " + pipeline.blocked + " task(s)"] : []),
                  "",
                  "Session: " + (currentSession?.id || ""),
                ].join("\\n");

                const [editableCommitMsg, setEditableCommitMsg] = React.useState(defaultCommitMsg);
                const [worktreeCleaned, setWorktreeCleaned] = React.useState(false);
                const [cleaningUp, setCleaningUp] = React.useState(false);
                const [copiedValidate, setCopiedValidate] = React.useState(false);
                const [copiedSquash, setCopiedSquash] = React.useState(false);
                const [copiedPr, setCopiedPr] = React.useState(false);
                const [copiedMsg, setCopiedMsg] = React.useState(false);

                const validateCmds = hasWorktree
                  ? "cd " + worktreeRoot + "\\ngit log --oneline\\ngit diff --stat HEAD~1"
                  : "";
                const squashCmds = hasWorktree
                  ? "cd " + sourceRepo + "\\ngit merge --squash " + branch + "\\ngit commit -m \\"" + editableCommitMsg.replace(/"/g, '\\\\"') + "\\""
                  : "";
                const prCmds = hasWorktree
                  ? "cd " + sourceRepo + "\\ngh pr create --head " + branch
                  : "";

                async function handleCleanup() {
                  if (!currentSession?.id) return;
                  const confirmed = window.confirm("Remove the worktree for this session? This cannot be undone.");
                  if (!confirmed) return;
                  setCleaningUp(true);
                  try {
                    await fetch("/api/sessions/" + currentSession.id + "/cleanup-worktree", { method: "POST" });
                    setWorktreeCleaned(true);
                    if (onCleanup) onCleanup();
                  } catch (e) {
                    alert("Cleanup failed: " + e.message);
                  } finally {
                    setCleaningUp(false);
                  }
                }

                return (
                  <section className="worker-grid">
                    <article className="worker-card" style={{ gridColumn: "1 / -1", borderColor: "rgba(52, 211, 153, 0.3)" }}>
                      <div className="worker-card-header">
                        <div className="worker-card-title">
                          <span className="mono" style={{ color: "var(--status-done)", fontSize: "var(--text-md)" }}>
                            Session Completed — Next Steps
                          </span>
                          <span className="secondary">
                            {pipeline.done || 0} task(s) done{pipeline.blocked > 0 ? ", " + pipeline.blocked + " blocked" : ""}
                          </span>
                        </div>
                        <span className="status-badge" style={{ background: "rgba(52, 211, 153, 0.15)", color: "var(--status-done)", border: "1px solid rgba(52, 211, 153, 0.3)" }}>completed</span>
                      </div>

                      {hasWorktree && !worktreeCleaned ? (
                        <div>
                          <div className="completion-card-section">
                            <h4>1. Validate</h4>
                            <div className="completion-code-block">
                              {validateCmds}
                              <button type="button" className="copy-btn" onClick={() => copyToClipboard(validateCmds, setCopiedValidate)}>
                                {copiedValidate ? "Copied!" : "Copy"}
                              </button>
                            </div>
                          </div>

                          <div className="completion-card-section">
                            <h4>2. Commit message</h4>
                            <textarea
                              className="commit-msg-textarea"
                              value={editableCommitMsg}
                              onChange={e => setEditableCommitMsg(e.target.value)}
                              rows={8}
                            />
                            <button
                              type="button"
                              className="secondary-button"
                              style={{ marginTop: "var(--space-2)", fontSize: "var(--text-xs)" }}
                              onClick={() => copyToClipboard(editableCommitMsg, setCopiedMsg)}
                            >
                              {copiedMsg ? "Copied!" : "Copy message"}
                            </button>
                          </div>

                          <div className="completion-card-section">
                            <h4>3a. Squash merge into upstream</h4>
                            <div className="completion-code-block">
                              {"cd " + sourceRepo + "\\ngit merge --squash " + branch + "\\ngit commit"}
                              <button type="button" className="copy-btn" onClick={() => copyToClipboard("cd " + sourceRepo + "\\ngit merge --squash " + branch + "\\ngit commit", setCopiedSquash)}>
                                {copiedSquash ? "Copied!" : "Copy"}
                              </button>
                            </div>
                          </div>

                          <div className="completion-card-section">
                            <h4>3b. Open a pull request</h4>
                            <div className="completion-code-block">
                              {prCmds}
                              <button type="button" className="copy-btn" onClick={() => copyToClipboard(prCmds, setCopiedPr)}>
                                {copiedPr ? "Copied!" : "Copy"}
                              </button>
                            </div>
                          </div>

                          <div className="completion-card-section">
                            <button
                              type="button"
                              className="secondary-button"
                              style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}
                              disabled={cleaningUp}
                              onClick={handleCleanup}
                            >
                              {cleaningUp ? "Cleaning up..." : "Clean up worktree"}
                            </button>
                          </div>
                        </div>
                      ) : hasWorktree && worktreeCleaned ? (
                        <div className="completion-card-section">
                          <span className="mono muted" style={{ fontSize: "var(--text-sm)" }}>Worktree cleaned up.</span>
                        </div>
                      ) : (
                        <div className="completion-card-section">
                          <span style={{ color: "var(--text-secondary)", fontSize: "var(--text-sm)" }}>
                            Session output is in:{" "}
                            <span className="mono" style={{ fontSize: "var(--text-xs)" }}>{currentSession?.id || ""}</span>
                          </span>
                        </div>
                      )}
                    </article>
                  </section>
                );
              }

              const TASK_TRANSITIONS = {
                blocked: [
                  { target: "ready", label: "Retry", icon: "refresh-cw" },
                  { target: "intake", label: "Re-plan", icon: "edit" },
                ],
                review: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                  { target: "ready", label: "Approve & Queue", icon: "check-circle" },
                ],
                done: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                  { target: "ready", label: "Re-execute", icon: "refresh-cw" },
                ],
                staged: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                  { target: "review", label: "Send to Review", icon: "eye" },
                ],
                planning: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                ],
              };

              function MonitorView({ dashboard, currentSession, tasks, taskLogs, phaseDetail, onOpenTask, onOpenDag, onRevealFile, onMoveTask, onRescan, isRescanning, onReprocess, isReprocessing }) {
                const pipeline = dashboard?.pipeline || {};
                const pipelineDirs = dashboard?.pipeline_dirs || {};
                const workers = dashboard?.workers || [];
                const recentEvents = dashboard?.recent_events || [];
                const sessionStatus = dashboard?.session?.status || currentSession?.status || "created";
                const runtimeState = dashboard?.runtime_state || {};
                const effectiveConfig = dashboard?.effective_runtime_config || {};
                const isPreExecution = ["planning", "resolving"].includes(sessionStatus);
                const isExecution = ["running", "paused", "verifying", "auto_fixing"].includes(sessionStatus);
                const isTerminal = ["completed", "aborted"].includes(sessionStatus);
                const canReprocess = currentSession
                  && ["created", "idle", "paused"].includes(sessionStatus)
                  && !isReprocessing
                  && !currentSession.workers?.some(w => w.status === "active")
                  && ((pipeline.intake || 0) + (pipeline.staged || 0) + (pipeline.ready || 0)) > 0;

                return (
                  <div>
                    <PipelineStrip
                      pipeline={pipeline}
                      pipelineDirs={pipelineDirs}
                      sessionStatus={sessionStatus}
                      currentSession={currentSession}
                      onRevealFile={onRevealFile}
                      onOpenDag={onOpenDag}
                      onRescan={onRescan}
                      isRescanning={isRescanning}
                      onReprocess={onReprocess}
                      isReprocessing={isReprocessing}
                      canReprocess={canReprocess}
                    />
                    <HealthSummaryBar tasks={tasks} workers={workers} />
                    {recentEvents.length > 0 ? (
                      <div className="event-feed">
                        {recentEvents.map((evt, idx) => (
                          <div key={idx} className={`event-row ${evt.type === "session_error" ? "error" : evt.type === "pipeline_stopped" ? "warning" : ""}`}>
                            <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>{evt.timestamp?.slice(11, 19) || ""}</span>
                            <span className="mono" style={{ fontSize: 'var(--text-xs)', color: evt.type === "session_error" ? "var(--status-blocked)" : evt.type === "pipeline_stopped" ? "var(--status-review)" : "var(--text-secondary)" }}>
                              {evt.type}
                            </span>
                            <span style={{ fontSize: 'var(--text-sm)', flex: 1, minWidth: 0, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>{evt.message}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    <main className="page">
                      {isPreExecution ? (
                        <section className="worker-grid">
                          <PhaseActivityCard
                            title={sessionStatus === "planning" ? "Planning Phase" : "Resolution Phase"}
                            subtitle={sessionStatus === "planning"
                              ? `Analyzing intake items and generating task plans (${pipeline.planning || 0} claimed, ${pipeline.staged || 0} staged, ${pipeline.review || 0} to review)`
                              : `Resolving dependencies and ordering tasks (${pipeline.staged || 0} staged plans)`}
                            statusLabel={sessionStatus}
                            events={recentEvents}
                            pipeline={pipeline}
                            phaseLogs={taskLogs[sessionStatus === "planning" ? "__phase_planning__" : "__phase_resolution__"] || []}
                            planningAgents={sessionStatus === "planning" ? (dashboard?.planning_agents || []) : []}
                            taskLogs={taskLogs}
                            detailMessage={phaseDetail[sessionStatus === "planning" ? "__phase_planning__" : "__phase_resolution__"]}
                            phaseDetail={phaseDetail}
                          />
                          {pipeline.review > 0 ? (
                            <article className="worker-card" style={{
                              borderColor: 'rgba(249, 115, 22, 0.4)',
                              boxShadow: '0 0 12px rgba(249, 115, 22, 0.15)',
                            }}>
                              <div className="worker-card-header">
                                <div className="worker-card-title">
                                  <span className="mono" style={{ color: 'var(--status-review)', fontSize: 'var(--text-md)' }}>Items in Review</span>
                                  <span className="secondary">{`${pipeline.review} item(s) need human review before proceeding`}</span>
                                </div>
                                <span className="status-badge" style={statusBadgeStyle("review")}>{pipeline.review}</span>
                              </div>
                              <div className="log-tail" style={{ minHeight: '40px' }}>
                                <div className="log-line">
                                  <button type="button" className="nav-link" onClick={() => pipelineDirs.review && onRevealFile(pipelineDirs.review)} style={{ textDecoration: 'underline', padding: 0 }}>
                                    Open review directory to inspect
                                  </button>
                                </div>
                              </div>
                            </article>
                          ) : null}
                        </section>
                      ) : null}

                      {isExecution ? (
                        <React.Fragment>
                          {sessionStatus === "verifying" || sessionStatus === "auto_fixing" ? (
                            <section className="worker-grid" style={{ marginBottom: 'var(--space-4)' }}>
                              <VerificationCard
                                sessionStatus={sessionStatus}
                                runtimeState={runtimeState}
                                effectiveConfig={effectiveConfig}
                                recentEvents={recentEvents}
                                taskLogs={taskLogs}
                                onOpenTask={onOpenTask}
                              />
                            </section>
                          ) : null}
                          {sessionStatus === "running" && effectiveConfig.verification_interval > 0 ? (
                            runtimeState.verification_pending ? (
                              <div className="verification-countdown" style={{
                                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                                padding: 'var(--space-2) var(--space-3)',
                                marginBottom: 'var(--space-3)',
                                background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px',
                                border: '1px solid rgba(245, 158, 11, 0.3)',
                                fontSize: 'var(--text-xs)',
                              }}>
                                <span className="mono" style={{ color: 'var(--status-active)' }}>
                                  {`Verification pending: ${verificationReasonLabel(runtimeState.verification_reason, sessionStatus)}`}
                                </span>
                              </div>
                            ) : (
                              <div className="verification-countdown" style={{
                                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                                padding: 'var(--space-2) var(--space-3)',
                                marginBottom: 'var(--space-3)',
                                background: 'var(--bg-elevated)', borderRadius: '6px',
                                border: '1px solid var(--border-subtle)',
                                fontSize: 'var(--text-xs)',
                              }}>
                                <span className="mono muted">Next verification:</span>
                                <span className="mono" style={{ color: 'var(--status-active)' }}>
                                  {`${runtimeState.completed_since_verification || 0} / ${effectiveConfig.verification_interval} tasks`}
                                </span>
                                <div style={{
                                  flex: 1, height: '4px', background: 'var(--border-subtle)',
                                  borderRadius: '2px', overflow: 'hidden',
                                }}>
                                  <div style={{
                                    width: `${Math.min(100, ((runtimeState.completed_since_verification || 0) / effectiveConfig.verification_interval) * 100)}%`,
                                    height: '100%', background: 'var(--status-active)',
                                    transition: 'width 400ms ease',
                                  }} />
                                </div>
                              </div>
                            )
                          ) : null}
                          {runtimeState.last_verification_test_summary ? (
                            <div style={{
                              display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                              padding: 'var(--space-2) var(--space-3)',
                              marginBottom: 'var(--space-3)',
                              background: 'rgba(34, 197, 94, 0.08)', borderRadius: '6px',
                              border: '1px solid rgba(34, 197, 94, 0.25)',
                              fontSize: 'var(--text-xs)',
                            }}>
                              <span style={{ color: 'rgb(34, 197, 94)', fontSize: '12px' }}>&#10003;</span>
                              <span className="mono" style={{ color: 'rgb(34, 197, 94)' }}>
                                {runtimeState.last_verification_test_summary}
                              </span>
                            </div>
                          ) : null}
                          <section className="worker-grid">
                            {workers.map((worker, index) => {
                              const lineTail = (() => {
                                if (worker.task_id && taskLogs[worker.task_id]?.length) {
                                  return taskLogs[worker.task_id].map((entry) => ({ line: entry.line, ts: entry.ts }));
                                }
                                if (worker.last_log_line) {
                                  return [{ line: worker.last_log_line, ts: null }];
                                }
                                return [{ line: "Waiting for task...", ts: null }];
                              })();
                              const phaseTotal = Math.max(1, Number(worker.phase_total) || 1);
                              const currentIndex = Math.max(0, (Number(worker.phase_num) || 1) - 1);
                              const isIdleWarning = worker.status === "active"
                                && worker.task_idle_limit > 0
                                && (worker.last_activity_ago || 0) >= (worker.task_idle_limit * 2) / 3;
                              const stateClass = isIdleWarning
                                ? "worker-card warning"
                                : worker.status === "active"
                                  ? "worker-card active"
                                  : worker.status === "problem"
                                    ? "worker-card problem"
                                    : "worker-card idle";
                              return (
                                <article
                                  key={worker.slot}
                                  className={stateClass}
                                  onClick={() => worker.task_id && onOpenTask(worker.task_id)}
                                  style={{ animationDelay: `${160 + index * 60}ms` }}
                                >
                                  <div className="worker-card-header">
                                    <div className="worker-card-title">
                                      <span className="mono muted">{`slot ${worker.slot}`}</span>
                                      <span className="mono">{worker.task_id || "idle"}</span>
                                      <span className="secondary">{worker.task_title || "Waiting for task..."}</span>
                                    </div>
                                    <span className="status-badge" style={statusBadgeStyle(isIdleWarning ? "warning" : worker.status)}>
                                      {isIdleWarning ? "warning" : worker.status}
                                    </span>
                                  </div>
                                  {worker.status !== "idle" ? (
                                    <React.Fragment>
                                      <div
                                        className="progress-bar"
                                        style={{ gridTemplateColumns: `repeat(${phaseTotal}, 1fr)` }}
                                      >
                                        {Array.from({ length: phaseTotal }).map((_, phaseIndex) => {
                                          let phaseClass = "future";
                                          if (phaseIndex < currentIndex) {
                                            phaseClass = "done";
                                          } else if (phaseIndex === currentIndex && worker.status === "active") {
                                            phaseClass = "active";
                                          }
                                          return <span key={phaseIndex} className={phaseClass} />;
                                        })}
                                      </div>
                                      {worker.detail ? <div className="detail-line">{worker.detail}</div> : null}
                                      <div className="detail-line muted" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <span>{formatElapsed(worker.elapsed || 0)}</span>
                                        <LastActivityIndicator worker={worker} />
                                      </div>
                                      <div className="log-tail">
                                        {lineTail.map(e => ({ ...filterLogLine(e.line), ts: e.ts })).filter(r => r.show).slice(-5).map((r, lineIndex) => (
                                          <div key={lineIndex} className="log-line">
                                            {r.ts ? <span className="mono muted" style={{ marginRight: '6px', fontSize: 'var(--text-xs)' }}>{r.ts.slice(11, 19)}</span> : null}
                                            {r.text}
                                          </div>
                                        ))}
                                      </div>
                                    </React.Fragment>
                                  ) : null}
                                </article>
                              );
                            })}
                          </section>
                        </React.Fragment>
                      ) : null}

                      {isTerminal ? (
                        sessionStatus === "completed" ? (
                          <CompletionCard
                            currentSession={currentSession}
                            tasks={tasks}
                            pipeline={pipeline}
                          />
                        ) : (
                          <section className="worker-grid">
                            <article className="worker-card" style={{
                              gridColumn: '1 / -1',
                              borderColor: 'rgba(239, 68, 68, 0.3)',
                            }}>
                              <div className="worker-card-header">
                                <div className="worker-card-title">
                                  <span className="mono" style={{
                                    color: 'var(--status-blocked)',
                                    fontSize: 'var(--text-md)',
                                  }}>
                                    Session Aborted
                                  </span>
                                  <span className="secondary">
                                    {`${pipeline.done || 0} tasks completed, ${pipeline.blocked || 0} blocked`}
                                  </span>
                                </div>
                                <span className="status-badge" style={statusBadgeStyle(sessionStatus)}>{sessionStatus}</span>
                              </div>
                            </article>
                          </section>
                        )
                      ) : null}

                      {!isPreExecution && !isExecution && !isTerminal && sessionStatus === "created" ? (
                        <div className="empty-state">
                          Session created but not yet started. Go to Setup to configure and start.
                        </div>
                      ) : null}

                      {pipeline.review > 0 && isExecution ? (
                        <article className="worker-card" style={{
                          marginTop: 'var(--space-4)',
                          borderColor: 'rgba(249, 115, 22, 0.4)',
                          boxShadow: '0 0 12px rgba(249, 115, 22, 0.15)',
                        }}>
                          <div className="worker-card-header">
                            <div className="worker-card-title">
                              <span className="mono" style={{ color: 'var(--status-review)' }}>Items in Review</span>
                              <span className="secondary">{`${pipeline.review} item(s) parked for human review`}</span>
                            </div>
                            <button type="button" className="secondary-button" onClick={() => pipelineDirs.review && onRevealFile(pipelineDirs.review)}>
                              Open Review
                            </button>
                          </div>
                        </article>
                      ) : null}

                      <section className="task-feed">
                        {tasks.length === 0 && isPreExecution ? (
                          <div className="empty-state muted" style={{ padding: 'var(--space-4)' }}>
                            Tasks will appear here once planning completes and resolution assigns execution order.
                          </div>
                        ) : tasks.length === 0 ? (
                          <div className="empty-state">No tasks in this session yet.</div>
                        ) : tasks.map((task) => (
                          <div
                            key={task.task_id}
                            className={`task-row ${task.status === "blocked" ? "blocked" : task.status === "active" ? "active" : ""}`}
                            onClick={() => onOpenTask(task.task_id)}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%' }}>
                              <span className="mono">{task.task_id}</span>
                              <span className="secondary task-title">{task.title}</span>
                              {(task.depends_on || []).length > 0 ? icon("link", { width: 12, height: 12 }) : null}
                              {(task.anti_affinity || []).length > 0 ? icon("shield", { width: 12, height: 12 }) : null}
                              {task.full_test_after ? (
                                <span title="Full test after completion" style={{
                                  fontSize: 'var(--text-xs)',
                                  color: 'var(--status-active)',
                                  fontWeight: 600,
                                  padding: '0 4px',
                                  background: 'rgba(245, 158, 11, 0.15)',
                                  borderRadius: '3px',
                                }}>FTA</span>
                              ) : null}
                              {task.started_at ? (
                                <span className="mono muted" style={{ fontSize: 'var(--text-xs)' }}>
                                  {task.started_at.slice(11, 19)}
                                </span>
                              ) : null}
                              <span className="status-badge" style={statusBadgeStyle(task.status)}>{task.status}</span>
                              <TaskRowElapsed task={task} />
                              <div className="task-actions" onClick={(e) => e.stopPropagation()}>
                                {(TASK_TRANSITIONS[task.status] || []).map(({ target, label, icon: iconName }) => (
                                  <button
                                    key={target}
                                    type="button"
                                    className="icon-button"
                                    title={`${label} (\u2192 ${target})`}
                                    onClick={() => onMoveTask(task.task_id, target)}
                                  >
                                    {icon(iconName, { width: 14, height: 14 })}
                                  </button>
                                ))}
                                <button
                                  type="button"
                                  className="icon-button"
                                  title="Reveal plan file"
                                  onClick={() => onRevealFile(task.plan_path)}
                                >
                                  {icon("file-text", { width: 14, height: 14 })}
                                </button>
                              </div>
                            </div>
                            {(() => {
                              const evts = task.events || [];
                              const last = evts.length ? evts[evts.length - 1] : null;
                              if (!last || !["task.blocked", "session_error"].includes(last.type)) return null;
                              const color = "var(--status-blocked)";
                              return (
                                <div style={{ fontSize: 'var(--text-xs)', color, marginTop: '2px', paddingLeft: '2px' }}>
                                  {last.message}
                                </div>
                              );
                            })()}
                          </div>
                        ))}
                      </section>
                    </main>
                  </div>
                );
              }

              function SetupView({
                currentSession,
                setupDraft,
                setSetupDraft,
                selectedPack,
                packs,
                intake,
                preflight,
                settings,
                showAdvanced,
                setShowAdvanced,
                isBusy,
                repoRootInfo,
                repoBranches,
                onCreateDraft,
                onStartSession,
                onRefreshIntake,
                onRunPreflight,
                onOpenIntake,
                onOpenIntakeTerminal,
                onRevealFile,
                onBrowseRepoRoot,
                onBrowseProjectDir,
                onResolveRepoRoot,
                onCreateBranch,
                onDiscardDraft,
                onNewRun,
                onNavigate
              }) {
                const sessionStatus = currentSession?.status || "none";
                const draftExists = sessionStatus === "created";
                const sessionActive = ACTIVE_STATUSES.has(sessionStatus) && sessionStatus !== "idle";
                const formLocked = draftExists || sessionActive || sessionStatus === "idle";
                const files = intake?.files || [];
                const packSupportsPlanning = Boolean(selectedPack?.planning_enabled);
                const packSupportsVerification = Boolean(selectedPack?.verification_enabled);
                const isIdle = sessionStatus === "idle";
                const canManageIntake = draftExists || isIdle;
                const canStart = draftExists && files.length > 0 && (preflight?.ok ?? false);
                const [newBranchName, setNewBranchName] = useState("");
                const [creatingBranch, setCreatingBranch] = useState(false);
                const showBranchSelector = repoRootInfo && repoRootInfo.is_git && repoBranches.length > 0;
                const showNewBranchInput = setupDraft.branch === "__new__";
                if (sessionActive) {
                  return (
                    <div className="setup-shell">
                      <section className="setup-card" style={{ textAlign: 'center' }}>
                        <h1 className="view-title">Session Active</h1>
                        <p className="secondary" style={{ marginBottom: 'var(--space-6)' }}>
                          {`Session "${currentSession?.name}" is ${sessionStatus}. Configuration is locked while a session is running.`}
                        </p>
                        <button type="button" className="action-button" onClick={() => onNavigate("monitor")}>
                          Go to Monitor
                        </button>
                      </section>
                    </div>
                  );
                }
                return (
                  <div className="setup-shell">
                    <section className="setup-card">
                      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                        <h1 className="view-title" style={{ margin: 0 }}>
                          {currentSession ? `Session: ${currentSession.name}` : "Configure Session"}
                        </h1>
                        {draftExists ? (
                          <button
                            type="button"
                            className="secondary-button"
                            style={{ color: '#ef4444' }}
                            disabled={isBusy}
                            onClick={onDiscardDraft}
                          >Reset</button>
                        ) : null}
                      </div>
                      {draftExists ? (
                        <div className="field-hint" style={{ marginBottom: '0.75rem' }}>
                          {`Pack: ${currentSession.pack} | ID: ${currentSession.id} | Configuration is locked. Drop intake files, run preflight, then start.`}
                        </div>
                      ) : isIdle ? (
                        <div className="field-hint" style={{ marginBottom: '0.75rem' }}>
                          {`Pack: ${currentSession.pack} | ID: ${currentSession.id} | Session idle — drop intake files and start a new run.`}
                        </div>
                      ) : null}
                      <div className="form-grid">
                        <div>
                          <label className="field-label">Repository Root</label>
                          <div className="row" style={{ gap: '0.5rem' }}>
                            <input
                              className="text-input"
                              style={{ flex: 1 }}
                              placeholder="/path/to/your/project"
                              value={setupDraft.repo_root}
                              disabled={draftExists}
                              onChange={(event) => setSetupDraft((draft) => ({ ...draft, repo_root: event.target.value }))}
                              onBlur={() => onResolveRepoRoot(setupDraft.repo_root)}
                              onKeyDown={(event) => { if (event.key === 'Enter') onResolveRepoRoot(setupDraft.repo_root); }}
                            />
                            <button
                              type="button"
                              className="secondary-button"
                              disabled={draftExists || isBusy}
                              onClick={onBrowseRepoRoot}
                            >Browse</button>
                          </div>
                          {repoRootInfo && repoRootInfo.exists && repoRootInfo.is_git ? (
                            <div className="field-hint" style={{ color: repoRootInfo.on_protected_branch ? '#f59e0b' : '#10b981' }}>
                              {repoRootInfo.on_protected_branch
                                ? `\u26a0 Git repository on branch ${repoRootInfo.branch} (protected \u2014 use a feature branch)`
                                : `\u2713 Git repository on branch ${repoRootInfo.branch}`}
                            </div>
                          ) : repoRootInfo && repoRootInfo.exists && !repoRootInfo.is_git ? (
                            <div className="field-hint" style={{ color: '#ef4444' }}>
                              Directory exists but is not a git repository
                            </div>
                          ) : repoRootInfo && !repoRootInfo.exists ? (
                            <div className="field-hint" style={{ color: '#ef4444' }}>
                              Directory does not exist
                            </div>
                          ) : null}
                          {draftExists && currentSession?.config?.environment?.COGNITIVE_SWITCHYARD_SOURCE_REPO ? (
                            <div className="field-hint" style={{ marginTop: '0.25rem' }}>
                              {`Session worktree: ${currentSession.config.environment.COGNITIVE_SWITCHYARD_REPO_ROOT}`}
                              <br />
                              {`Source repo: ${currentSession.config.environment.COGNITIVE_SWITCHYARD_SOURCE_REPO}`}
                            </div>
                          ) : null}
                        </div>
                        <div>
                          <label className="field-label">Project Directory</label>
                          <div className="row" style={{ gap: '0.5rem' }}>
                            <input
                              className="text-input"
                              style={{ flex: 1 }}
                              placeholder="e.g. cognitive_switchyard (optional — for monorepos)"
                              value={setupDraft.project_dir}
                              disabled={draftExists}
                              onChange={(event) => setSetupDraft((draft) => ({ ...draft, project_dir: event.target.value }))}
                            />
                            <button
                              type="button"
                              className="secondary-button"
                              disabled={draftExists || isBusy || !setupDraft.repo_root}
                              onClick={onBrowseProjectDir}
                            >Browse</button>
                          </div>
                          <div className="field-hint">
                            For monorepos, browse to the subdirectory so verification scopes to this project only.
                          </div>
                        </div>
                        {showBranchSelector ? (
                          <div>
                            <label className="field-label">Branch</label>
                            {showNewBranchInput ? (
                              <div className="row" style={{ gap: '0.5rem' }}>
                                <input
                                  className="text-input"
                                  style={{ flex: 1 }}
                                  placeholder="new-branch-name"
                                  value={newBranchName}
                                  disabled={draftExists || creatingBranch}
                                  onChange={(event) => setNewBranchName(event.target.value)}
                                />
                                <button
                                  type="button"
                                  className="secondary-button"
                                  disabled={draftExists || creatingBranch || !newBranchName.trim()}
                                  onClick={async () => {
                                    setCreatingBranch(true);
                                    try {
                                      await onCreateBranch(setupDraft.repo_root, newBranchName.trim(), repoRootInfo.branch || "main");
                                      setNewBranchName("");
                                    } catch {
                                    } finally {
                                      setCreatingBranch(false);
                                    }
                                  }}
                                >Create</button>
                                <button
                                  type="button"
                                  className="secondary-button"
                                  disabled={creatingBranch}
                                  onClick={() => {
                                    setSetupDraft((draft) => ({ ...draft, branch: repoRootInfo?.branch || repoBranches[0] || "" }));
                                    setNewBranchName("");
                                  }}
                                >Cancel</button>
                              </div>
                            ) : (
                              <select
                                className="select-input"
                                value={setupDraft.branch}
                                disabled={draftExists}
                                onChange={(event) => setSetupDraft((draft) => ({ ...draft, branch: event.target.value }))}
                              >
                                {repoBranches.map((b) => <option key={b} value={b}>{b}</option>)}
                                <option value="__new__">New Branch...</option>
                              </select>
                            )}
                          </div>
                        ) : null}
                        <div>
                          <label className="field-label">Pack</label>
                          <select
                            className="select-input"
                            value={setupDraft.pack}
                            disabled={draftExists}
                            onChange={(event) => setSetupDraft((draft) => ({ ...draft, pack: event.target.value }))}
                          >
                            {packs.map((pack) => <option key={pack.name} value={pack.name}>{pack.name}</option>)}
                          </select>
                          {selectedPack ? <div className="field-hint">{selectedPack.description}</div> : null}
                        </div>
                        <div>
                          <label className="field-label">Session Name</label>
                          <input
                            className="text-input"
                            value={setupDraft.name}
                            disabled={draftExists}
                            onChange={(event) => setSetupDraft((draft) => ({ ...draft, name: event.target.value }))}
                          />
                        </div>
                        <div>
                          <label className="field-label">Session ID</label>
                          <input
                            className="text-input"
                            value={setupDraft.id}
                            disabled={draftExists}
                            onChange={(event) => setSetupDraft((draft) => ({ ...draft, id: event.target.value }))}
                          />
                        </div>
                        <div className="row">
                          {packSupportsPlanning ? (
                            <div style={{ flex: 1 }}>
                              <label className="field-label">Planner Count</label>
                              <input
                                className="text-input"
                                type="number"
                                min="1"
                                max={selectedPack?.max_planners || 99}
                                disabled={draftExists}
                                value={setupDraft.planner_count}
                                onChange={(event) => setSetupDraft((draft) => ({ ...draft, planner_count: event.target.value }))}
                              />
                              {selectedPack?.max_planners && parseInt(setupDraft.planner_count, 10) > selectedPack.max_planners ? (
                                <div className="field-hint" style={{ color: '#f59e0b' }}>
                                  {`Pack limit: ${selectedPack.max_planners} — value will be clamped`}
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                          <div style={{ flex: 1 }}>
                            <label className="field-label">Worker Count</label>
                            <input
                              className="text-input"
                              type="number"
                              min="1"
                              max={selectedPack?.max_workers || 99}
                              disabled={draftExists}
                              value={setupDraft.worker_count}
                              onChange={(event) => setSetupDraft((draft) => ({ ...draft, worker_count: event.target.value }))}
                            />
                            {selectedPack?.max_workers && parseInt(setupDraft.worker_count, 10) > selectedPack.max_workers ? (
                              <div className="field-hint" style={{ color: '#f59e0b' }}>
                                {`Pack limit: ${selectedPack.max_workers} — value will be clamped`}
                              </div>
                            ) : null}
                          </div>
                          {packSupportsVerification ? (
                            <div style={{ flex: 1 }}>
                              <label className="field-label">Verification Interval</label>
                              <input
                                className="text-input"
                                type="number"
                                min="1"
                                disabled={draftExists}
                                value={setupDraft.verification_interval}
                                onChange={(event) => setSetupDraft((draft) => ({ ...draft, verification_interval: event.target.value }))}
                              />
                            </div>
                          ) : null}
                        </div>
                        <div>
                          <label className="field-label">Defaults</label>
                          <div className="field-hint">
                            {`pack=${settings?.default_pack || "n/a"} planners=${settings?.default_planners || 0} workers=${settings?.default_workers || 0} retention=${settings?.retention_days ?? 0}d`}
                          </div>
                        </div>
                        <div className="action-row">
                          <button type="button" className="secondary-button" onClick={() => setShowAdvanced((value) => !value)}>
                            {showAdvanced ? "Hide Advanced" : "Show Advanced"}
                          </button>
                          {canManageIntake ? (
                            <>
                              <button type="button" className="secondary-button" onClick={onOpenIntake}>
                                Open Intake
                              </button>
                              <button type="button" className="secondary-button" onClick={onOpenIntakeTerminal}>
                                Intake Terminal
                              </button>
                              <button type="button" className="secondary-button" onClick={onRefreshIntake}>
                                Refresh Intake
                              </button>
                              {draftExists ? (
                                <button type="button" className="secondary-button" disabled={isBusy} onClick={onRunPreflight}>
                                  {isBusy ? "Running Preflight..." : preflight ? "Re-run Preflight" : "Run Preflight"}
                                </button>
                              ) : null}
                            </>
                          ) : null}
                        </div>
                        {showAdvanced ? (
                          <div className="advanced-panel stack">
                            <div className="row">
                              <div style={{ flex: 1 }}>
                                <label className="field-label">Auto-Fix</label>
                                <select
                                  className="select-input"
                                  disabled={draftExists}
                                  value={setupDraft.auto_fix_enabled ? "enabled" : "disabled"}
                                  onChange={(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    auto_fix_enabled: event.target.value === "enabled"
                                  }))}
                                >
                                  <option value="enabled">Enabled</option>
                                  <option value="disabled">Disabled</option>
                                </select>
                              </div>
                              <div style={{ flex: 1 }}>
                                <label className="field-label">Auto-Fix Attempts</label>
                                <input
                                  className="text-input"
                                  type="number"
                                  min="1"
                                  disabled={draftExists}
                                  value={setupDraft.auto_fix_max_attempts}
                                  onChange={(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    auto_fix_max_attempts: event.target.value
                                  }))}
                                />
                              </div>
                              <div style={{ flex: 1 }}>
                                <label className="field-label">Poll Interval</label>
                                <input
                                  className="text-input"
                                  type="number"
                                  step="0.01"
                                  min="0.01"
                                  disabled={draftExists}
                                  value={setupDraft.poll_interval}
                                  onChange={(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    poll_interval: event.target.value
                                  }))}
                                />
                              </div>
                            </div>
                            <div className="row">
                              <div style={{ flex: 1 }}>
                                <label className="field-label">Task Idle Timeout (s)</label>
                                <input
                                  className="text-input"
                                  type="number"
                                  min="0"
                                  placeholder="pack default"
                                  disabled={draftExists}
                                  value={setupDraft.task_idle_timeout}
                                  onChange={(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    task_idle_timeout: event.target.value
                                  }))}
                                />
                              </div>
                              <div style={{ flex: 1 }}>
                                <label className="field-label">Task Max Timeout (s)</label>
                                <input
                                  className="text-input"
                                  type="number"
                                  min="0"
                                  placeholder="0 = no limit"
                                  disabled={draftExists}
                                  value={setupDraft.task_max_timeout}
                                  onChange={(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    task_max_timeout: event.target.value
                                  }))}
                                />
                              </div>
                              <div style={{ flex: 1 }}>
                                <label className="field-label">Session Max Timeout (s)</label>
                                <input
                                  className="text-input"
                                  type="number"
                                  min="0"
                                  placeholder="pack default"
                                  disabled={draftExists}
                                  value={setupDraft.session_max_timeout}
                                  onChange={(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    session_max_timeout: event.target.value
                                  }))}
                                />
                              </div>
                            </div>
                          </div>
                        ) : null}
                        <div>
                          <label className="field-label">Intake Directory</label>
                          <div className="field-hint" style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                            {currentSession
                              ? `${settings?.runtime_root || "~/.cognitive_switchyard"}/sessions/${currentSession.id}/intake/`
                              : "Create a draft session to materialize the intake directory."}
                          </div>
                          <div className="intake-list">
                            {intake?.locked ? (
                              <div className="field-hint">Session locked - intake closed.</div>
                            ) : null}
                            {files.length === 0 ? (
                              <div className="muted">Drop .md files into the intake directory to begin.</div>
                            ) : files.map((file) => (
                              <div key={file.path} className="intake-row">
                                <div className="stack" style={{ gap: "4px" }}>
                                  <div className="row" style={{ gap: "8px" }}>
                                    {icon("file-text", { width: 14, height: 14 })}
                                    <span className="mono">{file.filename}</span>
                                    {file.in_snapshot === false ? <span className="muted">Not in session</span> : null}
                                  </div>
                                  <div className="field-hint">{`${file.size} bytes | ${file.detected_at}`}</div>
                                </div>
                                {!intake?.locked ? (
                                  <button type="button" className="icon-button" onClick={() => onRevealFile(file.path)} aria-label={`Reveal ${file.filename}`}>
                                    {icon("folder-open", { width: 16, height: 16 })}
                                  </button>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        </div>
                        <div>
                          <label className="field-label">
                            Preflight Checks
                            {preflight ? (
                              <span className="status-badge" style={{ ...statusBadgeStyle(preflight.ok ? "done" : "blocked"), marginLeft: '8px', fontSize: 'var(--text-xs)' }}>
                                {preflight.ok ? "passed" : "failed"}
                              </span>
                            ) : null}
                          </label>
                          <div className="preflight-panel">
                            {!draftExists ? (
                              <div className="muted">Create a draft session to run preflight.</div>
                            ) : !preflight ? (
                              <div className="muted">Run preflight to validate pack scripts and prerequisites.</div>
                            ) : (
                              <div className="preflight-list">
                                <div className="preflight-row">
                                  <div className="row">
                                    <span className="status-dot" style={{ background: preflight.permission_report.ok ? "var(--status-done)" : "var(--status-blocked)" }} />
                                    <span>Script permissions</span>
                                  </div>
                                  <span>{preflight.permission_report.ok ? "ok" : "fix required"}</span>
                                </div>
                                {(preflight.permission_report.issues || []).map((issue) => (
                                  <div key={issue.relative_path} className="field-hint">{issue.fix_command}</div>
                                ))}
                                {(preflight.prerequisite_results?.results || []).map((result) => (
                                  <React.Fragment key={result.name}>
                                    <div className="preflight-row">
                                      <div className="row">
                                        <span className="status-dot" style={{ background: result.ok ? "var(--status-done)" : "var(--status-blocked)" }} />
                                        <span>{result.name}</span>
                                      </div>
                                      <span>{result.ok ? "ok" : `failed (exit ${result.exit_code})`}</span>
                                    </div>
                                    {!result.ok && (result.stderr || result.stdout) ? (
                                      <pre className="preflight-output">{(result.stderr || result.stdout).trim()}</pre>
                                    ) : null}
                                  </React.Fragment>
                                ))}
                                {preflight.preflight_result ? (
                                  <React.Fragment>
                                    <div className="preflight-row">
                                      <div className="row">
                                        <span className="status-dot" style={{ background: preflight.preflight_result.ok ? "var(--status-done)" : "var(--status-blocked)" }} />
                                        <span>Pack preflight hook</span>
                                      </div>
                                      <span>{preflight.preflight_result.ok ? "ok" : `failed (exit ${preflight.preflight_result.exit_code})`}</span>
                                    </div>
                                    {!preflight.preflight_result.ok && (preflight.preflight_result.stderr || preflight.preflight_result.stdout) ? (
                                      <pre className="preflight-output">{(preflight.preflight_result.stderr || preflight.preflight_result.stdout).trim()}</pre>
                                    ) : null}
                                  </React.Fragment>
                                ) : null}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="action-row">
                          {isIdle ? (
                            <button type="button" className="action-button" onClick={onNewRun} disabled={isBusy}>
                              New Run
                            </button>
                          ) : !draftExists ? (
                            <button type="button" className="action-button" onClick={onCreateDraft} disabled={isBusy || !setupDraft.pack}>
                              Create Session
                            </button>
                          ) : (
                            <button type="button" className="action-button" onClick={onStartSession} disabled={isBusy || !canStart}>
                              Start Session
                            </button>
                          )}
                        </div>
                      </div>
                    </section>
                  </div>
                );
              }

              function HealthSummaryBar({ tasks, workers }) {
                const [tick, setTick] = React.useState(0);

                const activeWorkers = (workers || []).filter(w => w.status === "active");
                React.useEffect(() => {
                  if (activeWorkers.length === 0) return;
                  const id = setInterval(() => setTick(t => t + 1), 1000);
                  return () => clearInterval(id);
                }, [activeWorkers.length]);

                const counts = { done: 0, active: 0, ready: 0, blocked: 0 };
                (tasks || []).forEach(t => {
                  if (counts[t.status] !== undefined) counts[t.status]++;
                });

                const maxElapsed = activeWorkers.reduce((m, w) => Math.max(m, w.elapsed || 0), 0) + tick;

                const doneTasks = (tasks || []).filter(t => t.completed_at).sort((a, b) => b.completed_at.localeCompare(a.completed_at));
                const lastCompletion = doneTasks.length ? doneTasks[0].completed_at.slice(11, 19) : null;

                const parts = [];
                if (counts.done) parts.push(`${counts.done} done`);
                if (counts.active) parts.push(`${counts.active} active (${formatElapsed(maxElapsed)})`);
                if (counts.ready) parts.push(`${counts.ready} ready`);
                if (counts.blocked) parts.push(`${counts.blocked} blocked`);
                if (lastCompletion) parts.push(`Last completion: ${lastCompletion}`);

                if (parts.length === 0) return null;

                return (
                  <div className="health-summary mono" style={{
                    fontSize: 'var(--text-xs)',
                    color: 'var(--text-secondary)',
                    padding: '4px 12px',
                    display: 'flex',
                    gap: '12px',
                    flexWrap: 'wrap',
                  }}>
                    {parts.join(" — ")}
                  </div>
                );
              }

              function TaskRowElapsed({ task }) {
                const [now, setNow] = React.useState(Date.now());
                React.useEffect(() => {
                  if (task.status !== "active" || !task.started_at) return;
                  const id = setInterval(() => setNow(Date.now()), 1000);
                  return () => clearInterval(id);
                }, [task.status, task.started_at]);

                if (!task.started_at) return <span className="mono muted">{formatElapsed(0)}</span>;

                const seconds = task.status === "active"
                  ? Math.floor((now - new Date(task.started_at).getTime()) / 1000)
                  : (task.elapsed || 0);

                return <span className="mono muted">{formatElapsed(seconds)}</span>;
              }

              function LastActivityIndicator({ worker }) {
                const [tick, setTick] = React.useState(0);
                const snapshotRef = React.useRef(worker.last_activity_ago || 0);

                React.useEffect(() => {
                  snapshotRef.current = worker.last_activity_ago || 0;
                  setTick(0);
                }, [worker.last_activity_ago]);

                React.useEffect(() => {
                  if (worker.status !== "active") return;
                  const id = setInterval(() => setTick(t => t + 1), 1000);
                  return () => clearInterval(id);
                }, [worker.status]);

                if (worker.status !== "active" || worker.last_activity_ago == null) return null;

                const ago = snapshotRef.current + tick;
                const limit = worker.task_idle_limit;
                const thirdLow  = (limit > 0) ? limit / 3       : 120;
                const thirdHigh = (limit > 0) ? (limit * 2) / 3  : 600;

                let color, style;
                if (ago < thirdLow) {
                  color = "var(--status-done)";
                  style = { fontSize: 'var(--text-xs)', color, opacity: 0.7 };
                } else if (ago < thirdHigh) {
                  color = "var(--status-review)";
                  style = { fontSize: 'var(--text-xs)', color, animation: 'pulse-idle-amber 3s ease-in-out infinite' };
                } else {
                  color = "var(--status-blocked)";
                  style = { fontSize: 'var(--text-xs)', color, animation: 'pulse-idle-red 1.5s ease-in-out infinite', fontWeight: 600 };
                }

                return (
                  <span className="mono" style={style}>
                    {`idle: ${formatElapsed(ago)}`}
                  </span>
                );
              }

              function ElapsedField({ task }) {
                const [now, setNow] = React.useState(Date.now());

                React.useEffect(() => {
                  if (task.status !== "active" || !task.started_at) return;
                  const id = setInterval(() => setNow(Date.now()), 1000);
                  return () => clearInterval(id);
                }, [task.status, task.started_at]);

                if (!task.started_at) return null;

                const label = task.status === "active" ? "Elapsed" : "Duration";
                const seconds = task.status === "active"
                  ? Math.floor((now - new Date(task.started_at).getTime()) / 1000)
                  : (task.elapsed || 0);

                return (
                  <div>
                    <div className="field-label">{label}</div>
                    <div className="metadata-value mono">{formatElapsed(seconds)}</div>
                  </div>
                );
              }

              function TaskDetailView({ task, currentSession, logLines, taskLogs, sessionStatus, runtimeState, searchValue, onSearchChange, onBack, onMoveTask, onRevealFile }) {
                const logPanelRef = useRef(null);
                const effectiveLogLines = useMemo(() => {
                  const baseLines = logLines || [];
                  if (!task) return baseLines;

                  const isAutoFix = sessionStatus === "auto_fixing";
                  const isVerifying = sessionStatus === "verifying";
                  const isTargetTask = runtimeState?.auto_fix_task_id === task.task_id;

                  if (!isTargetTask || (!isAutoFix && !isVerifying)) {
                    return baseLines;
                  }

                  const phaseKey = isAutoFix ? "__phase_auto_fix__" : "__phase_verification__";
                  const phaseLines = (taskLogs || {})[phaseKey] || [];
                  if (phaseLines.length === 0) return baseLines;

                  const separator = isAutoFix
                    ? "─── Auto-fix output ───"
                    : "─── Verification output ───";
                  return [...baseLines, { line: "", ts: null }, { line: separator, ts: null }, ...phaseLines];
                }, [logLines, task, sessionStatus, runtimeState, taskLogs]);
                const emptyLogMessage = useMemo(() => {
                  if (!task) {
                    return "Waiting for live log subscription...";
                  }
                  if (task.history_source === "summary") {
                    return "Task logs were not retained for this completed session.";
                  }
                  if (task.status === "active") {
                    return "Waiting for live log subscription...";
                  }
                  if (task.status === "done" || task.status === "blocked") {
                    return "No retained log found for this task.";
                  }
                  return "No log yet. Logs appear after the task starts.";
                }, [task]);

                useEffect(() => {
                  if (logPanelRef.current) {
                    logPanelRef.current.scrollTop = logPanelRef.current.scrollHeight;
                  }
                }, [effectiveLogLines.length]);

                return (
                  <div className="split-view">
                    <aside className="detail-panel">
                      <button type="button" className="secondary-button" onClick={onBack}>
                        {icon("arrow-left", { width: 16, height: 16 })} Back to Monitor
                      </button>
                      {task ? (
                        <div>
                          <h1 className="mono" style={{ fontSize: "var(--text-xl)", marginBottom: "8px" }}>{task.task_id}</h1>
                          <div className="secondary">{task.title}</div>
                          <div style={{ marginTop: "16px" }}>
                            <span className="status-badge" style={statusBadgeStyle(task.status)}>{task.status}</span>
                            {task.full_test_after ? (
                              <span title="Full test after completion" style={{
                                fontSize: 'var(--text-xs)',
                                color: 'var(--status-active)',
                                fontWeight: 600,
                                padding: '0 4px',
                                background: 'rgba(245, 158, 11, 0.15)',
                                borderRadius: '3px',
                                marginLeft: '8px',
                              }}>FTA</span>
                            ) : null}
                          </div>
                          <div className="metadata-grid">
                            <div>
                              <div className="field-label">Session</div>
                              <div className="metadata-value mono">{currentSession?.name || "n/a"}</div>
                            </div>
                            <div>
                              <div className="field-label">Worker Slot</div>
                              <div className="metadata-value mono">{task.worker_slot ?? "n/a"}</div>
                            </div>
                            <div>
                              <div className="field-label">Plan Path</div>
                              <div className="metadata-value mono">{task.plan_path}</div>
                            </div>
                            <div>
                              <div className="field-label">Created</div>
                              <div className="metadata-value mono">{task.created_at || "n/a"}</div>
                            </div>
                            {task.started_at ? (
                              <div>
                                <div className="field-label">Started</div>
                                <div className="metadata-value mono" title={task.started_at}>{task.started_at.slice(11, 19)}</div>
                              </div>
                            ) : null}
                            <ElapsedField task={task} />
                            {task.completed_at ? (
                              <div>
                                <div className="field-label">Completed</div>
                                <div className="metadata-value mono" title={task.completed_at}>{task.completed_at.slice(11, 19)}</div>
                              </div>
                            ) : null}
                            <div>
                              <div className="field-label">Constraints</div>
                              <div className="constraint-list">
                                <div className="metadata-value mono">{`DEPENDS_ON: ${(task.depends_on || []).join(", ") || "none"}`}</div>
                                <div className="metadata-value mono">{`ANTI_AFFINITY: ${(task.anti_affinity || []).join(", ") || "none"}`}</div>
                                <div className="metadata-value mono">{`FULL_TEST_AFTER: ${task.full_test_after ? "yes" : "no"}`}</div>
                              </div>
                            </div>
                          </div>
                          {(() => {
                            const actions = TASK_TRANSITIONS[task.status];
                            if (!actions || actions.length === 0) return null;
                            return (
                              <div style={{ marginTop: '16px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                {actions.map(({ target, label, icon: iconName }) => (
                                  <button
                                    key={target}
                                    type="button"
                                    className="secondary-button"
                                    onClick={async (e) => {
                                      e.stopPropagation();
                                      await onMoveTask(task.task_id, target);
                                      if (target === "intake") {
                                        onBack();
                                      }
                                    }}
                                  >
                                    {icon(iconName, { width: 14, height: 14 })} {label}
                                  </button>
                                ))}
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() => onRevealFile(task.plan_path)}
                                  title="Open plan file in Finder/editor"
                                >
                                  {icon("file-text", { width: 14, height: 14 })} Reveal File
                                </button>
                              </div>
                            );
                          })()}
                        </div>
                      ) : (
                        <div className="empty-state">Select a task from the monitor.</div>
                      )}
                    </aside>
                    <section className="log-panel" ref={logPanelRef}>
                      <div style={{ position: "sticky", top: 0, background: "rgba(10, 12, 16, 0.96)", paddingBottom: "12px" }}>
                        <input
                          className="search-input"
                          placeholder="Search log output"
                          value={searchValue}
                          onChange={(event) => onSearchChange(event.target.value)}
                        />
                      </div>
                      {(effectiveLogLines.length ? effectiveLogLines : [{ line: emptyLogMessage, ts: null }]).map((entry, index) => (
                        <div
                          key={`${index}-${entry.line}`}
                          className={`log-line ${entry.line.startsWith("───") ? "separator" : isProgressLine(entry.line) ? "progress" : isProblemLine(entry.line) ? "error" : ""}`}
                        >
                          {entry.ts ? <span className="muted" style={{ marginRight: '8px' }}>{entry.ts.slice(11, 19)}</span> : null}
                          {entry.line}
                        </div>
                      ))}
                    </section>
                  </div>
                );
              }

              function DagView({ dag, onBack, onOpenTask }) {
                const ReactFlowComponent = ReactFlowLib?.default;
                const ReactFlowProvider = ReactFlowLib?.ReactFlowProvider;
                const MiniMap = ReactFlowLib?.MiniMap;
                const Controls = ReactFlowLib?.Controls;
                const Background = ReactFlowLib?.Background;

                const tasks = dag?.tasks || [];
                const groups = dag?.groups || [];

                // Topological layout: compute depth per node from dependencies
                const nodeWidth = 180;
                const nodeHeight = 80;
                const colGap = 260;
                const rowGap = 120;
                const padding = 40;

                const depthMap = useMemo(() => {
                  const depths = {};
                  const taskIds = new Set(tasks.map((t) => t.task_id));
                  function computeDepth(taskId, visited) {
                    if (depths[taskId] !== undefined) return depths[taskId];
                    if (visited.has(taskId)) return 0;
                    visited.add(taskId);
                    const task = tasks.find((t) => t.task_id === taskId);
                    if (!task) return 0;
                    const parentDepths = (task.depends_on || [])
                      .filter((dep) => taskIds.has(dep))
                      .map((dep) => computeDepth(dep, visited));
                    depths[taskId] = parentDepths.length > 0 ? Math.max(...parentDepths) + 1 : 0;
                    return depths[taskId];
                  }
                  tasks.forEach((t) => computeDepth(t.task_id, new Set()));
                  return depths;
                }, [tasks]);

                // Group tasks by depth column, then assign y positions
                const positions = useMemo(() => {
                  const columns = {};
                  tasks.forEach((task) => {
                    const col = depthMap[task.task_id] || 0;
                    if (!columns[col]) columns[col] = [];
                    columns[col].push(task.task_id);
                  });
                  const pos = {};
                  Object.entries(columns).forEach(([col, ids]) => {
                    const c = parseInt(col, 10);
                    ids.forEach((id, row) => {
                      pos[id] = { x: padding + c * colGap, y: padding + row * rowGap };
                    });
                  });
                  return pos;
                }, [tasks, depthMap]);

                // Anti-affinity group background nodes
                const groupColors = [
                  "rgba(167, 139, 250, 0.08)", // purple
                  "rgba(59, 130, 246, 0.08)",   // blue
                  "rgba(245, 158, 11, 0.08)",   // amber
                  "rgba(52, 211, 153, 0.08)",   // green
                  "rgba(239, 68, 68, 0.08)",    // red
                ];
                const groupBorderColors = [
                  "rgba(167, 139, 250, 0.25)",
                  "rgba(59, 130, 246, 0.25)",
                  "rgba(245, 158, 11, 0.25)",
                  "rgba(52, 211, 153, 0.25)",
                  "rgba(239, 68, 68, 0.25)",
                ];

                const groupNodes = useMemo(() => {
                  return groups.map((group, gi) => {
                    const memberPositions = (group.members || [])
                      .filter((m) => positions[m])
                      .map((m) => positions[m]);
                    if (memberPositions.length === 0) return null;
                    const groupPad = 24;
                    const minX = Math.min(...memberPositions.map((p) => p.x)) - groupPad;
                    const minY = Math.min(...memberPositions.map((p) => p.y)) - groupPad - 28;
                    const maxX = Math.max(...memberPositions.map((p) => p.x)) + nodeWidth + groupPad;
                    const maxY = Math.max(...memberPositions.map((p) => p.y)) + nodeHeight + groupPad;
                    return {
                      id: `group-${group.name}`,
                      type: "group",
                      position: { x: minX, y: minY },
                      data: { label: group.name },
                      style: {
                        width: maxX - minX,
                        height: maxY - minY,
                        background: groupColors[gi % groupColors.length],
                        border: `1px dashed ${groupBorderColors[gi % groupBorderColors.length]}`,
                        borderRadius: "var(--radius-xl)",
                        padding: 0,
                        zIndex: -1,
                      },
                      selectable: false,
                      draggable: false,
                    };
                  }).filter(Boolean);
                }, [groups, positions]);

                // Group label nodes (React Flow group type doesn't render labels)
                const groupLabelNodes = useMemo(() => {
                  return groupNodes.map((gn) => ({
                    id: `${gn.id}-label`,
                    position: { x: gn.position.x + 12, y: gn.position.y + 6 },
                    data: {
                      label: (
                        <div style={{
                          fontSize: "var(--text-xs)",
                          color: "var(--text-muted)",
                          fontFamily: "var(--font-mono)",
                          letterSpacing: "0.05em",
                          textTransform: "uppercase",
                          pointerEvents: "none",
                        }}>{gn.data.label}</div>
                      )
                    },
                    style: {
                      background: "transparent",
                      border: "none",
                      padding: 0,
                      width: "auto",
                      boxShadow: "none",
                    },
                    selectable: false,
                    draggable: false,
                  }));
                }, [groupNodes]);

                const graphNodes = tasks.map((task) => ({
                  id: task.task_id,
                  position: positions[task.task_id] || { x: 0, y: 0 },
                  data: {
                    label: (
                      <div>
                        <div className="mono">{task.task_id}</div>
                        <div className="secondary">{task.title || "Task"}</div>
                        <div className="status-badge" style={statusBadgeStyle(task.status || "ready")}>
                          {task.status || "ready"}
                        </div>
                      </div>
                    )
                  },
                  style: {
                    width: nodeWidth,
                    minHeight: 60,
                    background: "var(--bg-surface)",
                    border: `2px solid ${STATUS_COLORS[task.status || "ready"] || "var(--status-ready)"}`,
                    borderRadius: "var(--radius-lg)",
                    color: "var(--text-primary)"
                  }
                }));
                const dependsEdges = tasks.flatMap((task) => (
                  (task.depends_on || []).map((dependency) => ({
                    id: `${dependency}-${task.task_id}`,
                    source: dependency,
                    target: task.task_id,
                    animated: true,
                    markerEnd: { type: "arrowclosed" },
                    style: { stroke: "var(--text-muted)", strokeWidth: 2 }
                  }))
                ));
                const antiAffinityEdges = tasks.flatMap((task) => (
                  (task.anti_affinity || []).map((peer) => ({
                    id: `${task.task_id}-${peer}-anti-affinity`,
                    source: task.task_id,
                    target: peer,
                    animated: false,
                    style: { stroke: "var(--status-staged)", strokeWidth: 1, strokeDasharray: "6 4" }
                  }))
                ));
                const allNodes = [...groupNodes, ...groupLabelNodes, ...graphNodes];
                return (
                  <div className="dag-shell">
                    <div className="page">
                      <button type="button" className="secondary-button" onClick={onBack}>
                        {icon("arrow-left", { width: 16, height: 16 })} Back to Monitor
                      </button>
                    </div>
                    {ReactFlowComponent && ReactFlowProvider && dag ? (
                      <div className="dag-canvas">
                        <ReactFlowProvider>
                          <ReactFlowComponent
                            fitView
                            nodes={allNodes}
                            edges={[...dependsEdges, ...antiAffinityEdges]}
                            onNodeDoubleClick={(_, node) => {
                              if (!node.id.startsWith("group-")) onOpenTask(node.id);
                            }}
                          >
                            <MiniMap />
                            <Controls />
                            <Background color="transparent" />
                          </ReactFlowComponent>
                        </ReactFlowProvider>
                      </div>
                    ) : (
                      <div className="empty-state">DAG data will appear here once a session has a graph.</div>
                    )}
                  </div>
                );
              }

              function HistoryView({ sessions, settings, selectedSession, selectedTasks, onOpenSession, onOpenSettings, onPurgeSession, onPurgeAll }) {
                const completed = sessions.filter((session) => session.status === "completed" || session.status === "aborted");
                return (
                  <main className="page">
                    <div className="row" style={{ justifyContent: "space-between", marginBottom: "24px" }}>
                      <h1 style={{ margin: 0, fontFamily: "var(--font-display)", fontSize: "var(--text-xl)" }}>Session History</h1>
                      <div className="action-row">
                        <button type="button" className="secondary-button" onClick={onOpenSettings}>
                          Retention
                        </button>
                        <button type="button" className="danger-button" onClick={onPurgeAll}>
                          Purge All
                        </button>
                      </div>
                    </div>
                    <section className="history-list">
                      {completed.length === 0 ? (
                        <div className="empty-state">
                          {icon("inbox", { width: 32, height: 32 })}
                          <div>No sessions yet</div>
                        </div>
                      ) : completed.map((session) => (
                        <article key={session.id} className="session-card">
                          <div className="session-card-header">
                            <div onClick={() => onOpenSession(session)} style={{ cursor: "pointer", flex: 1 }}>
                              <div style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>{session.name}</div>
                              <div className="secondary mono">{session.pack}</div>
                              <div className="secondary mono" style={{ marginTop: "12px" }}>
                                {`${session.created_at} -> ${session.completed_at || "in progress"}`}
                              </div>
                            </div>
                            <div className="stack" style={{ justifyItems: "end" }}>
                              <span className="status-badge" style={statusBadgeStyle(session.status)}>{session.status}</span>
                              <button type="button" className="icon-button" onClick={() => onPurgeSession(session.id)} aria-label={`Purge ${session.name}`}>
                                {icon("trash-2", { width: 16, height: 16 })}
                              </button>
                            </div>
                          </div>
                        </article>
                      ))}
                    </section>
                    {selectedSession ? (
                      <section className="setup-card" style={{ marginTop: "24px" }}>
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                          <div>
                            <h2 style={{ margin: 0, fontFamily: "var(--font-display)", fontSize: "var(--text-lg)" }}>{selectedSession.name}</h2>
                            <div className="secondary mono">{selectedSession.pack}</div>
                          </div>
                          <span className="status-badge" style={statusBadgeStyle(selectedSession.status)}>{selectedSession.status}</span>
                        </div>
                        <div className="secondary mono" style={{ marginTop: "12px" }}>
                          {`${selectedSession.started_at || selectedSession.created_at} -> ${selectedSession.completed_at || "in progress"}`}
                        </div>
                        {selectedSession?.release_notes?.content ? (
                          <section className="section-card" style={{ marginTop: "20px", padding: "16px" }}>
                            <div style={{ fontFamily: "var(--font-display)", fontSize: "var(--text-md)", fontWeight: 700, marginBottom: "12px" }}>
                              Release Notes
                            </div>
                            <pre className="log-panel" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                              {selectedSession.release_notes.content}
                            </pre>
                          </section>
                        ) : null}
                        <div className="stack" style={{ marginTop: "20px", gap: "12px" }}>
                          {(selectedTasks || []).map((task) => (
                            <div key={task.task_id} className="session-card">
                              <div className="session-card-header">
                                <div>
                                  <div style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>{task.title}</div>
                                  <div className="secondary mono">{task.task_id}</div>
                                </div>
                                <span className="status-badge" style={statusBadgeStyle(task.status)}>{task.status}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </section>
                    ) : null}
                    <div className="retention-line">
                      {`Auto-purge: ${settings?.retention_days ? `sessions older than ${settings.retention_days} days` : "disabled"}`}
                    </div>
                  </main>
                );
              }

              function SettingsView({ settingsDraft, setSettingsDraft, packs, onSave }) {
                return (
                  <main className="page">
                    <section className="setup-card" style={{ margin: "0 auto" }}>
                      <h1 style={{ fontFamily: "var(--font-display)", fontSize: "var(--text-xl)", marginTop: 0 }}>Settings</h1>
                      <div className="settings-grid">
                        <div>
                          <label className="field-label">Session Retention (days)</label>
                          <input
                            className="text-input"
                            type="number"
                            value={settingsDraft.retention_days}
                            onChange={(event) => setSettingsDraft((draft) => ({ ...draft, retention_days: Number(event.target.value) }))}
                          />
                        </div>
                        <div className="row">
                          <div style={{ flex: 1 }}>
                            <label className="field-label">Default Planner Count</label>
                            <input
                              className="text-input"
                              type="number"
                              value={settingsDraft.default_planners}
                              onChange={(event) => setSettingsDraft((draft) => ({ ...draft, default_planners: Number(event.target.value) }))}
                            />
                          </div>
                          <div style={{ flex: 1 }}>
                            <label className="field-label">Default Worker Count</label>
                            <input
                              className="text-input"
                              type="number"
                              value={settingsDraft.default_workers}
                              onChange={(event) => setSettingsDraft((draft) => ({ ...draft, default_workers: Number(event.target.value) }))}
                            />
                          </div>
                        </div>
                        <div>
                          <label className="field-label">Default Pack</label>
                          <select
                            className="select-input"
                            value={settingsDraft.default_pack}
                            onChange={(event) => setSettingsDraft((draft) => ({ ...draft, default_pack: event.target.value }))}
                          >
                            {packs.map((pack) => <option key={pack.name} value={pack.name}>{pack.name}</option>)}
                          </select>
                        </div>
                        <div>
                          <label className="field-label">Terminal Application</label>
                          <input
                            className="text-input"
                            list="terminal-options"
                            value={settingsDraft.terminal_app || ""}
                            onChange={(event) => setSettingsDraft((draft) => ({ ...draft, terminal_app: event.target.value }))}
                            placeholder="e.g. iTerm, Terminal, Kitty"
                          />
                          <datalist id="terminal-options">
                            <option value="iTerm" />
                            <option value="Terminal" />
                            <option value="Wezterm" />
                            <option value="Kitty" />
                            <option value="Alacritty" />
                          </datalist>
                        </div>
                        <button type="button" className="action-button" onClick={onSave}>Save Settings</button>
                      </div>
                    </section>
                  </main>
                );
              }

              ReactDOM.createRoot(document.getElementById("switchyard-app")).render(<App />);
            </script>
          </body>
        </html>
        """
    )
    return (
        template
        .replace("__DESIGN_TOKENS_BLOCK__", DESIGN_TOKENS_BLOCK)
        .replace("__BOOTSTRAP_JSON__", _escape_json_for_inline_html(bootstrap))
    )


def _escape_json_for_inline_html(payload: dict[str, Any]) -> str:
    rendered = json.dumps(payload, sort_keys=True)
    return (
        rendered
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
