"""Shared parsing layer (`parse` / `extract` / `normalize`).

**Not private to Agent 1**: Agent 3's raw mode also needs `parse`, and "run only the requirements
check" also needs `extract`. If each side grew its own copy, the same PDF would be split into
different blocks and a demo would show "two scans of one document, two conclusions" with no
explanation.
"""