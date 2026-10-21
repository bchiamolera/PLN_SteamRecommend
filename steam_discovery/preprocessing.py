import unicodedata
from functools import lru_cache
from nltk.corpus import stopwords
from nltk.tokenize import TweetTokenizer

VERSION = "english-tweet-negations-v1"
TOKENIZER = TweetTokenizer(preserve_case=True, reduce_len=False, strip_handles=False)
APOSTROPHES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'"})
NEGATIONS = {"no", "not", "nor", "never", "neither", "nothing", "nobody", "without", "cannot", "n't"}

def tokenizar(text):
    return TOKENIZER.tokenize(text)

def normalizar(tokens):
    return [unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", t).translate(APOSTROPHES).lower()) for t in tokens]

@lru_cache(maxsize=1)
def english_stopwords():
    try:
        words = stopwords.words("english")
    except LookupError:
        raise RuntimeError("Missing NLTK stopwords. Run: python -m nltk.downloader stopwords") from None
    return {w for w in normalizar(words) if w not in NEGATIONS and not w.endswith("n't")}

def remover_stopwords(tokens):
    return [t for t in tokens if t not in english_stopwords()]

def preprocess(text):
    return remover_stopwords(normalizar(tokenizar(text)))
