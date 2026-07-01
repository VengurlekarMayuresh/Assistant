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
        "production-quality system architecture diagram using Mermaid.js syntax. You must mimic the exact visual style of 'GitDiagram'.\n\n"
        "RULES FOR THE DIAGRAM:\n"
        "1. Use 'graph TD' direction.\n"
        "2. Group related components logically using 'subgraph' (e.g., 'subgraph Frontend SPA', 'subgraph Backend API', 'subgraph Data & Services').\n"
        "3. Within subgraphs, map the most important files or modules into nodes.\n"
        "4. **NODE SHAPES**: \n"
        "   - Entry points/Contexts should be stadiums (pill-shaped): `id([\"text\"])`\n"
        "   - Standard files/components should be rectangles: `id[\"text\"]`\n"
        "   - Databases should be cylinders: `id[(\"text\")]`\n"
        "   - External integrations should be hexagons: `id{{\"text\"}}`\n"
        "5. **NODE TEXT FORMAT**: Every node text MUST be enclosed in quotes and have exactly 3 lines separated by `<br/>`:\n"
        "   - Line 1: A friendly name (e.g., `SPA shell`)\n"
        "   - Line 2: A description/type (e.g., `React app`)\n"
        "   - Line 3: The exact filename in brackets (e.g., `[App.jsx]`)\n"
        "   Example: `frontend/src/App.jsx(\"SPA shell<br/>React app<br/>[App.jsx]\")`\n"
        "6. **NODE IDs**: The Node ID (before the shape brackets) MUST be the EXACT file path or folder path. For example, `backend/app/main.py` or `frontend/src`. Do not use generic IDs like `A` or `Node1` for files.\n"
        "7. Add meaningful edge labels indicating how things connect (e.g., `-->|calls|`, `-->|reads/writes|`, `-->|mounts|`).\n"
        "8. **CUSTOM STYLING**: Include these exact classDefs at the bottom of your graph and apply them to nodes using `:::className` syntax (e.g., `id[text]:::frontend`):\n"
        "   classDef frontend fill:#ffedd5,stroke:#fdba74,stroke-width:2px,color:#1f2937;\n"
        "   classDef backend fill:#dbeafe,stroke:#93c5fd,stroke-width:2px,color:#1f2937;\n"
        "   classDef database fill:#dcfce7,stroke:#86efac,stroke-width:2px,color:#1f2937;\n"
        "   classDef config fill:#f3f4f6,stroke:#d1d5db,stroke-width:2px,color:#1f2937;\n"
        "   classDef default fill:#ffffff,stroke:#e5e7eb,stroke-width:1px,color:#1f2937;\n"
        "9. Style your subgraphs with a light gray background by adding this to the bottom: `style SubgraphName fill:#f9fafb,stroke:#e5e7eb,stroke-width:1px,color:#374151` (Replace SubgraphName with the actual subgraph ID).\n"
        "10. Only output the raw Mermaid code inside a ```mermaid code block. No conversational text."
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
