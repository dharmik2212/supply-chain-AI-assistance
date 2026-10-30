import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings

load_dotenv()

# Active fast LLM on Groq (Free Cloud, 0 RAM, 0 Disk)
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
FALLBACK_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

def get_llm(model_id: str = DEFAULT_GROQ_MODEL, max_tokens: int = 600) -> BaseChatModel:
    """
    Returns ChatGroq using the requested model (defaults to qwen/qwen3.8-27b).
    Explicit max_tokens prevents exceeding Groq free tier's 1000 Output Tokens Per Minute (OTPM) limit.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError(
            "GROQ_API_KEY not found in .env file. "
            "Please ensure GROQ_API_KEY=gsk_... is added to your .env file."
        )

    return ChatGroq(
        model_name=model_id,
        api_key=groq_api_key,
        max_tokens=max_tokens,
        temperature=0.1,
    )

def get_embeddings(model_id: str = DEFAULT_EMBEDDING_MODEL) -> Embeddings:
    """
    Returns Hugging Face embeddings running locally.
    Defaults to sentence-transformers/all-MiniLM-L6-v2 (80 MB, works 100% offline).
    """
    hf_token = os.getenv("HUGGINGFACEHUB_API_TOKEN")
    model_kwargs = {"device": "cpu"}
    if hf_token:
        model_kwargs["token"] = hf_token

    return HuggingFaceEmbeddings(
        model_name=model_id,
        model_kwargs=model_kwargs,
        encode_kwargs={"normalize_embeddings": True},
    )
