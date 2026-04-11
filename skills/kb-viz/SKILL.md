---
name: kb-viz
version: 0.1.0
description: |
  Generate matplotlib charts and diagrams from wiki data. Reads wiki articles,
  extracts data or relationships, creates visualizations, and saves to outputs/images/.
  Viewable in Obsidian as embedded images.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
trigger: /kb-viz
---

# /kb-viz — Generate Visualizations

Generate matplotlib charts and diagrams from wiki content.

## Usage

- `/kb-viz "Compare training costs across model architectures"` — generate a chart
- `/kb-viz "Concept map of the RL articles"` — generate a relationship diagram
- `/kb-viz wiki/ai/` — visualize a category's structure

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Research Data

1. Read relevant wiki articles using the navigation protocol
2. Extract quantitative data, relationships, timelines, or comparisons
3. Determine the best chart type:
   - **Bar/line chart** — for comparisons, trends
   - **Scatter plot** — for correlations
   - **Network/graph** — for concept relationships
   - **Timeline** — for chronological data
   - **Table** — when a chart isn't the right fit

### Step 3: Generate Visualization

Write a Python script and execute it to create the chart:

```python
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

# ... create the visualization ...

plt.savefig('outputs/images/YYYY-MM-DD-slug.png', dpi=150, bbox_inches='tight')
plt.close()
```

Save the image to `outputs/images/YYYY-MM-DD-slug.png`.

### Guidelines

- **Clear labels** — title, axis labels, legend
- **Clean style** — use `plt.style.use('seaborn-v0_8-whitegrid')` or similar
- **150 DPI** — good balance of quality and file size
- **Save as PNG** — universal format, works in Obsidian
- **Delete the script after execution** — the image is the deliverable, not the code
- If matplotlib is not installed, tell the user to run `pip install matplotlib`

### Step 4: Embed and Report

- Print the path to the image
- Show how to embed in a wiki article: `![[outputs/images/YYYY-MM-DD-slug.png]]`
- Ask user: embed this in an existing wiki article?
