"""
resolve_variable — DeerFlow 风格变量解析器（增强版）

功能：
1. 动态导入模块属性：`"package.module:var_name"`
2. 环境变量插值：`"$ENV_VAR"` 或 `"${ENV_VAR}"`
3. 类型验证：可选 expected_type isinstance() 检查

参考 deerflow/reflection/resolvers.py，添加环境变量支持。
"""

from __future__ import annotations

import os
import re
import threading
from importlib import import_module
from typing import TypeVar

T = TypeVar("T")

__all__ = ["resolve_variable", "resolve_class"]

# 缓存（避免每次启动重复解析同名路径）
_cache: dict[str, object] = {}
_cache_lock = threading.RLock()

# 环境变量插值正则：${VAR} / $VAR（词边界）
_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

# ── 环境变量插值 ──────────────────────────────────────────────────────


def _expand_env(value: str) -> str:
    """
    递归替换字符串中的 $VAR / ${VAR} 为环境变量值。
    未定义的变量替换为空字符串。
    """

    def _replace(match: re.Match) -> str:
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, "")

    result = _ENV_PATTERN.sub(_replace, value)
    # 递归处理（以防嵌套插值）
    if _ENV_PATTERN.search(result):
        result = _expand_env(result)
    return result


# ── 核心解析 ─────────────────────────────────────────────────────────


def resolve_variable[T](
    variable_path: str,
    expected_type: type[T] | tuple[type, ...] | None = None,
) -> T:
    """
    从路径字符串解析变量（支持环境变量插值）。

    Args:
        variable_path: 路径字符串，格式为 "module.path:name"。
            use 字段中的 $ENV_VAR 或 ${ENV_VAR} 会自动展开。
            示例：
              "app.reasoning.tools.market_data.kline:get_kline"
              "langchain_openai:ChatOpenAI"
        expected_type: 可选的类型验证，resolved 后做 isinstance() 检查。

    Returns:
        解析得到的变量（函数、类、对象均可）。

    Raises:
        ImportError: 模块路径无效或属性不存在。
        ValueError: 类型验证失败。
    """
    # 环境变量插值
    expanded = _expand_env(variable_path)

    # 缓存
    with _cache_lock:
        if expanded in _cache:
            result = _cache[expanded]
            if expected_type is not None and not isinstance(result, expected_type):
                type_name = (
                    expected_type.__name__
                    if isinstance(expected_type, type)
                    else " or ".join(t.__name__ for t in expected_type)
                )
                raise ValueError(
                    f"{variable_path} resolved to {expanded} is not an instance of {type_name}, "
                    f"got {type(result).__name__}"
                )
            return result  # type: ignore[return-value]

    # 解析 module:name
    try:
        module_path, variable_name = expanded.rsplit(":", 1)
    except ValueError as err:
        raise ImportError(
            f"{variable_path} doesn't look like a variable path. "
            "Example: parent_package_name.sub_package_name.module_name:variable_name"
        ) from err

    # 动态导入模块
    try:
        module = import_module(module_path)
    except ImportError as err:
        module_root = module_path.split(".", 1)[0]
        err_name = getattr(err, "name", None)
        if isinstance(err, ModuleNotFoundError) or err_name == module_root:
            missing = module_root.replace("_", "-")
            hint = (
                f"Missing dependency '{missing}'. "
                f"Install it with `uv add {missing}` (or `pip install {missing}`), "
                "then restart the backend."
            )
            raise ImportError(f"Could not import module {module_path}. {hint}") from err
        raise ImportError(f"Error importing module {module_path}: {err}") from err

    # 获取属性
    try:
        variable = getattr(module, variable_name)
    except AttributeError as err:
        raise ImportError(f"Module {module_path} does not define a {variable_name} attribute") from err

    # 类型验证
    if expected_type is not None and not isinstance(variable, expected_type):
        type_name = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else " or ".join(t.__name__ for t in expected_type)
        )
        raise ValueError(
            f"{variable_path} resolved to {expanded} is not an instance of {type_name}, got {type(variable).__name__}"
        )

    # 缓存结果
    with _cache_lock:
        _cache[expanded] = variable

    return variable  # type: ignore[return-value]


def resolve_class[T](
    class_path: str,
    base_class: type[T] | None = None,
) -> type[T]:
    """
    从路径字符串解析类（带基类验证）。

    与 resolve_variable 类似，但强制要求解析结果为类，并可选验证基类。

    Args:
        class_path: 格式为 "module.path:ClassName"
        base_class: 可选，验证解析出的类是否为该基类的子类

    Returns:
        解析得到的类类型
    """
    cls = resolve_variable(class_path, expected_type=type)

    if not isinstance(cls, type):
        raise ValueError(f"{class_path} is not a class")

    if base_class is not None and not issubclass(cls, base_class):
        raise ValueError(f"{class_path} is not a subclass of {base_class.__name__}")

    return cls  # type: ignore[return-value]


def clear_cache() -> None:
    """清空解析缓存（主要用于测试）"""
    with _cache_lock:
        _cache.clear()
