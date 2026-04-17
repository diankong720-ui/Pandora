from __future__ import annotations

"""
Tool 3 — SQL Execution

This module wires together the WarehouseClient, cache, and admission control
into the single LLM-callable SQL execution tool.

The LLM calls execute_sql() with a fully formed SQL string.
This function handles:
  - admission control (checks warehouse load state)
  - cache lookup (returns cached result if available and allowed)
  - live execution (calls client.execute() on admission)
  - cache write (persists live results for future lookups)
  - load tracking (records outcome to update admission state)

The LLM receives a plain dict describing the outcome. It decides
what the result means for the current hypothesis — this function does not.
"""

import re
import time
from typing import Any

from runtime.interface import WarehouseClient
from runtime.admission import check_admission, record_query_outcome, get_warehouse_snapshot
from runtime.cache import lookup_cache, write_cache, load_cached_rows
from runtime.persistence import append_execution_log
from runtime.sql_helpers import render_parameterized_sql


SAFE_TABLE_WHITELIST: list[str] | None = None  # None = allow all tables


def set_table_whitelist(tables: list[str] | None) -> None:
    """
    Optionally restrict which tables the LLM may query.
    Call once at startup with your allowed table list.
    Pass None to disable the whitelist.
    """
    global SAFE_TABLE_WHITELIST
    SAFE_TABLE_WHITELIST = tables


def _normalize_sql_for_validation(sql: str) -> str:
    """Strip SQL comments and collapse whitespace before keyword scanning."""
    sql = re.sub(r'/\*.*?\*/', ' ', sql, flags=re.DOTALL)  # block comments
    sql = re.sub(r'--[^\n]*', ' ', sql)                     # line comments
    return re.sub(r'\s+', ' ', sql).strip().upper()


def _validate_sql(sql: str) -> str | None:
    """Return an error string if the SQL is unsafe, else None."""
    normalized = _normalize_sql_for_validation(sql)

    statements = [part.strip() for part in sql.split(";") if part.strip()]
    if len(statements) > 1:
        return "SQL must contain exactly one statement."

    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE")
    for keyword in forbidden:
        # Match at start, after a semicolon, or after whitespace — with word boundary.
        # This catches semicolon chains, newline-separated statements, and comment-embedded keywords.
        if re.search(rf'(?:^|;|\s){re.escape(keyword)}\b', normalized):
            return f"SQL contains forbidden keyword: {keyword}"

    if SAFE_TABLE_WHITELIST is not None:
        # Handle schema-qualified names (schema.table) — capture only the table part.
        referenced = set(re.findall(r"FROM\s+[`\"]?(?:\w+\.)?(\w+)[`\"]?", normalized))
        referenced |= set(re.findall(r"JOIN\s+[`\"]?(?:\w+\.)?(\w+)[`\"]?", normalized))
        blocked = referenced - {t.upper() for t in SAFE_TABLE_WHITELIST}
        if blocked:
            return f"Query references tables not in the whitelist: {', '.join(blocked)}"

    return None


def _resolve_cache_behavior(cache_policy: str) -> dict[str, bool]:
    if cache_policy == "bypass":
        return {
            "allow_cache_lookup": False,
            "allow_cache_fallback": False,
            "require_cache_hit": False,
        }
    if cache_policy == "allow_read":
        return {
            "allow_cache_lookup": True,
            "allow_cache_fallback": True,
            "require_cache_hit": False,
        }
    if cache_policy == "require_read":
        return {
            "allow_cache_lookup": True,
            "allow_cache_fallback": False,
            "require_cache_hit": True,
        }
    raise ValueError(f"Unsupported cache_policy: {cache_policy}")


def execute_sql(
    client: WarehouseClient,
    sql: str,
    *,
    output_name: str = "result",
    cost_class: str = "standard",
    allow_cache: bool = True,
    params: list[Any] | None = None,
    timeout: float = 30.0,
    max_rows: int = 10_000,
    max_cache_age_seconds: float | None = None,
) -> dict[str, Any]:
    """
    LLM-callable SQL execution tool.

    The LLM must provide the complete SQL. This function will not rewrite,
    infer joins, or fill in missing filters.

    Args:
        client:                 Initialised WarehouseClient.
        sql:                    The exact SQL to execute (may contain %s placeholders).
        output_name:            Identifier for this query result in the investigation record.
        cost_class:             "cheap" (scalar) or "standard" (GROUP BY / JOIN).
        allow_cache:            Whether a cache hit may substitute for live execution.
        params:                 Optional positional parameters for %s placeholders in sql.
        timeout:                Per-query timeout in seconds.
        max_rows:               Truncate result to this many rows.
        max_cache_age_seconds:  If set, reject cache entries older than this many seconds.

    Returns a plain dict with:
        status:       "success" | "cached" | "degraded_to_cache" |
                      "blocked" | "failed" | "timeout"
        output_name:  Echo of the output_name argument.
        rows_preview: First 10 rows (or [] on failure).
        row_count:    Total rows returned.
        cost_class:   Echo of cost_class.
        warehouse_snapshot: Current load state snapshot.
        error:        Error message string, or null.
    """
    rendered_sql = render_parameterized_sql(sql, params) if params else sql
    result = _execute_sql_detailed(
        client=client,
        sql=rendered_sql,
        output_name=output_name,
        cost_class=cost_class,
        cache_policy="allow_read" if allow_cache else "bypass",
        queue_once_allowed=False,
        workspace="default",
        timeout=timeout,
        max_rows=max_rows,
        max_cache_age_seconds=max_cache_age_seconds,
    )
    return _legacy_result(result)

def execute_query_request(
    client: WarehouseClient,
    request: dict[str, Any],
    *,
    slug: str | None = None,
    contract_id: str | None = None,
    round_number: int | None = None,
    timeout: float = 30.0,
    max_rows: int = 10_000,
    max_cache_age_seconds: float | None = None,
) -> dict[str, Any]:
    """
    Execute a full QueryExecutionRequest without rewriting or inferring SQL.
    """
    required_fields = (
        "query_id",
        "description",
        "sql",
        "workspace",
        "output_name",
        "cache_policy",
        "queue_once_allowed",
        "cost_class",
    )
    missing = [field for field in required_fields if field not in request]
    if missing:
        raise ValueError(f"QueryExecutionRequest missing required fields: {', '.join(missing)}")

    detailed = _execute_sql_detailed(
        client=client,
        sql=request["sql"],
        output_name=request["output_name"],
        cost_class=request["cost_class"],
        cache_policy=request["cache_policy"],
        queue_once_allowed=bool(request["queue_once_allowed"]),
        workspace=str(request["workspace"]),
        timeout=timeout,
        max_rows=max_rows,
        max_cache_age_seconds=max_cache_age_seconds,
    )
    result = {
        "query_id": request["query_id"],
        "description": request["description"],
        "status": detailed["status"],
        "rows_preview": detailed["rows_preview"],
        "cost_class": detailed["cost_class"],
        "source": detailed["source"],
        "notes": detailed["notes"],
    }
    if slug:
        append_execution_log(
            slug,
            {
                "query_id": request["query_id"],
                "description": request["description"],
                "contract_id": contract_id,
                "round_number": round_number,
                "workspace": request["workspace"],
                "output_name": request["output_name"],
                "status": detailed["status"],
                "source": detailed["source"],
                "warehouse_snapshot": detailed["warehouse_snapshot"],
                "error": detailed["error"],
                "executed_at": time.time(),
                "cache_policy": request["cache_policy"],
                "queue_once_allowed": bool(request["queue_once_allowed"]),
                "cache_hit": detailed["cache_hit"],
                "notes": detailed["notes"],
            },
        )
    return result


def _execute_sql_detailed(
    *,
    client: WarehouseClient,
    sql: str,
    output_name: str,
    cost_class: str,
    cache_policy: str,
    queue_once_allowed: bool,
    workspace: str,
    timeout: float,
    max_rows: int,
    max_cache_age_seconds: float | None,
) -> dict[str, Any]:
    cache_behavior = _resolve_cache_behavior(cache_policy)

    validation_error = _validate_sql(sql)
    if validation_error:
        notes = ["validation_blocked"]
        if queue_once_allowed:
            notes.append("queue not supported")
        return _result(
            status="blocked",
            output_name=output_name,
            cost_class=cost_class,
            rows=[],
            error=validation_error,
            client=client,
            source="live",
            cache_hit=False,
            notes=notes,
            workspace=workspace,
        )

    hit = None
    if cache_behavior["allow_cache_lookup"]:
        hit = lookup_cache(
            client.identity,
            sql,
            max_age_seconds=max_cache_age_seconds,
        )
        if hit["status"] == "hit":
            rows = load_cached_rows(
                client.identity,
                sql,
                max_age_seconds=max_cache_age_seconds,
            ) or []
            status = "cached"
            return _result(
                status=status,
                output_name=output_name,
                cost_class=cost_class,
                rows=rows,
                error=None,
                client=client,
                source="cache",
                cache_hit=True,
                notes=[],
                workspace=workspace,
            )
        if cache_behavior["require_cache_hit"]:
            notes = ["cache required but no usable cache entry was found"]
            return _result(
                status="blocked",
                output_name=output_name,
                cost_class=cost_class,
                rows=[],
                error="Cache policy require_read blocked live execution because no usable cache entry exists.",
                client=client,
                source="cache",
                cache_hit=False,
                notes=notes,
                workspace=workspace,
            )

    decision = check_admission(
        cost_class,
        allow_cache_fallback=cache_behavior["allow_cache_fallback"],
    )

    if not decision.allowed:
        if decision.mode == "cache_only" and cache_behavior["allow_cache_lookup"]:
            cached_rows = load_cached_rows(
                client.identity,
                sql,
                max_age_seconds=max_cache_age_seconds,
            )
            if cached_rows is not None:
                return _result(
                    status="degraded_to_cache",
                    output_name=output_name,
                    cost_class=cost_class,
                    rows=cached_rows,
                    error=None,
                    client=client,
                    source="cache",
                    cache_hit=True,
                    notes=["live execution degraded to cache because of warehouse admission"],
                    workspace=workspace,
                )
        notes = []
        source = "cache" if decision.mode == "cache_only" else "live"
        if queue_once_allowed:
            notes.append("queue not supported")
        return _result(
            status="blocked",
            output_name=output_name,
            cost_class=cost_class,
            rows=[],
            error=decision.reason,
            client=client,
            source=source,
            cache_hit=False,
            notes=notes,
            workspace=workspace,
        )

    query_result = client.execute(sql, timeout=timeout, max_rows=max_rows)
    record_query_outcome(timed_out=query_result.timed_out)

    if query_result.ok:
        write_cache(client.identity, sql, query_result.rows, query_result.columns)
        return _result(
            status="success",
            output_name=output_name,
            cost_class=cost_class,
            rows=query_result.rows,
            error=None,
            client=client,
            source="live",
            cache_hit=False,
            notes=[],
            workspace=workspace,
        )

    status = "timeout" if query_result.timed_out else "failed"
    return _result(
        status=status,
        output_name=output_name,
        cost_class=cost_class,
        rows=[],
        error=query_result.error,
        client=client,
        source="live",
        cache_hit=False,
        notes=[],
        workspace=workspace,
    )


def _result(
    *,
    status: str,
    output_name: str,
    cost_class: str,
    rows: list[dict[str, Any]],
    error: str | None,
    client: WarehouseClient,
    source: str,
    cache_hit: bool,
    notes: list[str],
    workspace: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "output_name": output_name,
        "rows_preview": rows[:10],
        "row_count": len(rows),
        "cost_class": cost_class,
        "source": source,
        "cache_hit": cache_hit,
        "notes": notes,
        "workspace": workspace,
        "warehouse_snapshot": get_warehouse_snapshot(),
        "error": error,
    }


def _legacy_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result["status"],
        "output_name": result["output_name"],
        "rows_preview": result["rows_preview"],
        "row_count": result["row_count"],
        "cost_class": result["cost_class"],
        "warehouse_snapshot": result["warehouse_snapshot"],
        "error": result["error"],
    }
