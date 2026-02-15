"""ee_bench_run_scripts - Run scripts provider and attachment generators.

Provides:
- RunScriptsProvider: enrichment provider fetching run scripts from SWE-bench Pro OS repo
- GitHubAttachmentGenerator: attaches run script files to PR branches
- AttachmentExportGenerator: downloads attachment files from PR branches to local folders
"""

from ee_bench_run_scripts.attachment_export_generator import AttachmentExportGenerator
from ee_bench_run_scripts.attachment_generator import GitHubAttachmentGenerator
from ee_bench_run_scripts.provider import RunScriptsProvider

__version__ = "0.1.0"

__all__ = [
    "RunScriptsProvider",
    "GitHubAttachmentGenerator",
    "AttachmentExportGenerator",
]
