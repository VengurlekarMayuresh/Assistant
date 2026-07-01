import { mermaidAPI } from 'mermaid';
import mermaid from 'mermaid';

const code = `graph TD
    subgraph Frontend_SPA ["Frontend SPA (Vite/React)"]
        frontend_src_main_jsx(("Entry Point<br/>React Root<br/>[main.jsx]")):::frontend
        frontend_src_App_jsx["App Shell<br/>Router & Layout<br/>[App.jsx]"]:::frontend
    end`;

async function test() {
    try {
        await mermaid.parse(code);
        console.log("OK");
    } catch(e) {
        console.log("FAIL", e);
    }
}
test();
