import argparse
import json
import pathlib
from typing import Any, List, Optional

HIGH_WORDS = {"high", "critical", "error", "err"}


class SecurityReportError(ValueError):
    """A scanner report cannot be trusted as evidence for a passing gate."""


def load_json_file(path: Optional[str], scanner: str = "security scanner") -> Any:
    if not path:
        raise SecurityReportError(f"{scanner}: report path was not provided")
    file_path = pathlib.Path(path)
    if not file_path.is_file():
        raise SecurityReportError(f"{scanner}: report is missing: {file_path}")
    try:
        raw_report = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SecurityReportError(f"{scanner}: report cannot be read: {file_path}") from exc
    if not raw_report.strip():
        raise SecurityReportError(f"{scanner}: report is empty: {file_path}")
    try:
        return json.loads(raw_report)
    except json.JSONDecodeError as exc:
        raise SecurityReportError(f"{scanner}: report is not valid JSON: {file_path}") from exc


def validate_report(scanner: str, report: Any) -> None:
    if scanner == "pip-audit":
        dependencies = report if isinstance(report, list) else None
        if isinstance(report, dict):
            dependencies = report.get("dependencies")
        if not isinstance(dependencies, list):
            raise SecurityReportError("pip-audit: report has an unexpected schema")
        if isinstance(report, dict) and (report.get("error") or report.get("errors")):
            raise SecurityReportError("pip-audit: scanner reported an operational error")
        for dependency in dependencies:
            if not isinstance(dependency, dict) or not isinstance(dependency.get("vulns"), list):
                raise SecurityReportError("pip-audit: report has malformed dependency data")
            for vulnerability in dependency["vulns"]:
                if not isinstance(vulnerability, dict) or not vulnerability.get("id"):
                    raise SecurityReportError("pip-audit: report has malformed vulnerability data")
        return

    if not isinstance(report, dict):
        raise SecurityReportError(f"{scanner}: report has an unexpected schema")
    if report.get("error"):
        raise SecurityReportError(f"{scanner}: scanner reported an operational error")

    expected_list_keys = {
        "bandit": ("results", "errors"),
        "semgrep": ("results", "errors"),
    }
    if scanner == "npm-audit":
        vulnerabilities = report.get("vulnerabilities")
        if not isinstance(vulnerabilities, dict) or not isinstance(report.get("metadata"), dict):
            raise SecurityReportError("npm-audit: report has an unexpected schema")
        if any(
            not isinstance(details, dict) or normalize_severity(details.get("severity")) is None
            for details in vulnerabilities.values()
        ):
            raise SecurityReportError("npm-audit: report has malformed vulnerability data")
        return

    required_keys = expected_list_keys.get(scanner)
    if not required_keys or any(not isinstance(report.get(key), list) for key in required_keys):
        raise SecurityReportError(f"{scanner}: report has an unexpected schema")
    if report.get("errors"):
        raise SecurityReportError(f"{scanner}: scanner reported an operational error")
    for result in report["results"]:
        if not isinstance(result, dict):
            raise SecurityReportError(f"{scanner}: report has malformed finding data")
        if scanner == "bandit":
            severity = result.get("issue_severity")
        else:
            extra = result.get("extra")
            if not isinstance(extra, dict):
                raise SecurityReportError("semgrep: report has malformed finding data")
            severity = extra.get("severity")
        if normalize_severity(severity) is None:
            raise SecurityReportError(f"{scanner}: report has malformed finding severity")


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
    if isinstance(report, dict):
        packages = report.get("dependencies") or []
    elif isinstance(report, list):
        packages = report
    else:
        return findings

    for package in packages:
        if not isinstance(package, dict):
            continue
        name = package.get("name", "unknown")
        for vuln in package.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            vuln_id = vuln.get("id", "unknown")
            fix_versions = vuln.get("fix_versions") or []
            fix_text = f" (fix: {', '.join(fix_versions)})" if fix_versions else ""
            findings.append(f"pip-audit: {name} -> {vuln_id}{fix_text}")

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
    parser.add_argument("--pip", dest="pip_report", required=True)
    parser.add_argument("--npm", dest="npm_report", required=True)
    parser.add_argument("--bandit", dest="bandit_report", required=True)
    parser.add_argument("--semgrep", dest="semgrep_report", required=True)
    args = parser.parse_args()

    try:
        pip_report = load_json_file(args.pip_report, "pip-audit")
        npm_report = load_json_file(args.npm_report, "npm-audit")
        bandit_report = load_json_file(args.bandit_report, "bandit")
        semgrep_report = load_json_file(args.semgrep_report, "semgrep")
        reports = {
            "pip-audit": pip_report,
            "npm-audit": npm_report,
            "bandit": bandit_report,
            "semgrep": semgrep_report,
        }
        for scanner, report in reports.items():
            validate_report(scanner, report)
    except SecurityReportError as exc:
        print(f"Security gate failed closed: {exc}")
        return 2

    findings: List[str] = []
    findings.extend(collect_pip_audit_findings(pip_report))
    findings.extend(collect_npm_audit_findings(npm_report))
    findings.extend(collect_bandit_findings(bandit_report))
    findings.extend(collect_semgrep_findings(semgrep_report))

    if findings:
        print("Blocking security findings detected:")
        for finding in findings:
            print(f" - {finding}")
        return 1

    print("Security gate passed: no blocking findings detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
