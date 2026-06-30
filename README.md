# RepoMind AI - Autonomous Software Engineering Intelligence Platform

RepoMind AI is an autonomous, multi-agent AI system designed to analyze, map, and interact with GitHub repositories without cloning them locally. It leverages the Model Context Protocol (MCP) and GitHub APIs to query codebase structures, parse imports for visual architecture mappings, and answer engineering queries.

## Architecture

- **Frontend**: React (built with Vite), Tailwind CSS, React Flow, and Axios/WebSockets for streaming agent logs.
- **Backend**: FastAPI, MongoDB (Atlas for document storage), LangGraph (Agentic Workflow), and Google GenAI (AI Model API).
- **Database**: MongoDB Atlas (document store), Qdrant Cloud (vector semantic search), Neo4j AuraDB (file dependency graph).

## Prerequisites

- [Docker](https://www.docker.com/) and Docker Compose
- GitHub Personal Access Token (PAT)
- Google API Key

## Getting Started

1. **Clone the configuration & create environment settings**:
   ```bash
   cp .env.example .env
   ```
2. **Edit `.env`** to insert your `GOOGLE_API_KEY`, `GITHUB_TOKEN`, and cloud database credentials:
   - MongoDB Atlas URI (from your Atlas dashboard)
   - Qdrant Cloud URL and API Key (from https://cloud.qdrant.io)
   - Neo4j AuraDB URI and password (from https://console.neo4j.io)
3. **Start the applications**:
   ```bash
   docker-compose up --build
   ```
4. Access the applications:
   - **Frontend**: `http://localhost:5173`
   - **Backend API Docs**: `http://localhost:8000/docs`

## Local Development (Without Docker)

### Backend Setup
1. Navigate to the backend directory:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Set up environment variables in your terminal or a local `.env` file.
3. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

### Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
