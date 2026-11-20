"""Cheap local text matching: the first (free, instant) tier before any AI call."""
import re
from difflib import SequenceMatcher

STOPWORDS = {
    # grammar
    "the", "and", "for", "with", "that", "this", "from", "into", "about", "then", "also", "just", "some",
    "our", "your", "my", "its", "are", "was", "will", "can", "all", "any", "out", "off", "via", "per",
    # task-command verbs (they describe the action, not the work)
    "task", "add", "new", "need", "needs", "should", "must", "have", "has", "get", "got", "finish",
    "finished", "complete", "completed", "done", "start", "started", "work", "working", "make", "please",
    "remind", "todo", "pause", "remove", "delete", "cancel", "mark",
    # window chrome that shows up in titles
    "google", "chrome", "microsoft", "edge", "firefox", "mozilla", "brave", "visual", "studio", "code",
    "untitled", "tab", "home", "page", "pages", "window", "profile", "personal", "more",
    # URL noise
    "com", "www", "http", "https", "html", "htm", "org", "net", "index", "php", "aspx",
}


def tokens(text: str) -> set:
    out = set()
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(word) < 3 or word in STOPWORDS:
            continue
        if word.endswith("s") and len(word) > 4 and not word.endswith("ss"):
            word = word[:-1]
        out.add(word)
    return out


def task_tokens(title: str, project: str = None) -> set:
    return tokens(title) | tokens(project or "")


def overlap(task_toks: set, other_toks: set):
    """Return (score, hits): share of the task's words found in the other text."""
    if not task_toks or not other_toks:
        return 0.0, 0
    hits = len(task_toks & other_toks)
    return hits / len(task_toks), hits


def is_confident_link(score: float, hits: int, n_task_tokens: int) -> bool:
    # Short titles ("Fix auth bug" -> {fix, auth, bug}) can link on one strong word only if it's most of the title.
    if hits >= 2 and score >= 0.4:
        return True
    return hits >= 1 and n_task_tokens <= 2 and score >= 0.5


REF_STOPWORDS = STOPWORDS | {"checked", "fixed", "sorted", "resolved", "handled", "sent", "submitted", "shipped",
                              "wrapped", "also", "already", "just", "was", "were", "been", "them", "one", "ones",
                              "tasks", "thing", "things", "stuff", "part", "mean", "now", "today", "last"}


def _ref_words(text: str):
    """All words in order (incl. 1-2 letter ones, needed to rejoin "dp world" -> "dpworld")."""
    out = []
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if word.endswith("s") and len(word) > 4 and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def _similar(a: str, b: str) -> bool:
    """Speech-to-text tolerant: "tpworld"~"dpworld", "world" inside "dpworld", "eir"=="eirs"."""
    if a == b:
        return True
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return True
    return min(len(a), len(b)) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.8


def ref_score(query: str, target: str) -> float:
    """How well a spoken reference names a task. Spacing/spelling tolerant; scored against the shorter side
    so "the report" fully matches "Finish November financial report"."""
    qw, tw = _ref_words(query), _ref_words(target)
    q = {w for w in qw if len(w) >= 3 and w not in REF_STOPWORDS}
    t = {w for w in tw if len(w) >= 3 and w not in REF_STOPWORDS}
    q_pairs = {a + b for a, b in zip(qw, qw[1:])}
    t_pairs = {a + b for a, b in zip(tw, tw[1:])}
    if not t or not (q or q_pairs):
        return 0.0
    hits = sum(1 for w in q if any(_similar(w, x) for x in t | t_pairs))
    hits += sum(1 for p in q_pairs - q if len(p) >= 5 and any(_similar(p, x) for x in t))
    return min(1.0, hits / max(1, min(len(q) or 1, len(t))))


def task_text(task) -> str:
    """Everything a task can be called: title, project, and phrases learned from your corrections."""
    return f"{task.title} {task.project or ''} {getattr(task, 'aliases', '') or ''}"


def best_task_match(query: str, tasks, min_score: float = 0.0):
    """Find the open task a spoken reference ("the report", "dp world one") points at."""
    best, best_score = None, 0.0
    for task in tasks:
        score = ref_score(query, task_text(task))
        if score > best_score:
            best, best_score = task, score
    return (best, best_score) if best_score >= min_score else (None, best_score)


def all_task_matches(query: str, tasks, min_score: float = 0.5):
    return [t for t in tasks if ref_score(query, task_text(t)) >= min_score]


def normalize_title(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip()).strip(" .,!?;:")
    if not text:
        return ""
    return text[0].upper() + text[1:]



def vocabulary_terms(title: str):
    """Names worth teaching Whisper: acronyms (EIR, GGEA), Capitalised Names (Jebel Ali), codes (GDA6).
    Consecutive name-like words stay together ("DP World EIRs"); the sentence-opening verb is skipped."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'&-]*", title or "")
    if words and words[0][:1].isupper() and not words[0].isupper() and not any(ch.isdigit() for ch in words[0]):
        words = words[1:]

    def namey(w):
        return (w[:1].isupper() or any(ch.isdigit() for ch in w)) and w.lower() not in STOPWORDS

    terms, run = [], []
    for w in words + [""]:
        if w and namey(w):
            run.append(w)
            continue
        phrase = " ".join(run)
        if len(phrase) >= 3 or (phrase.isupper() and len(phrase) >= 2):
            terms.append(phrase)
        run = []
    return terms
