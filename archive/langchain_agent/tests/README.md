# Archived tests for `langchain_agent`

Moved out of `backend/tests/` during dsh 全切 so pytest/CI on the default path
does not import `app.reasoning.langchain_agent` (package now at
`archive/langchain_agent/`).

| Location | Former location |
|---|---|
| `archive/langchain_agent/tests/reasoning/*.py` | `backend/tests/reasoning/` |
| `archive/langchain_agent/tests/*.py` | `backend/tests/` (top-level) |

Live tests that only had a few langchain_agent assertions were trimmed in place
(`test_kg_search`, `test_tools_functional`, `test_embedding`, `test_graph_reasoning`,
`test_v2_architecture`) rather than fully archived.

Do not add these paths back to pytest collection unless the package is restored.
