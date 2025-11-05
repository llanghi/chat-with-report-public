# app.py — local RAG server (LlamaIndex + PyMuPDF) with FastAPI
import os
import glob
from pathlib import Path
from typing import Dict, List, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# LlamaIndex core + OpenAI adapters + file reader
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeWithScore
from llama_index.readers.file import PyMuPDFReader
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.embeddings.openai import OpenAIEmbedding

load_dotenv()

# === Config ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL_NAME", "gpt-4.1-mini")  # change to gpt-4o-mini, gpt-4.1, gpt-4o, etc.
DATA_DIR = "data"  # index all PDFs under data/ and data/sections/

SYSTEM_INSTRUCTIONS = (
    "You answer only from the provided report PDFs in the index. "
    "If the information is not present, say you cannot find it in the report. "
    "Always include exact page numbers from the source documents. "
    "When the question mentions a figure or table, rely on the text and captions in the PDFs."
)

# === FastAPI app ===
app = FastAPI(title="Chat with Report (Local RAG)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Build index on startup ===
_index: VectorStoreIndex = None  # type: ignore


def _discover_pdfs() -> List[str]:
    files = []
    files += glob.glob(os.path.join(DATA_DIR, "*.pdf"))
    files += glob.glob(os.path.join(DATA_DIR, "sections", "*.pdf"))
    # de-dup + stable order
    return sorted(list(set(files)))


def _load_docs(pdf_paths: List[str]):
    """
    Load PDFs via PyMuPDFReader and normalise metadata so each node carries:
      - file_name: short filename for display
      - page_cite: canonical page label (roman or arabic), from page_label/page_number/page
    """
    if not pdf_paths:
        raise RuntimeError("No PDFs found. Place your PDFs under data/ or data/sections/")

    reader = PyMuPDFReader()
    docs = []

    for p in pdf_paths:
        try:
            # Support both older/newer reader APIs
            try:
                loaded = reader.load_data(file_path=str(p))  # newer
            except Exception:
                loaded = reader.load(file_path=str(p))       # older

            for d in loaded:
                d.metadata = d.metadata or {}
                # short, friendly filename
                d.metadata["file_name"] = Path(p).name

                # normalise page label (keep roman numerals if present)
                page_label = (
                    d.metadata.get("page_label")
                    or d.metadata.get("page_number")
                    or d.metadata.get("page")
                    or d.metadata.get("page_index")
                )
                if page_label is not None:
                    d.metadata["page_cite"] = str(page_label)

                # keep legacy key for back-compat with any existing formatters
                d.metadata["source"] = d.metadata.get("source") or Path(p).name

            docs.extend(loaded)
        except Exception as e:
            print(f"Failed to load {p}: {e}")

    if not docs:
        raise RuntimeError("No text extracted from PDFs (are they scanned without OCR?)")
    return docs


def _init_index() -> VectorStoreIndex:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY in .env")

    # Model + embeddings config
    Settings.llm = LlamaOpenAI(model=MODEL, api_key=OPENAI_API_KEY, temperature=0)
    Settings.embed_model = OpenAIEmbedding(model="text-embedding-3-large", api_key=OPENAI_API_KEY)

    # Chunking
    Settings.node_parser = SentenceSplitter(chunk_size=900, chunk_overlap=150)

    pdfs = _discover_pdfs()
    print(f"Indexing PDFs: {pdfs}")
    docs = _load_docs(pdfs)

    # Build a simple in-memory vector index
    index = VectorStoreIndex.from_documents(docs, show_progress=True)
    return index


@app.on_event("startup")
def _on_startup():
    global _index
    if _index is None:
        _index = _init_index()
        print("Index ready.")


def _format_sources(nodes: List[NodeWithScore]) -> List[Dict[str, Any]]:
    out = []
    for n in nodes or []:
        # handle both NodeWithScore and raw Node
        node = getattr(n, "node", None) or n
        md = getattr(node, "metadata", {}) or {}

        # prefer our normalised keys, with fallbacks
        src = (
            md.get("file_name")
            or md.get("source")
            or (md.get("file_path") and Path(md["file_path"]).name)
            or "unknown.pdf"
        )
        page = (
            md.get("page_cite")
            or md.get("page_label")
            or md.get("page_number")
            or md.get("page")
            or md.get("page_index")
            or "?"
        )
        page = str(page)

        # short extract for display
        try:
            snippet = node.get_content(metadata_mode="none")  # newer API
        except Exception:
            snippet = getattr(node, "text", "") or ""
        snippet = snippet.strip()
        if len(snippet) > 360:
            snippet = snippet[:360] + "…"

        out.append({"source": src, "page": page, "snippet": snippet})
    return out


@app.post("/ask")
def ask(payload: Dict[str, str] = Body(...)):
    """
    Body: {"question": "your question"}
    """
    if _index is None:
        raise HTTPException(status_code=500, detail="Index not ready")

    q = (payload.get("question") or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Missing question")

    try:
        # Standard retrieval (stable citations). You can raise/lower top_k if needed.
        query_engine = _index.as_query_engine(
            similarity_top_k=14,
            response_mode="compact",
        )

        # Prepend system instruction to enforce grounding, keep prose output.
        full_prompt = (
            f"{SYSTEM_INSTRUCTIONS}\n\n"
            "Answer in 1–3 short paragraphs (no bullet points). "
            "Be concise, specific, and grounded in the report. "
            "Include exact page numbers at the end as: Pages: p.X; p.Y.\n\n"
            f"Question: {q}"
        )

        resp = query_engine.query(full_prompt)

        answer_text = str(resp).strip()
        sources = _format_sources(getattr(resp, "source_nodes", []) or [])

        # Add a consolidated pages line if we have citations
        if sources:
            pages = []
            for s in sources:
                label = f"{s['source']} p.{s['page']}"
                if label not in pages:
                    pages.append(label)
            answer_text = answer_text + "\n\nPages: " + "; ".join(pages)

        return {"answer": answer_text, "citations": sources}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QA error: {e}" )
