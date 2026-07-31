# **Technical Design Document (TDD) & Design Specification**

**System Name:** Graphify Cloud IDE & Centralized AI Engineering Platform

**Document Version:** 2.0

**Target Architecture:** Next.js 14+ App Router, Ephemeral FastAPI Sandboxes, React Flow (@xyflow/react), Monaco Editor

---

## **1\. System Overview & Architecture Realignment**

The **Graphify Cloud IDE** is a centralized, cloud-native Web Workstation designed for automated repository syncing, structural knowledge graph parsing (graphify), and graph-aware AI engineering.

Unlike single-pane coding practice platforms, the workspace adopts a **3-pane structural layout** tailored for dual visual representation (Code AST \+ 2D Architectural Knowledge Graph) and automated Pull Request workflows:

┌────────────────────────────────────────────────────────────────────────────────────────┐  
│ Top Navigation Header: Repository Name | Active Branch | WS Extraction (100%) | \[ Create PR \]│  
├─────────────────────────┬─────────────────────────────┬────────────────────────────────┤  
│ Left Panel              │ Center Panel                │ Right Panel                    │  
│ Monaco Code Editor      │ Graph Viewer                │ Graph-Aware AI Agent           │  
│ & Diff Inspection       │ (@xyflow/react 2D Canvas)   │ (RPC Queries & PR Dispatch)    │  
└─────────────────────────┴─────────────────────────────┴────────────────────────────────┘

---

## **2\. Global Layout & Geometry Constants**

### **2.1 Geometry & Panel Border Rules**

* **Structural Radius Principle:** Strictly **0px (Sharp Edges)** across all main structural containers, sidebars, panel splitters, header strips, and bottom utility bars.  
* **Component Radius Principle:** Subtly rounded corners (**4px–6px**) reserved strictly for interactive form inputs, drop-down controls, tab triggers, and action buttons.  
* **Pill Element Radius:** Capsule-shaped corners (**14px–16px**) applied to status tags, category badges, and mode selection toggles.  
* **Border Standard:** 1px solid \#27272A (or rgba(255, 255, 255, 0.08)) applied across all panel divides.

### **2.2 Layout Grid & Resizable Panels Specification**

| Layout Zone | Default Dimension | Resizable Bounds | CSS & Border Configuration |
| :---- | :---- | :---- | :---- |
| **Top Header Bar** | Height: 44px | Fixed (0px) | bg: \#121215; border-bottom: 1px solid \#27272A; |
| **Left Panel (Monaco Editor)** | Width: 35% | Min: 25%, Max: 50% | bg: \#0D0D10; border-right: 1px solid \#27272A; |
| **Center Panel (Graph Viewer)** | Width: 40% | Min: 30%, Max: 60% | bg: \#09090B; border-right: 1px solid \#27272A; |
| **Right Panel (AI Chat Agent)** | Width: 25% | Min: 20%, Max: 40% | bg: \#121215; |

---

## **3\. Typography & Color Tokens Specification**

### **3.1 Color Palette Tokens**

CSS

:root {  
  /\* Surface & Panel Colors \*/  
  \--bg-app: \#09090B;          /\* Main application canvas backdrop \*/  
  \--bg-panel: \#121215;        /\* Top bar, left explorer, right chat sidebar \*/  
  \--bg-editor: \#0D0D10;       /\* Monaco editor code surface \*/  
  \--bg-input: \#18181B;        /\* Dropdowns, text inputs, form controls \*/  
    
  /\* Borders & Dividers \*/  
  \--border-subtle: \#27272A;   /\* Primary structural divide color \*/  
  \--border-focus: \#3F3F46;    /\* Input hover and focused states \*/

  /\* Status & Action Accents \*/  
  \--accent-emerald: \#10B981;  /\* Primary action CTA ("Create Pull Request") \*/  
  \--accent-blue: \#3B82F6;     /\* Active tab highlight & active graph node border \*/  
  \--accent-purple: \#8B5CF6;   /\* God-node indicator & high-centrality symbols \*/

  /\* Text Colors \*/  
  \--text-primary: \#FFFFFF;    /\* Active text, code, titles \*/  
  \--text-secondary: \#A1A1AA;  /\* Labels, sub-headers, inactive tabs \*/  
  \--text-muted: \#52525B;      /\* Line numbers, placeholder text \*/  
}

### **3.2 Font Hierarchy Table**

CSS

/\* Core Font Families \*/  
\--font-ui: Inter, \-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;  
\--font-code: "JetBrains Mono", Fira Code, Menlo, Monaco, Consolas, monospace;

| UI Element | Font Family | Size | Weight | Line Height | Color Code |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **Header Repo Title** | \--font-ui | 14px | 600 (SemiBold) | 1.2 | \#FFFFFF |
| **Branch Dropdown** | \--font-code | 12px | 500 (Medium) | 1.0 | \#D4D4D8 |
| **Monaco Code Editor** | \--font-code | 14px | 400 (Regular) | 1.5 | \#F4F4F5 |
| **Monaco Line Numbers** | \--font-code | 13px | 400 (Regular) | 1.5 | \#52525B |
| **Explorer File Items** | \--font-ui | 13px | 400 (Regular) | 1.4 | \#D4D4D8 |
| **AI Agent Chat Message** | \--font-ui | 13px | 400 (Regular) | 1.5 | \#E4E4E7 |
| **Primary Action Button** | \--font-ui | 13px | 600 (SemiBold) | 1.0 | \#FFFFFF |

---

## **4\. Detailed Component Specifications**

### **4.1 Top Navigation Header Component**

* **Dimensions:** Height 44px, Width 100%, border-radius: 0px, border-bottom: 1px solid \#27272A.  
* **Left Group:**  
  * **Repository Title Badge:** Renders synced repository owner/repository string (font-size: 14px, font-weight: 600).  
  * **Branch Select Dropdown:** Height 28px, border-radius: 6px, bg: \#18181B, border: 1px solid \#27272A, displaying current active branch (e.g., main or feat/refactor-ast).  
* **Center Group:**  
  * **WebSocket Indexing Indicator:** Real-time text indicator showing parsing progress streamed from backend (e.g., AST Indexing: 100%). \--font-code, font size 12px, text color \#10B981.  
* **Right Button Group:**  
  * **Admin Settings Link:** Height 32px, padding 0 12px, border-radius: 6px, bg: \#27272A, text \#FFFFFF (accessible for system credentials setup).  
  * **Create Pull Request Button (Primary CTA):** Height 32px, padding 0 16px, border-radius: 6px, bg: \#10B981, font weight 600, text \#FFFFFF. Triggers GitHub REST API push & PR creation.

### **4.2 Left Panel: Monaco Code Editor & Diff Engine**

* **Container:** Background \#0D0D10, border-radius: 0px, border-right: 1px solid \#27272A.  
* **Monaco Configuration Settings:**  
* JSON

{  
  "fontSize": 14,  
  "lineHeight": 21,  
  "fontFamily": "'JetBrains Mono', Fira Code, monospace",  
  "renderLineHighlight": "all",  
  "minimap": { "enabled": false },  
  "scrollBeyondLastLine": false,  
  "automaticLayout": true  
}

*   
*   
* **Git Diff View:** Supports inline or side-by-side Monaco Diff Editor (@monaco-editor/react) to inspect changes performed by the AI agent on the workspace volume prior to dispatching a PR.

### **4.3 Center Panel: Interactive 2D Graph Viewer (@xyflow/react)**

* **Container:** Background \#09090B, border-radius: 0px, border-right: 1px solid \#27272A.  
* **Graph Engine:** Implemented using React Flow (@xyflow/react) parsing state directly from graph.json.  
* **Node Styling Rules:**  
  * **Standard Code Nodes:** bg: \#18181B, border: 1px solid \#27272A, border-radius: 6px, text \#FFFFFF.  
  * **God Nodes (High Centrality):** Highlighted with elevated border 1.5px solid \#8B5CF6 (Purple).  
  * **Selected Node State:** Enclosed in 2px solid \#3B82F6 (Blue active highlight).  
* **Editor-Graph Bi-directional Selection:**  
  * Clicking a node on the graph dispatches an event that focuses the Monaco Editor on the specific file, class, or function definition line.

### **4.4 Right Panel: Graph-Aware AI Agent Workspace**

* **Container:** Background \#121215, border-radius: 0px.  
* **Top Header Tabs:** \[ Agent \] | \[ Output Log \]. Active tab styled with border-bottom: 2px solid \#3B82F6.  
* **Prompt Input Container:**  
  * Background \#18181B, border: 1px solid \#27272A, border-radius: 12px, padding 12px 16px.  
  * Send Arrow Button: Embedded inside right edge of input box, size 28px x 28px, border-radius: 6px, bg: \#2563EB.  
* **Agent RPC Response Actions:** The chat interface directly consumes decrypted admin credentials to run deterministic queries against graph.json. Chat messages render inline interactive action triggers:  
  * \[ Inspect Diff in Monaco \]  
  * \[ Dispatch Pull Request \]

---

## **5\. CSS Utility Implementation Reference**

CSS

/\* Quick CSS Class Reference for Front-End Engineering \*/

.graphify-panel-container {  
  border-radius: var(--panel-border-radius);  
  border-color: var(--border-subtle);  
  background-color: var(--bg-panel);  
}

.graphify-button-primary {  
  height: 32px;  
  padding: 0 16px;  
  border-radius: var(--control-border-radius);  
  background-color: var(--accent-emerald);  
  color: \#ffffff;  
  font-family: var(--font-ui);  
  font-size: 13px;  
  font-weight: 600;  
  border: none;  
  cursor: pointer;  
}

.graphify-chat-input {  
  background-color: var(--bg-input);  
  border: 1px solid var(--border-subtle);  
  border-radius: var(--chat-input-border-radius);  
  padding: 12px 16px;  
  color: var(--text-primary);  
  font-family: var(--font-ui);  
  font-size: 13px;  
}

