# jtree User Guide

A walkthrough for exploring, editing, and exporting JSON files with jtree's interactive node graph.

---

## 1. Getting Started

### Launch

```bash
# Open a JSON file directly
./jtree data.json

# Launch without a file (opens welcome screen)
./jtree

# Custom port
./jtree data.json --port 9000

# Read-only mode (disables all editing)
./jtree data.json --readonly
```

jtree starts a local web server and opens your browser automatically. The default port is **8100**.

### First-Time Setup

On first run, jtree creates a private virtual environment at `~/.jtree_venv` and installs its dependencies (FastAPI, uvicorn). This happens once — subsequent launches start instantly.

**Requirements:** Python 3.8+ and a modern web browser. An internet connection on first run for CDN resources (React, Tailwind, fonts).

### Welcome Screen

When launched without a file, jtree shows a welcome screen with a large **Open a JSON file** button. You can also pass a file path on the command line: `jtree <file.json>`.

---

## 2. The Interface

### Layout

The interface has four main areas:

| Area | Position | Purpose |
|------|----------|---------|
| **Toolbar** | Top | File operations, export, navigator toggle, search, theme toggle |
| **Breadcrumb bar** | Below toolbar | Clickable path showing your location in the JSON tree |
| **Canvas** | Center | Pannable, zoomable node graph |
| **Navigator sidebar** | Left (toggle) | Tree-of-contents for quick navigation |
| **Minimap** | Bottom-right | Scaled overview with click-to-navigate |

### File Path Display

The toolbar shows the full file path of the loaded file. Click the copy button next to it to copy the path to your clipboard.

### Dark / Light Mode

Click the sun/moon icon in the top-right corner to switch themes. jtree defaults to dark mode on first visit. Your preference is saved to localStorage and persists across sessions.

- **Dark mode:** Navy blueprint background with cyan accents and grid lines
- **Light mode:** Light blue-gray background with blue accents and grid lines

---

## 3. The Node Graph

### Layout

JSON is rendered as a horizontal tree: the root node sits on the left, and children expand rightward. Each node is a card showing its key, type badge, and value.

### Type Color Coding

Every JSON type has a distinct border color and badge:

| Type | Color | Badge |
|------|-------|-------|
| **Object** | Cyan | `object` |
| **Array** | Purple | `array` |
| **String** | Green | `string` |
| **Number** | Orange | `number` |
| **Boolean** | Red | `boolean` |
| **Null** | Blue-gray | `null` |

Each node has a 4px left border in its type color for quick visual scanning.

### Expanding and Collapsing

- **Click** a container node (object or array) to toggle it open or closed
- **Collapsed nodes** show summaries like `{5 keys}` or `[3 items]`
- **Containment lanes** — dashed borders visually group expanded children by depth

### Pan and Zoom

| Action | How |
|--------|-----|
| **Pan** | Click and drag on the canvas background |
| **Zoom** | Ctrl/Cmd + scroll wheel (range: 10%–300%) |

A zoom level indicator appears in the bottom-left corner (e.g., "150%").

### Selection

Click any node to select it. The selected node gets a blue outline. Many operations (copy, paste, context menu) act on the selected node.

---

## 4. Navigation

### Breadcrumb Bar

A clickable path bar runs below the toolbar, showing your current location (e.g., `root > users > [0] > address`). Click any segment to pan the canvas to that node.

### Navigator Sidebar

Toggle with **Ctrl/Cmd+B** or the toolbar button.

| State | Appearance |
|-------|------------|
| **Open** | 280px wide scrollable tree view |
| **Collapsed** | Thin 28px rail with expand icon (always visible for discoverability) |

The sidebar shows **only container nodes** (objects and arrays) with disclosure triangles. Leaf nodes are hidden to keep the tree compact.

**Interactions:**
- Click a disclosure triangle to expand/collapse a subtree in the sidebar
- Click a node name to pan the canvas to that node (smooth animation)
- The sidebar auto-reveals ancestors and scrolls to keep the active node visible as you navigate

**Visual indicators:**
- Cyan dots for objects, purple dots for arrays
- Item counts shown as `{5}` or `[3]`
- Active node highlighted with a tinted background

### Minimap

A 200x150px scaled overview in the bottom-right corner shows all visible nodes as small rectangles. A blue rectangle indicates the current viewport.

| Action | How |
|--------|-----|
| **Jump** | Click anywhere on the minimap |
| **Pan** | Drag the blue viewport rectangle |

### Search

Open with **Ctrl/Cmd+F** or the search button in the toolbar.

**Features:**
- Search across keys, values, or both (three filter tabs: **Both**, **Key**, **Value**)
- Results appear in real time with a 300ms debounce
- Up to 100 matches displayed
- Each result shows the full path (cyan for key matches, green for value matches)
- Click any result to navigate the canvas to that node
- Close with **Escape** or the X button

---

## 5. File Operations

### Open

Press **Ctrl/Cmd+O** or click the **Open** button in the toolbar.

Two methods:
1. **Browser file picker** — Click "Choose file..." to select a `.json` file from your system
2. **Server path** — Click "Enter a server path instead" and type a file path (supports `~` expansion)

### Save

Press **Ctrl/Cmd+S** or click the **Save** button.

- If the file was opened from a path, it saves directly to that path
- If no path exists (e.g., opened via browser picker), the Save As dialog opens

### Save As

Two methods:
1. **Browser save** — Click "Choose location..." to use the browser file picker
2. **Server path** — Click "or save to a server path" and type a destination path (supports `~` expansion)

---

## 6. Editing

All editing operations are disabled in `--readonly` mode. Each edit is recorded in a 50-operation undo stack.

### Edit Values

**Double-click** any leaf node, or right-click and choose **Edit Value**.

| Type | Editor |
|------|--------|
| **String** | Text input |
| **Number** | Number input with validation |
| **Boolean** | True/False toggle buttons |
| **Null** | Read-only display ("Value is null") |

Press **Enter** or click **Save** to confirm. Press **Escape** or click **Cancel** to discard.

### Add Child

Right-click a container node (object or array) and choose **Add Child**.

- **Objects:** Enter a key name, choose a type (string, number, boolean, null, object, array), and optionally set a value
- **Arrays:** Choose a type and optionally set a value (no key needed)

The parent automatically expands after adding.

### Delete

Right-click a non-root node and choose **Delete**. A confirmation dialog appears, showing the path and a warning with the descendant count if the node has children. The root node cannot be deleted.

### Rename Key

Right-click an object key and choose **Rename Key**. Enter the new key name in the modal. Not available for array items (use reordering instead).

### Copy and Paste

| Action | Shortcut | Behavior |
|--------|----------|----------|
| **Copy** | Ctrl/Cmd+C | Copies the selected node (and its entire subtree) to an in-memory clipboard |
| **Paste** | Ctrl/Cmd+V | Pastes into the selected container node |

- **Objects:** Auto-generates unique keys for duplicates (`key_copy1`, `key_copy2`, etc.)
- **Arrays:** Appends to the end
- The clipboard survives file switches, enabling cross-file copy/paste workflows
- Paste is grayed out if the clipboard is empty or the selected node is not a container

### Array Reordering

Right-click an array item to access:

| Option | Description |
|--------|-------------|
| **Move Up** | Move one position earlier (grayed out if already first) |
| **Move Down** | Move one position later (grayed out if already last) |
| **Move to Position...** | Enter a specific 0-based index |

### Undo / Redo

| Action | Shortcut |
|--------|----------|
| **Undo** | Ctrl/Cmd+Z |
| **Redo** | Ctrl/Cmd+Shift+Z or Ctrl+Y |

The undo stack holds up to 50 operations.

---

## 7. Context Menu

Right-click any node to open the context menu. Available options depend on the node type:

### Container Nodes (Objects & Arrays)

| Option | Description |
|--------|-------------|
| **Expand / Collapse** | Toggle expansion state |
| **Expand All** | Recursively expand all descendants |
| **Collapse All** | Recursively collapse all descendants |
| **Add Child** | Add a new child node |
| **Copy Node** | Copy entire subtree to clipboard |
| **Paste** | Paste from clipboard |
| **Copy Path** | Copy the JSONPath to clipboard |

### Leaf Nodes

| Option | Description |
|--------|-------------|
| **Edit Value** | Edit the scalar value |
| **Copy Node** | Copy to clipboard |
| **Copy Value** | Copy the scalar value to clipboard |
| **Copy Path** | Copy the JSONPath to clipboard |

### Array Items (additional)

| Option | Description |
|--------|-------------|
| **Move Up** | Move one position earlier |
| **Move Down** | Move one position later |
| **Move to Position...** | Specify a new index |

### Object Keys (additional)

| Option | Description |
|--------|-------------|
| **Rename Key** | Change the object key name |

### All Non-Root Nodes

| Option | Description |
|--------|-------------|
| **Delete** | Remove the node (with confirmation) |

In readonly mode, all editing options are hidden. View and navigation options remain available.

---

## 8. Export

Click the **Export** button in the toolbar to open a dropdown with three formats:

| Format | Description |
|--------|-------------|
| **SVG** | Vector export preserving all styling — ideal for documentation and scaling |
| **PNG** | Raster image at 2x resolution (rendered from SVG) |
| **JPEG** | Raster image at 2x resolution, 92% quality |

All exports capture the current visible graph (expanded nodes, lanes, edges, and styling). The file downloads to your browser's download folder.

---

## 9. Performance

- Full JSON is loaded in memory server-side; the frontend fetches slices on demand
- Handles files up to **50 MB**
- Large arrays are paginated at **50 items** per expansion
- Only expanded nodes are rendered — collapsed subtrees have zero rendering cost
- Lazy loading: children are fetched from the server only when a node is expanded

---

## 10. Quick Reference

### CLI Flags

```
./jtree [file.json] [--port PORT] [--readonly]
```

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `file.json` | — | *(none)* | JSON file to open (optional) |
| `--port` | `-p` | 8100 | Server port |
| `--readonly` | — | off | Disable all editing |

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Ctrl/Cmd+O** | Open file |
| **Ctrl/Cmd+S** | Save |
| **Ctrl/Cmd+Z** | Undo |
| **Ctrl/Cmd+Shift+Z** (or Ctrl+Y) | Redo |
| **Ctrl/Cmd+C** | Copy node |
| **Ctrl/Cmd+V** | Paste node |
| **Ctrl/Cmd+B** | Toggle navigator sidebar |
| **Ctrl/Cmd+F** | Toggle search |
| **Escape** | Close modal / search / context menu |

### Color Legend

**Node Types:**

| Type | Border / Badge Color |
|------|---------------------|
| Object | Cyan |
| Array | Purple |
| String | Green |
| Number | Orange |
| Boolean | Red |
| Null | Blue-gray |

**Interface:**

| Element | Color | Meaning |
|---------|-------|---------|
| Blue outline | Blue | Selected node |
| Dashed border | Semi-transparent | Containment lane (depth grouping) |
| Cyan path segment | Cyan | Key match in search results |
| Green path segment | Green | Value match in search results |
