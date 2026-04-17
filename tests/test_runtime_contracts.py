from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime import (
    admission,
    cache,
    evaluation,
    final_answer,
    orchestration,
    persistence,
    schema_probe,
    tools,
)
from runtime.domain_pack_suggestions import persist_domain_pack_suggestions
from runtime.domain_packs import deterministic_slug, resolve_target_pack_id
from runtime.interface import QueryResult, WarehouseClient


class FakeClient(WarehouseClient):
    def __init__(self, *, identity: str = "fake://warehouse", quote_style: str = "raw") -> None:
        self._identity = identity
        self.quote_style = quote_style
        self.executed_sql: list[str] = []
        self.responses: dict[str, QueryResult] = {}

    @property
    def identity(self) -> str:
        return self._identity

    def quote_identifier(self, name: str) -> str:
        if self.quote_style == "mysql":
            return ".".join(f"`{part}`" for part in name.split("."))
        if self.quote_style == "ansi":
            return ".".join(f'"{part}"' for part in name.split("."))
        return name

    def execute(
        self,
        sql: str,
        *,
        timeout: float = 30.0,
        max_rows: int = 10_000,
    ) -> QueryResult:
        self.executed_sql.append(sql)
        return self.responses.get(sql, QueryResult(rows=[{"value": 1}], columns=["value"]))


class RuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="runtime-contracts-"))
        self.research_root = self.tempdir / "RESEARCH"
        persistence.RESEARCH_ROOT = self.research_root
        persistence.get_slug_root("probe")  # force resolve path under temp root
        cache.CACHE_ROOT = self.research_root / ".sql_cache"
        admission.STATE_FILE = self.research_root / ".warehouse_load_state.json"
        admission._tracker.recent = []
        admission._tracker.state = admission.LoadState.NORMAL
        tools.set_table_whitelist(None)

    def tearDown(self) -> None:
        admission._tracker.recent = []
        admission._tracker.state = admission.LoadState.NORMAL
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_query_execution_request_returns_contract_shape_and_logs(self) -> None:
        client = FakeClient()
        request = {
            "query_id": "q1",
            "description": "Read headline metric",
            "sql": "SELECT 1 AS value",
            "workspace": "default",
            "output_name": "headline_metric",
            "cache_policy": "bypass",
            "queue_once_allowed": False,
            "cost_class": "cheap",
        }

        result = tools.execute_query_request(
            client,
            request,
            slug="session_a",
            contract_id="round_1_audit",
            round_number=1,
        )

        self.assertEqual(
            result,
            {
                "query_id": "q1",
                "description": "Read headline metric",
                "status": "success",
                "rows_preview": [{"value": 1}],
                "cost_class": "cheap",
                "source": "live",
                "notes": [],
            },
        )
        execution_log = persistence.read_artifact("session_a", "execution_log.json")
        self.assertEqual(len(execution_log["entries"]), 1)
        self.assertEqual(execution_log["entries"][0]["query_id"], "q1")
        self.assertEqual(execution_log["entries"][0]["source"], "live")

    def test_allow_read_uses_cache_hit(self) -> None:
        client = FakeClient()
        cache.write_cache(client.identity, "SELECT 1 AS value", [{"value": 7}], ["value"])
        request = {
            "query_id": "q_cache",
            "description": "Reuse cache",
            "sql": "SELECT 1 AS value",
            "workspace": "default",
            "output_name": "cached_metric",
            "cache_policy": "allow_read",
            "queue_once_allowed": False,
            "cost_class": "cheap",
        }

        result = tools.execute_query_request(client, request)

        self.assertEqual(result["status"], "cached")
        self.assertEqual(result["source"], "cache")
        self.assertEqual(client.executed_sql, [])

    def test_require_read_without_cache_blocks_live_execution(self) -> None:
        client = FakeClient()
        request = {
            "query_id": "q_require",
            "description": "Require cache",
            "sql": "SELECT 2 AS value",
            "workspace": "default",
            "output_name": "cached_only_metric",
            "cache_policy": "require_read",
            "queue_once_allowed": False,
            "cost_class": "cheap",
        }

        result = tools.execute_query_request(client, request)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["source"], "cache")
        self.assertEqual(client.executed_sql, [])

    def test_bypass_blocks_under_degraded_load(self) -> None:
        client = FakeClient()
        admission._tracker.state = admission.LoadState.DEGRADED
        request = {
            "query_id": "q_live_only",
            "description": "Live only",
            "sql": "SELECT 3 AS value",
            "workspace": "default",
            "output_name": "live_only_metric",
            "cache_policy": "bypass",
            "queue_once_allowed": True,
            "cost_class": "standard",
        }

        result = tools.execute_query_request(client, request)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["source"], "live")
        self.assertIn("queue not supported", result["notes"])
        self.assertEqual(client.executed_sql, [])

    def test_round_bundle_persistence_matches_contract_layout(self) -> None:
        bundle_path = persistence.persist_round_bundle(
            "session_b",
            "round_1",
            {"contract_id": "round_1_audit"},
            [{"query_id": "q1", "status": "success"}],
            {"round_id": "round_1", "conclusion_state": "partial_answer_available"},
        )

        saved = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        self.assertEqual(saved["contract"]["contract_id"], "round_1_audit")
        self.assertEqual(saved["executed_queries"][0]["query_id"], "q1")
        self.assertEqual(saved["evaluation"]["round_id"], "round_1")

    def test_execute_investigation_contract_uses_formal_query_entrypoint(self) -> None:
        client = FakeClient()
        contract = {
            "contract_id": "round_1_audit",
            "round_number": 1,
            "queries": [
                {
                    "query_id": "q1",
                    "description": "Read metric",
                    "sql": "SELECT 1 AS value",
                    "workspace": "default",
                    "output_name": "metric_primary",
                    "cache_policy": "bypass",
                    "queue_once_allowed": False,
                    "cost_class": "cheap",
                }
            ],
        }

        executed_queries = orchestration.execute_investigation_contract(
            client,
            contract,
            slug="session_contract",
        )

        self.assertEqual(len(executed_queries), 1)
        self.assertEqual(executed_queries[0]["query_id"], "q1")
        self.assertEqual(executed_queries[0]["status"], "success")
        execution_log = persistence.read_execution_log("session_contract")
        self.assertEqual(execution_log["entries"][0]["contract_id"], "round_1_audit")

    def test_persist_round_evaluation_accepts_blocked_runtime_only_when_preconditions_hold(self) -> None:
        contract = {
            "contract_id": "round_1_audit",
            "round_number": 1,
        }
        executed_queries = [
            {
                "query_id": "q1",
                "description": "Blocked query",
                "status": "blocked",
                "rows_preview": [],
                "cost_class": "standard",
                "source": "live",
                "notes": ["queue not supported"],
            }
        ]
        blocked_eval = {
            "round_id": "round_1",
            "round_number": 1,
            "contract_id": "round_1_audit",
            "hypothesis_updates": [],
            "residual_update": {
                "explained_components": [],
                "revoked_components": [],
                "layer_explained_share": {
                    "audit": 0.0,
                    "demand": 0.0,
                    "value": 0.0,
                    "structure": 0.0,
                    "fulfillment": 0.0,
                },
                "current_unexplained_ratio": 1.0,
                "confidence_band": "low",
                "stalled_round_streak": 0,
                "negative_gain_streak": 0,
                "operator_gain_note": "Runtime blocked every decisive test.",
            },
            "residual_score": 100,
            "residual_band": "very_high",
            "open_questions": ["Can any admissible audit query run?"],
            "scores": {
                "scope_fidelity": 1,
                "evidence_strength": 0,
                "explanatory_power": 0,
                "contradiction_integrity": 1,
                "business_actionability": 0,
                "warehouse_burden": "high",
            },
            "recommended_next_action": "stop",
            "should_continue": False,
            "stop_reason": "runtime_blocked",
            "operator_gain": 0.0,
            "gain_direction": "flat",
            "confidence_shift": "down",
            "correction_mode": False,
            "conclusion_state": "blocked_runtime",
            "incompleteness_category": "warehouse_load",
        }

        path = evaluation.persist_round_evaluation(
            "session_eval",
            blocked_eval,
            contract=contract,
            executed_queries=executed_queries,
        )
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(saved["evaluation"]["conclusion_state"], "blocked_runtime")

    def test_finalize_session_requires_final_answer_to_match_latest_round_evaluation(self) -> None:
        contract = {"contract_id": "round_1_audit", "round_number": 1}
        executed_queries = [
            {
                "query_id": "q1",
                "description": "Metric query",
                "status": "success",
                "rows_preview": [{"value": 1}],
                "cost_class": "cheap",
                "source": "live",
                "notes": [],
            }
        ]
        evaluation.persist_round_evaluation(
            "session_final",
            {
                "round_id": "round_1",
                "round_number": 1,
                "contract_id": "round_1_audit",
                "hypothesis_updates": [],
                "residual_update": {
                    "explained_components": [],
                    "revoked_components": [],
                    "layer_explained_share": {
                        "audit": 1.0,
                        "demand": 0.0,
                        "value": 0.0,
                        "structure": 0.0,
                        "fulfillment": 0.0,
                    },
                    "current_unexplained_ratio": 0.4,
                    "confidence_band": "medium",
                    "stalled_round_streak": 0,
                    "negative_gain_streak": 0,
                    "operator_gain_note": "Audit closed; residual remains open.",
                },
                "residual_score": 45,
                "residual_band": "medium",
                "open_questions": ["Which driver explains the remaining gap?"],
                "scores": {
                    "scope_fidelity": 4,
                    "evidence_strength": 3,
                    "explanatory_power": 2,
                    "contradiction_integrity": 4,
                    "business_actionability": 2,
                    "warehouse_burden": "low",
                },
                "recommended_next_action": "stop",
                "should_continue": False,
                "stop_reason": "budget_exhausted",
                "operator_gain": 0.2,
                "gain_direction": "positive",
                "confidence_shift": "up",
                "correction_mode": False,
                "conclusion_state": "partial_answer_available",
                "incompleteness_category": "budget_exhausted",
            },
            contract=contract,
            executed_queries=executed_queries,
        )

        orchestration.finalize_session(
            "session_final",
            {
                "session_slug": "session_final",
                "conclusion_state": "partial_answer_available",
                "headline_conclusion": "Headline verified; key driver remains partially open.",
                "supported_claims": [],
                "contradictions": [],
                "residual_summary": {
                    "residual_score": 45,
                    "residual_band": "medium",
                    "current_unexplained_ratio": 0.4,
                    "open_questions": ["Which driver explains the remaining gap?"],
                },
                "correction_mode": False,
                "incompleteness_category": "budget_exhausted",
                "recommended_follow_up": [],
            },
        )
        saved = persistence.read_artifact("session_final", "final_answer.json")
        self.assertEqual(saved["conclusion_state"], "partial_answer_available")
        self.assertEqual(
            final_answer.get_latest_round_evaluation("session_final")["conclusion_state"],
            "partial_answer_available",
        )

    def test_execute_round_and_persist_closes_execution_to_evaluation_bundle(self) -> None:
        client = FakeClient()
        contract = {
            "contract_id": "round_1_audit",
            "round_number": 1,
            "queries": [
                {
                    "query_id": "q1",
                    "description": "Metric query",
                    "sql": "SELECT 1 AS value",
                    "workspace": "default",
                    "output_name": "metric_primary",
                    "cache_policy": "bypass",
                    "queue_once_allowed": False,
                    "cost_class": "cheap",
                }
            ],
        }
        evaluation_result = {
            "round_id": "round_1",
            "round_number": 1,
            "contract_id": "round_1_audit",
            "hypothesis_updates": [],
            "residual_update": {
                "explained_components": [],
                "revoked_components": [],
                "layer_explained_share": {
                    "audit": 1.0,
                    "demand": 0.0,
                    "value": 0.0,
                    "structure": 0.0,
                    "fulfillment": 0.0,
                },
                "current_unexplained_ratio": 0.5,
                "confidence_band": "medium",
                "stalled_round_streak": 0,
                "negative_gain_streak": 0,
                "operator_gain_note": "Round executed and persisted cleanly.",
            },
            "residual_score": 50,
            "residual_band": "medium",
            "open_questions": ["What is the next driver to test?"],
            "scores": {
                "scope_fidelity": 4,
                "evidence_strength": 3,
                "explanatory_power": 2,
                "contradiction_integrity": 4,
                "business_actionability": 2,
                "warehouse_burden": "low",
            },
            "recommended_next_action": "pivot",
            "should_continue": True,
            "stop_reason": "round_complete",
            "operator_gain": 0.15,
            "gain_direction": "positive",
            "confidence_shift": "up",
            "correction_mode": False,
            "conclusion_state": "partial_answer_available",
            "incompleteness_category": "",
        }

        bundle = orchestration.execute_round_and_persist(
            client,
            contract,
            evaluation_result,
            slug="session_round",
        )

        self.assertEqual(bundle["executed_queries"][0]["status"], "success")
        persisted = persistence.read_round_bundle("session_round", "round_1")
        self.assertEqual(persisted["evaluation"]["round_id"], "round_1")
        self.assertEqual(persisted["executed_queries"][0]["query_id"], "q1")

    def test_persist_domain_pack_suggestions_fills_target_pack_id_deterministically(self) -> None:
        persist_domain_pack_suggestions(
            "session_pack",
            {
                "session_slug": "session_pack",
                "active_pack_id": "generic",
                "target_pack_id": "",
                "suggested_updates": {
                    "taxonomy": {"problem_types": []},
                    "lexicon": {
                        "metrics": [],
                        "dimensions": [],
                        "business_aliases": [],
                        "unsupported_dimensions": [],
                    },
                    "performance_risks": [],
                    "driver_family_templates": {},
                    "domain_priors": {},
                    "operator_preferences": {},
                },
                "note": "Create a new company pack.",
            },
            business_label="New Company!!!",
        )
        saved = persistence.read_artifact("session_pack", "domain_pack_suggestions.json")
        self.assertEqual(saved["target_pack_id"], "new_company")

    def test_load_session_evidence_reads_explicit_artifacts(self) -> None:
        persistence.persist_artifact("session_c", "intent.json", {"intent_id": "i1"})
        persistence.persist_artifact("session_c", "final_answer.json", {"conclusion_state": "completed"})
        persistence.persist_round_bundle(
            "session_c",
            "round_1",
            {"contract_id": "c1"},
            [{"query_id": "q1", "status": "success"}],
            {"round_id": "round_1", "conclusion_state": "partial_answer_available"},
        )
        persistence.append_execution_log("session_c", {"query_id": "q1", "status": "success"})

        session_evidence = persistence.load_session_evidence("session_c")

        self.assertEqual(session_evidence["intent"]["intent_id"], "i1")
        self.assertEqual(session_evidence["final_answer"]["conclusion_state"], "completed")
        self.assertEqual(len(session_evidence["round_bundles"]), 1)
        self.assertEqual(len(session_evidence["execution_log"]["entries"]), 1)

    def test_domain_pack_resolution_reuses_existing_or_generates_deterministic_slug(self) -> None:
        existing = [{"pack_id": "acme_inc"}]
        self.assertEqual(resolve_target_pack_id("generic", "Acme Inc", existing), "acme_inc")
        self.assertEqual(deterministic_slug("New Company!!!"), "new_company")
        self.assertEqual(
            resolve_target_pack_id("generic", "New Company!!!", existing),
            "new_company",
        )

    def test_schema_probe_uses_client_specific_identifier_quoting(self) -> None:
        mysql_client = FakeClient(quote_style="mysql")
        ansi_client = FakeClient(quote_style="ansi")

        schema_probe.probe_table(mysql_client, "analytics.orders")
        schema_probe.probe_table(ansi_client, "analytics.orders")

        self.assertEqual(mysql_client.executed_sql[-1], "SELECT * FROM `analytics`.`orders` LIMIT 5")
        self.assertEqual(ansi_client.executed_sql[-1], 'SELECT * FROM "analytics"."orders" LIMIT 5')


if __name__ == "__main__":
    unittest.main()
