"""Lock only the installed runtime dependency tree, not test tools."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement

seen = {}
todo = ["fastapi", "uvicorn", "httpx", "feedparser"]
while todo:
    dist = distribution(todo.pop())
    name = dist.metadata["Name"]
    if name in seen:
        continue
    seen[name] = dist.version
    for raw in dist.requires or []:
        req = Requirement(raw)
        if not req.marker or req.marker.evaluate({"extra": ""}):
            todo.append(req.name)
Path("requirements.txt").write_text(
    "\n".join(name + "==" + version for name, version in sorted(seen.items(), key=lambda pair: pair[0].lower())) + "\n",
    encoding="utf-8",
)
print("Pinned runtime dependencies:", len(seen))
