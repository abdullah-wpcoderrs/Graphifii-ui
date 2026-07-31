# **Technical Design Document (TDD)**

**System Name:** Graphify Cloud IDE & Centralized AI Engineering Platform

**Document Version:** 1.0

**Target Platform:** Railway / Docker Compose (Cloud-Native Multi-Tenant Architecture)

---

## **1\. Feature Specifications**

### **1.1 Centralized Admin Key Provisioning & Security**

* **Client-Side Encryption:** AI LLM provider keys (OpenAI, Anthropic, Gemini) are encrypted in the browser using Web Crypto API (AES-256-GCM with PBKDF2 key derivation) before being sent across the network.  
* **Global Credential Reuse:** Platform administrators configure AI keys once. Users can run AI-assisted graph queries and code refactoring across any project without exposing raw credentials to the client or requiring per-developer local .env setups.

### **1.2 GitHub OAuth & Automated Repository Discovery**

* **One-Click GitHub Integration:** Users authenticate via GitHub OAuth or a dedicated GitHub App.  
* **Repository Sync & Selection:** The system syncs all public and private repositories accessible to the user and displays them on a dashboard for one-click environment provisioning.

### **1.3 Micro-Sandboxed Execution & AST Graph Generation**

* **Containerized Workspaces:** Ephemeral Docker containers (built via Docker Compose / Railway / Daytona) host an isolated Python 3.12 environment with tree-sitter AST parsers.  
* **Headless Graphify Execution:** Asynchronous parsing of codebases into graph.json, graph.html, and GRAPH\_REPORT.md using Python function hooks instead of terminal CLI calls.  
* **Real-Time Streaming:** WebSocket integration (ws\_manager.py) streams tree-sitter parsing progress and graph generation stages (0% $\\rightarrow$ 100%) back to the Next.js UI.

### **1.4 In-Browser Graph IDE & Direct PR Dispatch**

* **Interactive Code & Architecture View:** Dual-pane interface featuring Monaco Editor (VS Code engine) alongside interactive 2D graph visualizations via @xyflow/react.  
* **Graph-Aware AI Agent:** Direct RPC queries against graph.json enable the agent to explain system paths, identify god nodes, and refactor code based on deterministic relationships rather than raw grepping.  
* **Git & PR Dispatch:** Automated branch creation (feat/...), committing, and Pull Request dispatch directly to GitHub via the GitHub REST API using the user's OAuth access token.

---

## **2\. Technology Stack**

| Layer | Technology | Purpose |
| :---- | :---- | :---- |
| **Frontend Framework** | Next.js 14+ (App Router, React 18+) | Web dashboard, authentication state, workspace layout |
| **Code Editor Engine** | @monaco-editor/react | In-browser code editing, diff viewing, and syntax highlighting |
| **Graph Visualizer** | @xyflow/react (React Flow) | Rendering interactive nodes, edges, and communities from graph.json |
| **Client Cryptography** | Web Crypto API (AES-256-GCM) | Zero-trust client-side encryption of API credentials |
| **Backend API & Orchestration** | Node.js / Next.js API Routes | Session management, database orchestration, GitHub API integration |
| **Job Queue & Broker** | Redis \+ BullMQ | Background scheduling for repository cloning and indexing |
| **Database & ORM** | PostgreSQL \+ Prisma ORM | Multi-tenant schema, user management, and encrypted secret storage |
| **Sandbox Environment** | Ephemeral Docker Containers / FastAPI | Python 3.12, tree-sitter AST, isolated Workspace volume |
| **Object Storage** | AWS S3 / Cloudflare R2 | Storage for generated graph.json, graph.html, and cached workspace states |

---

## **3\. Inventory of Modified & Created Files**

To convert the CLI-focused graphify repository into a headless microservice backend, the following file inventory and refactoring rules apply:

graphify/  
├── graphify/               \# Main Python Package  
│   ├── cli.py             \# REWRITE: Remove interactive CLI terminal prompts/stdin  
│   ├── extract.py         \# REWRITE: Expose in-memory progress callbacks & return JSON dicts  
│   └── query.py           \# REWRITE: Make query logic REST/RPC callable without terminal prints  
├── server/                \# NEW MODULE: FastAPI Sidecar API  
│   ├── \_\_init\_\_.py  
│   ├── app.py             \# NEW: FastAPI server exposing /health, /extract, /query  
│   └── ws\_manager.py      \# NEW: WebSocket connection manager for live task progress  
├── Dockerfile             \# REWRITE: Production container spec (Python 3.12, uv, git)  
└── docker-compose.yml     \# NEW: Development orchestration (Next.js \+ Redis \+ Sandbox worker)

### **3.1 Detailed File Specification Highlights**

#### **graphify/server/app.py (NEW)**

Exposes core Graphify functionalities over HTTP REST endpoints for the Next.js orchestrator:

* GET /health: Health-check endpoint returning workspace status.  
* POST /api/extract: Asynchronously triggers tree-sitter codebase parsing.  
* POST /api/query: Executes deterministic sub-graph queries on graph.json.

#### **graphify/server/ws\_manager.py (NEW)**

Manages WebSocket broadcast loops to stream real-time AST parsing progress (TASK\_PROGRESS) back to the client.

#### **graphify/extract.py (REWRITE)**

Removes terminal prints (rich console logs) and replaces them with an optional progress callback parameter:

Python

def extract\_codebase(target\_dir, progress\_callback=None):  
    \# Modified loop to report percentage progress over WebSockets

#### **Dockerfile (REWRITE)**

Replaces single-user CLI setup with a production server image running uvicorn graphify.server.app:app \--host 0.0.0.0 \--port 8000.

---

## **4\. End-to-End Data Flow (ASCII Diagram)**

┌──────────────┐         ┌──────────────────────┐         ┌──────────────────────┐         ┌─────────────────────┐         ┌────────────────────┐  
│ Admin/User   │         │  Next.js Frontend    │         │ Orchestrator / DB    │         │ Redis \+ BullMQ      │         │ Sandbox Container  │  
└──────┬───────┘         └──────────┬───────────┘         └──────────┬───────────┘         └──────────┬──────────┘         └─────────┬──────────┘  
       │                            │                                │                                │                            │  
       │ 1\. Input AI Keys           │                                │                                │                            │  
       ├───────────────────────────►│ Client-side Encryption         │                                │                            │  
       │                            │ (AES-256-GCM)                  │                                │                            │  
       │                            ├───────────────────────────────►│ Store Encrypted Ciphertext     │                            │  
       │                            │                                │ in PostgreSQL                  │                            │  
       │                            │                                │                                │                            │  
       │ 2\. Connect GitHub & Launch │                                │                                │                            │  
       ├───────────────────────────►│ POST /api/projects/launch      │                                │                            │  
       │                            ├───────────────────────────────►│ Enqueue Clone & Index Job      │                            │  
       │                            │                                ├───────────────────────────────►│ Dispatch Job to Worker     │  
       │                            │                                │                                ├───────────────────────────►│ 3\. Provision Pod   │  
       │                            │                                │                                │                            │    Clone GitHub Repo  
       │                            │                                │                                │                            │    Inject Decrypted Keys  
       │                            │◄───────────────────────────────┴────────────────────────────────┴────────────────────────────┤ 4\. Run Tree-Sitter  
       │                            │  5\. Stream Progress via WebSockets ("TASK\_PROGRESS": 0% \-\> 100%)                              │    Build graph.json  
       │                            │                                                                                              │  
       │ 6\. Interact via UI         │                                                                                              │  
       ├───────────────────────────►│ Query Graph / Monaco Edits                                                                   │  
       │                            ├─────────────────────────────────────────────────────────────────────────────────────────────►│ 7\. FastAPI Sidecar  
       │                            │                                                                                              │    Query graph.json  
       │                            │◄─────────────────────────────────────────────────────────────────────────────────────────────┤    Return AST JSON  
       │                            │                                                                                              │  
       │ 8\. Click "Create PR"       │                                                                                              │  
       ├───────────────────────────►│ Push Branch & Open Pull Request via GitHub API                                              │  
       │                            ├─────────────────────────────────────────────────────────────────────────────────────────────►│ 9\. Git Push Branch  
       │                            │                                                                                              │    Clean up Sandbox

---

## **5\. Database Schema (Prisma ORM Format)**

Code snippet

datasource db {  
  provider \= "postgresql"  
  url      \= env("DATABASE\_URL")  
}

generator client {  
  provider \= "prisma-client-js"  
}

enum Role {  
  ADMIN  
  USER  
}

enum ProjectStatus {  
  CLONING  
  INDEXING  
  READY  
  FAILED  
}

model User {  
  id                String      @id @default(uuid())  
  email             String      @unique  
  name              String?  
  role              Role        @default(USER)  
  githubAccessToken String?     // Encrypted OAuth Access Token for GitHub API  
  projects          Project\[\]  
  createdAt         DateTime    @default(now())  
  updatedAt         DateTime    @updatedAt  
}

model SystemCredential {  
  id            String   @id @default(uuid())  
  provider      String   // "openai", "anthropic", "gemini"  
  keyCiphertext  String   // Encrypted client-side via AES-256-GCM  
  iv            String   // Initialization Vector (Base64)  
  salt          String   // Key derivation salt (Base64)  
  createdAt     DateTime @default(now())  
  updatedAt     DateTime @updatedAt  
}

model Project {  
  id            String        @id @default(uuid())  
  userId        String  
  user          User          @relation(fields: \[userId\], references: \[id\], onDelete: Cascade)  
  repoName      String        // e.g., "owner/repository"  
  repoUrl       String  
  defaultBranch String        @default("main")  
  status        ProjectStatus @default(CLONING)  
  sandboxId     String?       // Remote container or pod instance ID  
  graphJsonUrl  String?       // S3/R2 storage link for persisted graph.json  
  graphHtmlUrl  String?       // S3/R2 storage link for persisted graph.html  
  createdAt     DateTime      @default(now())  
  updatedAt     DateTime      @updatedAt  
}

