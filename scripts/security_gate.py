#!/usr/bin/env python3
"""Security gate: fail CI only on high-severity findings."""

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional

HIGH_WORDS = {"high", "critical", "error", "err"}


def load_json_file(path: Optional[str]) -> Any:
    if not path:
        return None
    file_path = pathlib.Path(path)
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def normalize_severity(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        if text in HIGH_WORDS:
            return "high"
        if text in {"medium", "moderate", "warning", "warn"}:
            return "medium"
        if text in {"low", "info", "informational"}:
            return "low"
        try:
            score = float(text)
            return "high" if score >= 7.0 else "medium" if score >= 4.0 else "low"
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return "high" if float(value) >= 7.0 else "medium" if float(value) >= 4.0 else "low"
    if isinstance(value, dict):
        for key in ("severity", "score", "cvss", "value"):
            if key in value:
                sev = normalize_severity(value.get(key))
                if sev:
                    return sev
    if isinstance(value, list):
        resolved = [normalize_severity(item) for item in value]
        if "high" in resolved:
            return "high"
        if "medium" in resolved:
            return "medium"
        if "low" in resolved:
            return "low"
    return None


def is_high(value: Any) -> bool:
    return normalize_severity(value) == "high"


def collect_pip_audit_findings(report: Any) -> List[str]:
    findings: List[str] = []
    if not isinstance(report, list):
        return findings

    for package in report:
        if not isinstance(package, dict):
            continue
        name = package.get("name", "unknown")
        for vuln in package.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            severity = vuln.get("severity")
            if not severity:
                severity = vuln.get("cvss")
            if not severity:
                severity = vuln.get("cvss_score")
            if is_high(severity):
                findings.append(f"pip-audit: {name} -> {vuln.get('id', 'unknown')}")

    return findings


def collect_npm_audit_findings(report: Any) -> List[str]:
    findings: List[str] = []
    if not isinstance(report, dict):
        return findings

    vulnerabilities = report.get("vulnerabilities") or {}
    if not isinstance(vulnerabilities, dict):
        return findings

    for pkg, details in vulnerabilities.items():
        if not isinstance(details, dict):
            continue
        if is_high(details.get("severity")):
            findings.append(f"npm-audit: {pkg} -> {details.get('severity', 'unknown')}")

    return findings


def collect_bandit_findings(report: Any) -> List[str]:
    findings: List[str] = []
    if not isinstance(report, dict):
        return findings

    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        if is_high(result.get("issue_severity")):
            findings.append(
                "bandit: {file}:{line} -> {test}".format(
                    file=result.get("filename", "unknown"),
                    line=result.get("line_number", "?"),
                    test=result.get("test_name", "unknown"),
                )
            )

    return findings


def collect_semgrep_findings(report: Any) -> List[str]:
    findings: List[str] = []
    if not isinstance(report, dict):
        return findings

    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        extra = result.get("extra") or {}
        severity = extra.get("severity")
        if is_high(severity):
            findings.append(
                "semgrep: {path}:{line} -> {rule}".format(
                    path=result.get("path", "unknown"),
                    line=(result.get("start") or {}).get("line", "?"),
                    rule=result.get("check_id", "unknown"),
                )
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pip", dest="pip_report")
    parser.add_argument("--npm", dest="npm_report")
    parser.add_argument("--bandit", dest="bandit_report")
    parser.add_argument("--semgrep", dest="semgrep_report")
    args = parser.parse_args()

    pip_report = load_json_file(args.pip_report)
    npm_report = load_json_file(args.npm_report)
    bandit_report = load_json_file(args.bandit_report)
    semgrep_report = load_json_file(args.semgrep_report)

    findings: List[str] = []
    findings.extend(collect_pip_audit_findings(pip_report))
    findings.extend(collect_npm_audit_findings(npm_report))
    findings.extend(collect_bandit_findings(bandit_report))
    findings.extend(collect_semgrep_findings(semgrep_report))

    if findings:
        print("High-severity security findings detected:")
        for finding in findings:
            print(f" - {finding}")
        return 1

    print("Security gate passed: no high-severity findings detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
