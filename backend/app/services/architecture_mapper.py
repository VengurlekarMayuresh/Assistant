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
    
    # We constrain the LLM to only output valid Mermaid code
    system_prompt = (
        "You are an expert Software Architect and Technical Communicator. "
        "Your task is to generate a high-level system architecture diagram using Mermaid.js syntax. "
        "Create a visual representation of how the components of this repository interact. "
        "Use 'graph TD' (flowchart) or 'classDiagram' whichever is most appropriate. "
        "Only output the raw Mermaid code inside a ```mermaid code block. Do NOT include any conversational text."
    )
    
    # We give the LLM the list of files and detected frameworks to deduce the architecture
    frameworks_str = ", ".join(repo.get("frameworks", []))
    languages_str = ", ".join(repo.get("languages", {}).keys())
    files_sample = "\n".join(file_list[:150])  # limit to top 150 files to save context
    
    user_prompt = (
        f"Repository: {repo['owner']}/{repo['name']}\n"
        f"Languages: {languages_str}\n"
        f"Frameworks Detected: {frameworks_str}\n\n"
        f"File Structure Sample:\n{files_sample}\n\n"
        "Based on this structure, generate a comprehensive Mermaid diagram showing the system architecture, "
        "key modules, databases, APIs, and their relationships. Focus on the high-level design."
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
