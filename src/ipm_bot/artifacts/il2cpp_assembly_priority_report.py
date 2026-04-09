"""Metadata-only prioritization of dumped assemblies inside an IL2CPP output catalog."""

from __future__ import annotations

import json
from pathlib import Path

from .shared import DEFAULT_OUTPUT_ROOT, make_run_id, utc_timestamp, write_json


def run_il2cpp_assembly_priority_report(
    catalog_dir: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    notes: str | None = None,
) -> Path:
    """Rank dumped assemblies by likely usefulness to the bot project."""

    resolved_catalog_dir = catalog_dir.resolve()
    if not resolved_catalog_dir.is_dir():
        raise FileNotFoundError(f"IL2CPP output catalog directory does not exist: {resolved_catalog_dir}")

    catalog_manifest_path = resolved_catalog_dir / "manifest.json"
    if not catalog_manifest_path.is_file():
        raise FileNotFoundError(
            f"IL2CPP output catalog is missing required manifest: {catalog_manifest_path}"
        )

    catalog_manifest = _load_catalog_manifest(catalog_manifest_path)
    dll_inventory = _extract_dll_inventory(catalog_manifest, catalog_manifest_path)
    assembly_entries = [_classify_assembly(item) for item in dll_inventory]
    assembly_entries.sort(
        key=lambda item: (-int(item["priority_score"]), str(item["assembly_name"]).lower())
    )

    report_id = make_run_id(f"il2cpp_assembly_priority_report_{resolved_catalog_dir.name}")
    report_dir = output_root / "il2cpp_assembly_priority_reports" / report_id
    report_dir.mkdir(parents=True, exist_ok=False)

    recommended_open_order = [
        entry["relative_path"]
        for entry in assembly_entries
        if int(entry["priority_score"]) >= 50
    ]

    manifest = {
        "schema_version": "il2cpp-assembly-priority-report-v1",
        "command_name": "il2cpp-assembly-priority-report",
        "created_at_utc": utc_timestamp(),
        "source_catalog_path": str(resolved_catalog_dir),
        "source_snapshot_path": _string_or_none(catalog_manifest.get("source_snapshot_path")),
        "notes": notes,
        "assembly_entries": assembly_entries,
        "recommended_open_order": recommended_open_order,
        "note": (
            "Metadata-only assembly prioritization. "
            "This report ranks dumped assemblies by likely investigation value for the bot "
            "without opening file contents or claiming runtime correctness."
        ),
    }
    write_json(report_dir / "manifest.json", manifest)

    summary_lines = [
        f"report_path: {report_dir.resolve()}",
        f"source_catalog_path: {resolved_catalog_dir}",
        f"source_snapshot_path: {manifest['source_snapshot_path'] or 'unknown'}",
        f"assembly_count: {len(assembly_entries)}",
        "",
        "recommended_open_order:",
    ]
    if recommended_open_order:
        summary_lines.extend(f"- {relative_path}" for relative_path in recommended_open_order)
    else:
        summary_lines.append("(no high-priority assemblies detected)")

    if notes:
        summary_lines.extend(["", "notes:", notes])

    summary_lines.extend(
        [
            "",
            "priority_guide:",
            "- Open DummyDll/Assembly-CSharp.dll first for game-owned classes, save schema anchors, and runtime field names.",
            "- Use Unity.LevelPlay.dll to understand rewarded-ad callback vocabulary and SDK-side event names.",
            "- Use PlayFab.dll for cloud/backend side paths only after the save-grounded gameplay path is understood.",
            "- Use Firebase.Firestore.dll only to explain Firestore-backed properties; do not treat it as gameplay truth.",
            "- Use Tapjoy.dll or Tapjoy.Android.dll only when tracing offerwall-specific reward branches.",
            "- Treat UnityEngine.*, System.*, and Il2CppDummyDll.dll as background/framework context unless a concrete type sends you there.",
            "",
            "assembly_entries:",
        ]
    )
    if assembly_entries:
        summary_lines.extend(_render_assembly_line(entry) for entry in assembly_entries)
    else:
        summary_lines.append("(no dumped assemblies found in catalog)")
    summary_lines.extend(
        [
            "",
            "scope_note:",
            "This report is a triage aid. Save-backed state remains the bot's authoritative truth source.",
        ]
    )
    (report_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report_dir


def _load_catalog_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"IL2CPP output catalog manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"IL2CPP output catalog manifest must be a JSON object: {path}")
    return payload


def _extract_dll_inventory(
    manifest: dict[str, object],
    manifest_path: Path,
) -> list[dict[str, object]]:
    file_inventory = manifest.get("file_inventory")
    if not isinstance(file_inventory, list):
        raise ValueError(
            f"IL2CPP output catalog manifest is missing a valid file_inventory list: {manifest_path}"
        )

    validated: list[dict[str, object]] = []
    for item in file_inventory:
        if not isinstance(item, dict):
            raise ValueError(
                f"IL2CPP output catalog manifest contains a non-object file_inventory entry: {manifest_path}"
            )
        relative_path = item.get("relative_path")
        size_bytes = item.get("size_bytes")
        sha256 = item.get("sha256")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError(
                f"IL2CPP output catalog manifest contains an invalid relative_path entry: {manifest_path}"
            )
        if not isinstance(size_bytes, int):
            raise ValueError(
                f"IL2CPP output catalog manifest contains an invalid size_bytes entry: {manifest_path}"
            )
        if not isinstance(sha256, str) or not sha256.strip():
            raise ValueError(
                f"IL2CPP output catalog manifest contains an invalid sha256 entry: {manifest_path}"
            )
        if not relative_path.lower().endswith(".dll"):
            continue
        validated.append(
            {
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
        )
    return validated


def _classify_assembly(item: dict[str, object]) -> dict[str, object]:
    relative_path = str(item["relative_path"])
    assembly_name = Path(relative_path).name
    assembly_key = assembly_name.lower()
    classification = _classification_for_name(assembly_key)
    return {
        "relative_path": relative_path,
        "assembly_name": assembly_name,
        "size_bytes": int(item["size_bytes"]),
        "sha256": str(item["sha256"]),
        "priority_tier": classification["priority_tier"],
        "priority_score": classification["priority_score"],
        "investigation_role": classification["investigation_role"],
        "why_it_matters": classification["why_it_matters"],
        "recommended_use": classification["recommended_use"],
        "known_limitations": classification["known_limitations"],
    }


def _classification_for_name(assembly_key: str) -> dict[str, object]:
    exact_rules = {
        "assembly-csharp.dll": {
            "priority_tier": "critical",
            "priority_score": 100,
            "investigation_role": "game_logic_schema",
            "why_it_matters": (
                "Primary game-owned assembly. This is where Ads, Boosts, SaveLoad, SaveData, "
                "PlayerData, Homebase, UIManager, and other bot-relevant classes live."
            ),
            "recommended_use": (
                "Open first. Use it to map save-backed fields, runtime state holders, and class ownership "
                "before spending time in SDK/framework assemblies."
            ),
            "known_limitations": (
                "DummyDll methods remain stubs. Use this assembly for structure and naming, not final runtime behavior."
            ),
        },
        "unity.levelplay.dll": {
            "priority_tier": "high",
            "priority_score": 85,
            "investigation_role": "ad_sdk_callbacks",
            "why_it_matters": (
                "Contains LevelPlay/IronSource ad types and callback vocabulary used by the game's rewarded-ad flow."
            ),
            "recommended_use": (
                "Use after Assembly-CSharp.dll when you need to decode rewarded-ad event names, placements, "
                "and SDK callback semantics."
            ),
            "known_limitations": (
                "SDK semantics are supporting context only. Reward truth still has to be proven through save-backed state."
            ),
        },
        "playfab.dll": {
            "priority_tier": "high",
            "priority_score": 72,
            "investigation_role": "backend_cloud_paths",
            "why_it_matters": (
                "Likely source of cloud-save, title-data, and remote account interactions that may explain backend-side state."
            ),
            "recommended_use": (
                "Use when tracing cloud-sync side effects, account persistence, or backend APIs after the local save path is mapped."
            ),
            "known_limitations": (
                "PlayFab paths are not authoritative for the bot's reward verifier unless they change the local save contract."
            ),
        },
        "firebase.firestore.dll": {
            "priority_tier": "medium",
            "priority_score": 60,
            "investigation_role": "backend_property_explainer",
            "why_it_matters": (
                "Explains Firestore-backed properties that show up in the game's generated classes and can otherwise look misleading."
            ),
            "recommended_use": (
                "Use narrowly to explain FirestoreProperty attributes or cloud-model fields discovered in Assembly-CSharp.dll."
            ),
            "known_limitations": (
                "Firestore-backed fields are usually backend/analytics side paths, not direct gameplay truth."
            ),
        },
        "tapjoy.dll": {
            "priority_tier": "medium",
            "priority_score": 56,
            "investigation_role": "offerwall_support",
            "why_it_matters": "Offerwall/currency SDK surface for Tapjoy-specific branches.",
            "recommended_use": (
                "Open only when validating Tapjoy sale panels, offerwall rewards, or non-LevelPlay ad monetization branches."
            ),
            "known_limitations": (
                "Not relevant to the core rewarded-ad boost path unless the gameplay flow explicitly routes through Tapjoy."
            ),
        },
        "tapjoy.android.dll": {
            "priority_tier": "medium",
            "priority_score": 52,
            "investigation_role": "offerwall_platform_bridge",
            "why_it_matters": "Android-specific Tapjoy bridge assembly that may complement Tapjoy.dll.",
            "recommended_use": "Use alongside Tapjoy.dll only for Android-specific offerwall plumbing.",
            "known_limitations": "Low value for the base save-driven rewarded-ad contract.",
        },
        "assembly-csharp-firstpass.dll": {
            "priority_tier": "low",
            "priority_score": 38,
            "investigation_role": "legacy_support_code",
            "why_it_matters": "May contain older helper code or third-party integrations referenced by the main game assembly.",
            "recommended_use": "Open only if a concrete type reference from Assembly-CSharp.dll points into it.",
            "known_limitations": "Usually peripheral to the bot's save/reward verification problem.",
        },
        "appsflyer.dll": {
            "priority_tier": "low",
            "priority_score": 28,
            "investigation_role": "analytics_sidepath",
            "why_it_matters": "Likely explains analytics-only counters such as milestone-style ads watched events.",
            "recommended_use": "Use only to confirm that AppsFlyer fields are analytics noise rather than gameplay truth.",
            "known_limitations": "Analytics milestones should not drive verifier success decisions.",
        },
        "il2cppdummydll.dll": {
            "priority_tier": "background",
            "priority_score": 5,
            "investigation_role": "tooling_support",
            "why_it_matters": "Support assembly emitted by the dumper tooling itself.",
            "recommended_use": "Ignore unless you are debugging the reconstruction tooling.",
            "known_limitations": "Not part of the game's real logic surface.",
        },
    }
    if assembly_key in exact_rules:
        return exact_rules[assembly_key]

    if assembly_key.startswith("firebase."):
        return {
            "priority_tier": "low",
            "priority_score": 32,
            "investigation_role": "backend_sdk_support",
            "why_it_matters": "Backend Firebase support assembly that may explain remote analytics/auth/config side paths.",
            "recommended_use": "Open only when a concrete game-owned type or API call points into this Firebase assembly.",
            "known_limitations": "Usually secondary to the local save contract.",
        }
    if assembly_key.startswith("googlemobileads."):
        return {
            "priority_tier": "low",
            "priority_score": 26,
            "investigation_role": "alternate_ad_sdk_support",
            "why_it_matters": "Ad SDK support assembly that may coexist with or sit behind mediation layers.",
            "recommended_use": "Use if rewarded-ad flow evidence points outside LevelPlay/IronSource naming.",
            "known_limitations": "Mediation/provider support is usually less informative than game-owned logic plus save truth.",
        }
    if assembly_key.startswith("unityengine.purchasing") or assembly_key == "purchasing.common.dll":
        return {
            "priority_tier": "low",
            "priority_score": 24,
            "investigation_role": "iap_support",
            "why_it_matters": "In-app purchase support assembly, relevant for store-backed flows rather than ad rewards.",
            "recommended_use": "Use only when tracing disable-ads or cash pack purchases instead of rewarded-ad automation.",
            "known_limitations": "Peripheral to save-grounded ad reward verification.",
        }
    if assembly_key.startswith("unity.services."):
        return {
            "priority_tier": "background",
            "priority_score": 18,
            "investigation_role": "service_framework_support",
            "why_it_matters": "Unity services infrastructure that may support telemetry or environment configuration.",
            "recommended_use": "Ignore unless a concrete exception, type, or call path leads here.",
            "known_limitations": "Framework context only, not a preferred starting point.",
        }
    if assembly_key.startswith("unityengine.") or assembly_key.startswith("system.") or assembly_key == "mono.security.dll":
        return {
            "priority_tier": "background",
            "priority_score": 8,
            "investigation_role": "framework_runtime",
            "why_it_matters": "Framework/runtime assembly rather than game-specific logic.",
            "recommended_use": "Treat as background context only.",
            "known_limitations": "Very low leverage for bot-specific reverse engineering unless a specific type forces it.",
        }
    if assembly_key in {"newtonsoft.json.dll", "dotween.dll", "nativefilepicker.runtime.dll"}:
        return {
            "priority_tier": "background",
            "priority_score": 14,
            "investigation_role": "third_party_support",
            "why_it_matters": "Common third-party utility/support assembly.",
            "recommended_use": "Open only if a concrete game-owned type points into it.",
            "known_limitations": "Usually implementation detail, not a primary reward-state source.",
        }
    if assembly_key.startswith("stompyrobot."):
        return {
            "priority_tier": "background",
            "priority_score": 12,
            "investigation_role": "debugger_support",
            "why_it_matters": "Likely debug tooling support assembly.",
            "recommended_use": "Ignore unless explicitly investigating debug-only behavior.",
            "known_limitations": "Not a production reward-state source.",
        }

    return {
        "priority_tier": "background",
        "priority_score": 20,
        "investigation_role": "unclassified_support",
        "why_it_matters": "Dumped assembly present in the reconstruction output but not recognized as a primary bot target.",
        "recommended_use": "Inspect only when a concrete symbol, API, or call path points into it.",
        "known_limitations": "Not a preferred starting point without stronger evidence.",
    }


def _render_assembly_line(entry: dict[str, object]) -> str:
    return (
        f"- {entry['relative_path']} tier={entry['priority_tier']} score={entry['priority_score']} "
        f"role={entry['investigation_role']} "
        f"why={entry['why_it_matters']} "
        f"use={entry['recommended_use']} "
        f"limit={entry['known_limitations']}"
    )


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
