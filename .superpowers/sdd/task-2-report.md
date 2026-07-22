status: implemented and verified

files changed:
- backend/app/reasoning/context/schemas.py
- backend/app/reasoning/context/__init__.py
- backend/tests/reasoning/test_agent_context_schemas.py

commits:
- feat: add agent context dto schemas

tests run with outputs:
- `cd backend && pytest tests/reasoning/test_agent_context_schemas.py -q`
  - exit code: 127
  - output:
    ```text
    zsh:1: command not found: pytest
    ```
- `cd backend && uv run pytest tests/reasoning/test_agent_context_schemas.py -q`
  - red exit code: 2
  - output:
    ```text
    ==================================== ERRORS ====================================
    ________ ERROR collecting tests/reasoning/test_agent_context_schemas.py ________
    ImportError while importing test module '/Users/lwm/dev/QingshuiYanTou/backend/tests/reasoning/test_agent_context_schemas.py'.
    Hint: make sure your test modules/packages have valid Python names.
    Traceback:
    ../../../.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/lib/python3.13/importlib/__init__.py:88: in import_module
        return _bootstrap._gcd_import(name[level:], package, level)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    tests/reasoning/test_agent_context_schemas.py:1: in <module>
        from app.reasoning.context.schemas import AgentContextDTO, SignalMemoryDTO, UserSnapshotDTO
    E   ModuleNotFoundError: No module named 'app.reasoning.context.schemas'
    =========================== short test summary info ============================
    ERROR tests/reasoning/test_agent_context_schemas.py
    !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
    1 error in 0.04s
    ```
- `cd backend && uv run pytest tests/reasoning/test_agent_context_schemas.py -q`
  - green exit code: 0
  - output:
    ```text
    ...                                                                      [100%]
    3 passed in 0.01s
    ```

self-review:
- Implemented only the Task 2 DTO schemas and package exports.
- Preserved `portfolio_hits` compatibility on `SignalContextDTO`.
- Kept optional context fail-soft through nullable `user_snapshot`, nullable `signal_context`, and default factories.
- Did not modify `UserMemoryProvider`.
- Did not add LLM routing or external API requirements.
- Did not stage or include `backend/uv.lock`.

concerns:
- The literal specified `pytest` command is unavailable in this shell (`pytest: command not found`), so verification used `uv run pytest` with the same test path.
- `backend/uv.lock` was already untracked and remains outside this task.
