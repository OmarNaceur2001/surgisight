"""Local tracked-file safety scan; reads metadata and text only, never media bytes."""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".mp4", ".avi", ".mkv", ".mov", ".webm", ".zip", ".tar", ".gz",
    ".rar", ".7z", ".pt", ".pth", ".npy", ".npz", ".h5", ".hdf5",
    ".pkl", ".onnx", ".parquet",
}
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:API_KEY|ACCESS_TOKEN|SECRET_KEY|JWT_SECRET|PASSWORD)\s*=\s*([A-Za-z0-9_./:+-]+)"
)
PLACEHOLDERS = {"CHANGE_ME", "CHANGE_ME_IN_PRODUCTION_USE_32_BYTE_RANDOM_SECRET", "your-token-here", "example"}
TEXT_SUFFIXES = {
    ".py", ".ps1", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env",
    ".example", ".md", ".json", ".ts", ".tsx", ".js", ".mjs", ".css",
    ".html", ".txt", ".psm1",
}

def tracked_paths() -> list[Path]:
    """Return tracked repository paths from Git's index."""
    result = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
    return [Path(item.decode("utf-8", errors="replace")) for item in result.stdout.split(b"\0") if item]

def main() -> int:
    failures: list[str] = []
    paths = tracked_paths()
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES:
            failures.append(f"Forbidden tracked file type: {path}")
            continue
        try:
            if path.stat().st_size > 5 * 1024 * 1024:
                failures.append(f"Tracked file exceeds 5 MB: {path}")
                continue
            if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
                if not (path.as_posix().startswith("web/") or path.as_posix().startswith("docs/")):
                    failures.append(f"Image outside UI/docs path: {path}")
                continue
            if suffix in {".pyc", ".exe", ".dll", ".so"}:
                failures.append(f"Unexpected binary tracked file: {path}")
                continue
            if suffix not in TEXT_SUFFIXES:
                continue
            data = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(data):
                failures.append(f"Potential credential/private-key material in {path}")
                break
        for match in ASSIGNMENT.finditer(data):
            value = match.group(1).strip()
            if value and value not in PLACEHOLDERS and not value.startswith("$"):
                if "example" not in value.lower() and "change_me" not in value.lower():
                    failures.append(f"Potential hard-coded secret assignment in {path}")
                    break
    if failures:
        print("Security check failed:")
        print("\n".join(failures))
        return 1
    print(f"Security check passed: {len(paths)} tracked paths scanned; no prohibited artifacts/secrets detected.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
