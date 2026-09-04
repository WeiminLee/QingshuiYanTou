from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
import os

MODEL_PATH = os.getenv('EMBEDDING_MODEL_PATH', '/data/models/bge-m3')
model = SentenceTransformer(MODEL_PATH, device=os.getenv('EMBEDDING_DEVICE', 'cpu'))
app = FastAPI(title='bge-m3 Embedding API')

class Req(BaseModel):
    input: str | list[str]
    model: str = 'bge-m3'

@app.get('/v1/models')
def models():
    return {'object': 'list', 'data': [{'id': 'bge-m3', 'object': 'model', 'owned_by': 'BAAI'}]}

@app.post('/v1/embeddings')
def embeddings(req: Req):
    texts = [req.input] if isinstance(req.input, str) else req.input
    vec = model.encode(texts, normalize_embeddings=True).tolist()
    return {'object': 'list', 'data': [{'object': 'embedding', 'index': i, 'embedding': v} for i, v in enumerate(vec)], 'model': 'bge-m3', 'usage': {'prompt_tokens': 0, 'total_tokens': 0}}
