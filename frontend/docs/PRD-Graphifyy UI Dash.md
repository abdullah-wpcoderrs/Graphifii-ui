# **Product Requirement Document (PRD)**

**Product Name:** Graphify Cloud IDE & Centralized AI Engineering Platform

**Document Version:** 2.0

**Status:** Approved Specification

Graphify github repo: [https://github.com/Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify)

---

## **1\. Executive Summary & Intent**

### **1.1 Overview**

The **Graphify Cloud IDE** is a centralized, web-based AI Software Engineering Workspace designed to function as a single source of truth for managing all software projects across an organization.

Rather than requiring each developer to manually configure API keys, install local CLI tools, or set up per-project environments, the system features a **two-tier architecture**:

1. **Admin Key Provisioning:** Platform administrators configure and manage global AI LLM provider keys (OpenAI, Anthropic, Gemini) from an admin settings panel. Keys are encrypted client-side on the frontend before transmission and persisted securely in the database.  
2. **GitHub OAuth & Repository Sync:** Users authenticate via GitHub OAuth (or GitHub App integration). The system automatically discovers and syncs their repositories, allowing users to select any repository to instantly spin up a sandboxed environment, generate knowledge graphs via **Graphify**, inspect AST dependencies, and dispatch Pull Requests (PRs).

---

## **2\. Target Audience & Behavioral Usage Patterns**

### **2.1 User Roles & Personas**

* **System Administrator / Org Owner:** Responsible for setting up global LLM API credentials once, establishing usage boundaries, and managing organization-wide settings.  
* **Software Engineers & Developers:** Authenticate via GitHub, select projects from their synced repository list, interact with the graph-aware AI coding agent, edit code, and open PRs without handling raw API credentials.  
* **Engineering Managers / Tech Leads:** Inspect high-level architecture maps (GRAPH\_REPORT.md, god nodes, community dependencies) across all team projects.

### **2.2 Mental Model & Detailed Behavioral Flows**

┌────────────────────────────────────────────────────────────────────────────────────────┐  
│                              1\. ADMIN CREDENTIAL SETUP                                 │  
│ Admin logs in ──► Frontend encrypts AI LLM Keys (Client-side) ──► Saved in Database    │  
└───────────────────────────────────────────┬────────────────────────────────────────────┘  
                                            │  
                                            ▼  
┌────────────────────────────────────────────────────────────────────────────────────────┐  
│                        2\. USER AUTHENTICATION & REPO SYNC                              │  
│ Developer signs in via GitHub App/OAuth ──► System fetches & syncs GitHub Repositories │  
└───────────────────────────────────────────┬────────────────────────────────────────────┘  
                                            │  
                                            ▼  
┌────────────────────────────────────────────────────────────────────────────────────────┐  
│                          3\. ONE-CLICK PROJECT SANDBOX SPINNUP                          │  
│ User picks Repo ──► Next.js triggers Docker/Railway worker ──► Repos cloned in Sandbox  │  
│ Sandbox pulls global AI keys ──► Graphify tree-sitter parses AST ──► WS updates UI    │  
└───────────────────────────────────────────┬────────────────────────────────────────────┘  
                                            │  
                                            ▼  
┌────────────────────────────────────────────────────────────────────────────────────────┐  
│                        4\. INTERACTIVE WEB WORKSPACE & AGENT                            │  
│ Left: Code Editor (Monaco) | Middle: Graph Viewer (React Flow) | Right: AI Chat Agent  │  
└───────────────────────────────────────────┬────────────────────────────────────────────┘  
                                            │  
                                            ▼  
┌────────────────────────────────────────────────────────────────────────────────────────┐  
│                       5\. CODE MODIFICATION & PR DISPATCH                               │  
│ Agent edits code in volume ──► Developer checks diff ──► Open PR via GitHub App API   │  
└────────────────────────────────────────────────────────────────────────────────────────┘

#### **Admin Key Setup Flow**

1. Admin opens **Admin Settings $\\rightarrow$ AI Credentials**.  
2. Inputs API keys for OpenAI, Anthropic, or Gemini.  
3. The Next.js frontend encrypts the keys locally using a public key/secret before sending the payload over the wire.  
4. The server receives the ciphertext and stores it in PostgreSQL alongside the initialization vectors (IV) and auth tags.

#### **User Repository Selection Flow**

1. User logs in using **GitHub OAuth / GitHub App**.  
2. The platform queries the GitHub API using the user's OAuth token to retrieve accessible personal and organization repositories.  
3. Repositories are displayed as cards on the user dashboard.  
4. User clicks **"Launch Workspace"** on any repository card.

#### **Agent Workspace & PR Dispatch Flow**

1. Clicking "Launch Workspace" spins up an isolated, sandboxed Docker container (Railway / Daytona / E2B).  
2. The workspace pulls the central encrypted LLM keys from the DB (decrypted temporarily in worker memory) and runs graphify tree-sitter AST extraction.  
3. WebSockets stream graph creation status (0% $\\rightarrow$ 100%) back to the Next.js UI.  
4. The user asks the agent to perform refactoring or features. The agent uses graph.json to inspect code dependencies, applies changes to the workspace volume, and displays a Monaco diff.  
5. Clicking **"Create Pull Request"** pushes the branch to GitHub and opens a PR automatically via the user's GitHub integration.

---

## **3\. Comprehensive System Architecture**

┌────────────────────────────────────────────────────────────────────────┐  
│                        Next.js 14+ Frontend                            │  
│     (Client-Side Key Encryption \+ Monaco Editor \+ React Flow)          │  
└───────────────────────────────────┬────────────────────────────────────┘  
                                    │ WebSockets / REST API  
┌───────────────────────────────────▼────────────────────────────────────┐  
│                    Orchestration Backend (Node API)                    │  
│    (Database: Postgres \+ Prisma / Job Queue: Redis \+ BullMQ)          │  
└───────────────────────────────────┬────────────────────────────────────┘  
                                    │ Docker API / Container Execution  
┌───────────────────────────────────▼────────────────────────────────────┐  
│                  Sandboxed Workspace Container Pool                    │  
│      (Python 3.12 \+ Tree-Sitter \+ graphifyy CLI \+ Git \+ Node)          │  
└────────────────────────────────────────────────────────────────────────┘

---

## **4\. Codebase Refactoring & Headless Implementation**

To support web execution, standard CLI interactions (rich console prints, terminal stdin) are removed and replaced with a Python **FastAPI Sidecar** and **WebSocket event handlers**.

graphify/  
├── graphify/               \# Main Python Package  
│   ├── cli.py             \# REWRITE: Remove interactive terminal prompts/stdin  
│   ├── extract.py         \# REWRITE: Expose in-memory progress callbacks & JSON returns  
│   └── query.py           \# REWRITE: Make query functions REST/RPC callable  
├── server/                \# NEW MODULE: FastAPI Sidecar for cloud/web  
│   ├── \_\_init\_\_.py  
│   ├── app.py             \# NEW: FastAPI server exposing /extract, /query, /health  
│   └── ws\_manager.py      \# NEW: WebSocket manager for real-time extraction events  
├── Dockerfile             \# REWRITE: Production container spec (Python 3.12, uv, git)  
└── docker-compose.yml     \# NEW: Orchestration (Next.js \+ Redis \+ Sandbox worker)

### **4.1 Client-Side Encryption Implementation (Frontend Utilities)**

To guarantee that raw LLM API keys are encrypted **before** leaving the browser:

TypeScript

// lib/crypto.ts (Next.js Frontend)  
export async function encryptApiKey(plainKey: string, masterSecret: string) {  
  const enc \= new TextEncoder();  
  const keyMaterial \= await window.crypto.subtle.importKey(  
    "raw",  
    enc.encode(masterSecret),  
    { name: "PBKDF2" },  
    false,  
    \["deriveKey"\]  
  );

  const salt \= window.crypto.getRandomValues(new Uint8Array(16));  
  const key \= await window.crypto.subtle.deriveKey(  
    {  
      name: "PBKDF2",  
      salt,  
      iterations: 100000,  
      hash: "SHA-256",  
    },  
    keyMaterial,  
    { name: "AES-GCM", length: 256 },  
    false,  
    \["encrypt"\]  
  );

  const iv \= window.crypto.getRandomValues(new Uint8Array(12));  
  const encrypted \= await window.crypto.subtle.encrypt(  
    { name: "AES-GCM", iv },  
    key,  
    enc.encode(plainKey)  
  );

  return {  
    ciphertext: Buffer.from(encrypted).toString("base64"),  
    iv: Buffer.from(iv).toString("base64"),  
    salt: Buffer.from(salt).toString("base64"),  
  };  
}

### **4.2 FastAPI Sidecar Core Server (graphify/server/app.py)**

Python

from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect  
from fastapi.middleware.cors import CORSMiddleware  
import os  
from graphify.extract import extract\_codebase  
from graphify.query import query\_graph

app \= FastAPI(title="Graphify Engine Sidecar")

app.add\_middleware(  
    CORSMiddleware,  
    allow\_origins=\["\*"\],  
    allow\_credentials=True,  
    allow\_methods=\["\*"\],  
    allow\_headers=\["\*"\],  
)

@app.get("/health")  
def health():  
    return {"status": "ok", "workspace": os.environ.get("WORKSPACE\_DIR", "/workspace")}

@app.post("/api/extract")  
async def trigger\_extraction(background\_tasks: BackgroundTasks):  
    workspace \= os.environ.get("WORKSPACE\_DIR", "/workspace")  
    background\_tasks.add\_task(extract\_codebase, target\_dir=workspace)  
    return {"status": "processing", "message": "Extraction started"}

@app.post("/api/query")  
async def handle\_query(payload: dict):  
    question \= payload.get("query")  
    workspace \= os.environ.get("WORKSPACE\_DIR", "/workspace")  
    graph\_path \= os.path.join(workspace, "graphify-out", "graph.json")  
      
    result \= query\_graph(graph\_path=graph\_path, prompt=question)  
    return {"result": result}

### **4.3 WebSocket Progress Manager (graphify/server/ws\_manager.py)**

Python

from fastapi import WebSocket  
from typing import List

class ConnectionManager:  
    def \_\_init\_\_(self):  
        self.active\_connections: List\[WebSocket\] \= \[\]

    async def connect(self, websocket: WebSocket):  
        await websocket.accept()  
        self.active\_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):  
        self.active\_connections.remove(websocket)

    async def broadcast\_progress(self, phase: str, progress: int, message: str):  
        payload \= {  
            "event": "TASK\_PROGRESS",  
            "phase": phase,  
            "progress": progress,  
            "message": message  
        }  
        for connection in self.active\_connections:  
            await connection.send\_json(payload)

manager \= ConnectionManager()

### **4.4 Dockerfile Specification (Dockerfile)**

Dockerfile

FROM python:3.12\-slim

RUN apt-get update && apt-get install \-y \--no-install-recommends \\  
    git \\  
    build-essential \\  
    curl \\  
    && rm \-rf /var/lib/apt/lists/\*

COPY \--from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./  
RUN uv sync \--frozen \--no-cache

COPY . .

ENV PYTHONUNBUFFERED=1  
ENV WORKSPACE\_DIR=/workspace

EXPOSE 8000

CMD \["uv", "run", "uvicorn", "graphify.server.app:app", "--host", "0.0.0.0", "--port", "8000"\]

### **4.5 Docker Compose Orchestration (docker-compose.yml)**

YAML

version: '3.8'

services:  
  graphify-engine:  
    build:  
      context: .  
      dockerfile: Dockerfile  
    ports:  
      \- "8000:8000"  
    environment:  
      \- ANTHROPIC\_API\_KEY=${ANTHROPIC\_API\_KEY}  
      \- OPENAI\_API\_KEY=${OPENAI\_API\_KEY}  
      \- WORKSPACE\_DIR=/workspace  
    volumes:  
      \- ./test\_repo:/workspace  
    networks:  
      \- sandbox-net

  redis:  
    image: redis:alpine  
    ports:  
      \- "6379:6379"  
    networks:  
      \- sandbox-net

networks:  
  sandbox-net:  
    driver: bridge

---

## **5\. API Matrix & Data Schema**

### **5.1 REST API Endpoint Matrix**

| Method | Endpoint | Access Level | Description |
| :---- | :---- | :---- | :---- |
| **POST** | /api/admin/credentials | Admin Only | Saves client-encrypted AI LLM keys |
| **GET** | /api/github/repos | Authenticated | Fetches user's accessible GitHub repositories |
| **POST** | /api/projects/launch | Authenticated | Provisions sandbox, clones repo, triggers AST indexing |
| **GET** | /api/projects/\[id\]/graph | Authenticated | Retrieves graph.json state for graph viewer |
| **POST** | /api/agent/query | Authenticated | Queries graph structure or streams code refactor proposals |
| **POST** | /api/agent/pr | Authenticated | Pushes sandbox feature branch and opens a GitHub PR |

### **5.2 Database Schema (Prisma ORM)**

Code snippet

enum Role {  
  ADMIN  
  USER  
}

model User {  
  id             String        @id @default(uuid())  
  email          String        @unique  
  name           String?  
  role           Role          @default(USER)  
  githubAccessToken String?    // OAuth access token for GitHub API  
  projects       Project\[\]  
  createdAt      DateTime      @default(now())  
}

model SystemCredential {  
  id             String   @id @default(uuid())  
  provider       String   // "openai", "anthropic", "gemini"  
  keyCiphertext   String   // Encrypted on frontend (AES-GCM)  
  iv             String   // Initialization vector  
  salt           String   // Salt for key derivation  
  updatedAt      DateTime @updatedAt  
}

model Project {  
  id             String   @id @default(uuid())  
  userId         String  
  user           User     @relation(fields: \[userId\], references: \[id\], onDelete: Cascade)  
  repoName       String   // e.g. "org/repository"  
  repoUrl        String  
  defaultBranch  String   @default("main")  
  status         String   // "CLONING", "INDEXING", "READY", "FAILED"  
  sandboxId      String?  
  graphJsonUrl   String?  
  createdAt      DateTime @default(now())  
}

---

## **6\. Lifecycle Management & Security Protocols**

### **6.1 Sandbox Persistence & Auto-Teardown**

* **Ephemeral Workspaces:** Sandbox containers execute code parsing and agent tasks in isolation.  
* **Idle Shutdown:** Workspaces auto-terminate after 15 minutes of inactivity to optimize cloud resources.  
* **Persistent Assets:** Generated outputs (graph.json, graph.html, modified files) sync to AWS S3 / Cloudflare R2 object storage. Re-opening a project reinstantiates a fresh sandbox container and rehydrates assets in \~2 seconds.

### **6.2 Cascading User Deletion Protocol**

When an administrator or user triggers account deletion:

1. **Container Termination:** Active sandbox instances linked to the user are immediately force-killed (docker rm \-f).  
2. **Object Storage Eviction:** Files under s3://bucket/users/{userId}/ are deleted recursively.  
3. **Database Cascade:** Cascading foreign key rules (onDelete: Cascade) delete linked projects, OAuth tokens, and PR histories. System-level credentials set by admins remain intact for other users.

