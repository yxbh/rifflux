from __future__ import annotations

import hashlib
import re

import numpy as np

TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")


def hash_embed(text: str, dim: int = 384) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    tokens = TOKEN_RE.findall(text.lower())
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = -1.0 if digest[4] & 1 else 1.0
        weight = 1.0 + (digest[5] / 255.0)
        vec[index] += np.float32(sign * weight)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32)
