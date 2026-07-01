from typing import Dict, Any, List
from app.agents.agent_graph import get_llm
from langchain_core.messages import SystemMessage, HumanMessage
import logging
import json

logger = logging.getLogger(__name__)

async def generate_mermaid_architecture(repo: Dict[str, Any], file_list: List[str]) -> str:
    """
    Analyzes the repository's files and frameworks to generate a Mermaid 
    architecture diagram, simulating GitDiagram's functionality.
    """
    llm = get_llm()
    
    # We constrain the LLM to output highly styled, professional Mermaid code
    system_prompt = (
        "You are an expert Software Architect analyzing a codebase. Your task is to generate a breathtaking, "
        "production-quality system architecture diagram using Mermaid.js syntax. You must mimic the style of 'GitDiagram'.\n\n"
        "RULES FOR THE DIAGRAM:\n"
        "1. Use 'graph TB' or 'graph TD' direction.\n"
        "2. Group related components logically using 'subgraph' (e.g., 'subgraph Frontend', 'subgraph Backend', 'subgraph Database', 'subgraph CI/CD').\n"
        "3. Within subgraphs, map the most important files or modules into nodes.\n"
        "4. Use appropriate shapes: Databases should be cylindrical like `DB[(PostgreSQL)]`, standard components rounded like `App(React App)`.\n"
        "5. Add meaningful edge labels indicating how things connect (e.g., `-->|REST API|`, `-->|Reads/Writes|`, `-->|Imports|`).\n"
        "6. CRITICAL FOR INTERACTIVITY: The Node ID (the text before the brackets) MUST be the EXACT file path or folder path if it represents one. For example, `backend/app/main.py(FastAPI App)` or `frontend/src(React UI)`. Do not use generic IDs like `A` or `Node1` for files.\n"
        "7. INJECT CUSTOM STYLING. You must include these exact classDefs at the bottom of your graph and apply them to nodes using `:::className` syntax:\n"
        "   classDef frontend fill:#3b82f6,stroke:#2563eb,stroke-width:2px,color:#fff,rx:8px,ry:8px;\n"
        "   classDef backend fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff,rx:8px,ry:8px;\n"
        "   classDef database fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#fff,rx:10px,ry:10px;\n"
        "   classDef config fill:#64748b,stroke:#475569,stroke-width:2px,color:#fff,rx:5px,ry:5px;\n"
        "   classDef default fill:#1e293b,stroke:#334155,stroke-width:1px,color:#e2e8f0;\n"
        "8. Only output the raw Mermaid code inside a ```mermaid code block. No conversational text."
    )
    
    # We give the LLM the list of files and detected frameworks to deduce the architecture
    frameworks_str = ", ".join(repo.get("frameworks", []))
    languages_str = ", ".join(repo.get("languages", {}).keys())
    
    # Increase the file sample size since Gemini Flash has a large context window
    files_sample = "\n".join(file_list[:400])
    
    user_prompt = (
        f"Repository: {repo['owner']}/{repo['name']}\n"
        f"Languages: {languages_str}\n"
        f"Frameworks Detected: {frameworks_str}\n\n"
        f"Codebase Structure (Paths):\n{files_sample}\n\n"
        "Analyze the provided file paths and frameworks. Deduce the system's high-level architecture. "
        "Create a beautifully styled GitDiagram-style flowchart that shows the interactions between the main UI, the API/Backend services, "
        "the data storage layers, and any configuration/deployment tools. Remember to apply the custom classDefs to make it look visually stunning."
    )
    
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        raw_content = resp.content
        if isinstance(raw_content, list):
            content = "".join([c.get("text", "") for c in raw_content if isinstance(c, dict)])
        else:
            content = str(raw_content)
            
        content = content.strip()
        
        # Extract the mermaid code block if present
        if "```mermaid" in content:
            content = content.split("```mermaid")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        return content
        
    except Exception as e:
        logger.error(f"Failed to generate architecture diagram: {e}")
        # Fallback to a simple static diagram
        return f"graph TD\n    A[{repo['name']}] --> B[Error Generating Diagram]\n    B --> C[{str(e)}]"
