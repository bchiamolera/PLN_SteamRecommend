"""Conservative clause-level aspect observations, not generated factual claims."""
import re
from collections import defaultdict
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

VERSION = "aspects-clauses-v3"
ASPECTS = {
    "gameplay": {"gameplay", "combat", "mechanic", "crafting"},
    "story": {"story", "plot", "narrative", "writing", "dialogue"},
    "graphics": {"graphic", "visual", "animation", "texture"},
    "audio": {"audio", "sound", "soundtrack", "music", "voice"},
    "controls": {"control", "keyboard", "controller", "input"},
    "performance": {"performance", "framerate", "optimization", "stutter"},
    "bugs": {"bug", "glitch", "crash"},
    "multiplayer": {"multiplayer", "coop", "co-op", "server", "matchmaking"},
    "difficulty": {"difficulty", "challenge", "balance"},
    "replayability": {"replayability", "replay", "replayvalue"},
    "value": {"price", "value", "cost", "money"},
}
WORD_ASPECT = {word: aspect for aspect, words in ASPECTS.items() for word in words}
SPLIT = re.compile(r"\b(?:but|however|yet|whereas|although|and)\b|;", re.I)
FORMS = {form for word in WORD_ASPECT for form in (word, word + "s", word + "es", word[:-1] + "ies" if word.endswith("y") else word)}
CANDIDATE = re.compile(r"\b(?:" + "|".join(re.escape(word) for word in sorted(FORMS)) + r")\b", re.I)
SENTENCES = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")

def candidate_clauses(text):
    """Cheap lexical gate: parse only original-text clauses mentioning an aspect."""
    for sentence in SENTENCES.finditer(text):
        for clause in SPLIT.split(sentence.group()):
            clause = clause.strip()
            if clause and CANDIDATE.search(clause):
                yield clause

class AspectAnalyzer:
    def __init__(self, nlp=None):
        if nlp is None:
            import spacy
            try:
                nlp = spacy.load("en_core_web_sm", disable=["ner"])
            except OSError:
                raise RuntimeError("Missing spaCy model. Run: python -m spacy download en_core_web_sm") from None
        self.nlp = nlp
        self.sentiment = SentimentIntensityAnalyzer()

    def from_doc(self, doc):
        observations = []
        for sentence in doc.sents:
            text = sentence.text
            offset = sentence.start_char
            start = 0
            boundaries = [(m.start(), m.end()) for m in SPLIT.finditer(text)] + [(len(text), len(text))]
            for end, next_start in boundaries:
                raw = text[start:end]
                left = len(raw) - len(raw.lstrip())
                excerpt = raw.strip()
                clause = doc.char_span(offset + start + left, offset + end - (len(raw) - len(raw.rstrip())), alignment_mode="contract") if excerpt else None
                start = next_start
                if clause is None:
                    continue
                mentions = [(t, WORD_ASPECT.get(t.lemma_.lower()) or WORD_ASPECT.get(t.lower_)) for t in clause]
                mentions = [(t, a) for t, a in mentions if a]
                aspects = {a for _, a in mentions}
                # Multiple distinct aspects in one unresolved clause are ambiguous.
                if len(aspects) != 1:
                    continue
                # Avoid hypothetical praise, comparisons to other titles, and
                # 'too difficult to be fun' constructions requiring scope resolution.
                if any(t.lower_ in {"if", "would", "could", "wish", "too", "than", "compared"} or t.tag_ in {"JJR", "RBR"} for t in clause):
                    continue
                # Opinion must modify the aspect or its own predicate. A broad
                # dependency-radius search can incorrectly borrow nearby praise.
                opinions = []
                for token, _ in mentions:
                    opinions.extend(t for t in token.children if t.dep_ == "amod")
                    if token.dep_ in {"nsubj", "nsubjpass", "dobj", "obj"}:
                        opinions.append(token.head)
                        if token.dep_ in {"nsubj", "nsubjpass"}:
                            opinions.extend(t for t in token.head.children if t.dep_ in {"acomp", "attr", "oprd"})
                if not any(t.lower_ in self.sentiment.lexicon and clause.start <= t.i < clause.end for t in opinions):
                    continue
                scores = self.sentiment.polarity_scores(excerpt)
                # Abstain on clauses with competing positive and negative evidence.
                if scores["pos"] and scores["neg"]:
                    continue
                compound = scores["compound"]
                if abs(compound) < 0.05:
                    continue
                observations.append({"aspect": next(iter(aspects)), "polarity": "positive" if compound > 0 else "negative", "excerpt": excerpt, "score": compound})
        return observations

    def analyze(self, text):
        return next(self.pipe([text]))

    def pipe(self, texts):
        texts = list(texts)
        results = [[] for _ in texts]
        candidates = ((clause, index) for index, text in enumerate(texts) for clause in candidate_clauses(text))
        for doc, index in self.nlp.pipe(candidates, as_tuples=True, batch_size=128):
            results[index].extend(self.from_doc(doc))
        yield from results

def aggregate(observations):
    """Input: (review_id, observations). Count distinct reviews and retain evidence."""
    groups = defaultdict(dict)
    for review_id, points in observations:
        for point in points:
            groups[point["aspect"], point["polarity"]].setdefault(review_id, point)
    result = {"positive": [], "negative": []}
    for (aspect, polarity), reviews in groups.items():
        if len(reviews) < 2:
            continue
        result[polarity].append({
            "aspect": aspect, "support_count": len(reviews),
            "evidence": [{"review_id": rid, "excerpt": p["excerpt"]} for rid, p in list(reviews.items())[:3]],
        })
    for polarity in result:
        result[polarity] = sorted(result[polarity], key=lambda p: (-p["support_count"], p["aspect"]))[:5]
    return result
