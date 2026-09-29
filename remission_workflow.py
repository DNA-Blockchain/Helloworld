#!/usr/bin/env python3
# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

"""
remission_workflow.py
=====================
Host runner for remission_core (the same file the Network OS runs as a
MicroPython task bundle). Adds what only the host can do: a readable
report, JSON output, and encrypted off-chain storage of the full records
via EncryptedDataVault, so only hashes ever need to be shared or chained.

Usage:
    python remission_workflow.py                       # built-in demo
    python remission_workflow.py --input case.json --output result.json
    python remission_workflow.py --vault               # needs REMISSION_VAULT_PASSPHRASE

See remission_core.py for the input format and the model's limits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import remission_core

PASSPHRASE_ENV = "REMISSION_VAULT_PASSPHRASE"

DEMO_REQUEST = {
    "case_label": "demo-synthetic-001",
    "reference": "ACGTACGTACGT",
    "sample": "ACGTACATACGT",
    "follow_ups": [
        {"label": "TIME 3", "collected_on": "synthetic", "sequence": "ACGTACGTACGT"},
    ],
}


def format_report(result: dict) -> str:
    lines = [
        "CANCER -> MODELED REFERENCE MATCH  (" + result["schema"] + ")",
        "",
        "BEFORE   " + result["before"]["sequence"],
        "         " + result["before"]["binary"],
    ]
    for mutation in result["mutations"]:
        lines.append(
            "MUTATION {mutation_id}  position {position}  {reference} -> {observed}"
            "  ({reference_bits} -> {observed_bits})".format(**mutation)
        )
    for edit in result["modeled_edit"]:
        lines.append("MODELED EDIT  position {position}  {from} -> {to}".format(**edit))
    verification = result["verification"]
    assessment = result["assessment"]
    lines += [
        "AFTER    " + result["after"]["sequence"],
        "         " + result["after"]["binary"],
        "",
        "Verification: {matching_positions}/{total_positions} positions match, "
        "{different_positions} different".format(**verification),
    ]
    for entry in result["follow_ups"]:
        lines.append(
            "Follow-up {label}: {differences_vs_reference} differences vs reference, "
            "original mutations present: {present}".format(
                present=", ".join(entry["original_mutations_present"]) or "none", **entry
            )
        )
    lines += [
        "",
        "Modeled status:     " + assessment["modeled_status"],
        "Longitudinal trend: " + assessment["longitudinal_trend"],
        "Clinical status:    " + assessment["clinical_status"]["status"],
        "Ledger:             {} blocks, {}".format(
            len(result["ledger"]["blocks"]),
            "verified" if result["ledger"]["verified"] else "PROBLEMS: " + "; ".join(result["ledger"]["problems"]),
        ),
        "",
        remission_core.DISCLAIMER,
    ]
    return "\n".join(lines)


def store_records_in_vault(result: dict, passphrase: str, vault_dir: Path | None = None) -> dict:
    """Encrypt the full records (they contain sequences) and replace them
    in the result with the vault reference."""
    from encrypted_data_vault import EncryptedDataVault

    vault = EncryptedDataVault(vault_dir) if vault_dir else EncryptedDataVault()
    with tempfile.TemporaryDirectory() as scratch:
        records_path = Path(scratch) / "remission_records.json"
        records_path.write_text(remission_core.canonical_json(result["records"]), encoding="utf-8")
        stored = vault.store_file(
            records_path,
            passphrase=passphrase,
            classification="private",
            source_label="remission_workflow",
        )
    redacted = dict(result)
    redacted["records"] = {"vault": stored}
    return redacted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, help="request JSON (default: built-in synthetic demo)")
    parser.add_argument("--output", type=Path, help="write the full result JSON here")
    parser.add_argument("--vault", action="store_true",
                        help="encrypt full records off-chain (passphrase from " + PASSPHRASE_ENV + ")")
    parser.add_argument("--vault-dir", type=Path, help="vault directory (default: dna_shell_data/encrypted_vault)")
    args = parser.parse_args(argv)

    request = json.loads(args.input.read_text(encoding="utf-8")) if args.input else DEMO_REQUEST
    try:
        result = remission_core.run(request)
    except ValueError as error:
        print("error: " + str(error), file=sys.stderr)
        return 2

    if args.vault:
        passphrase = os.environ.get(PASSPHRASE_ENV)
        if not passphrase:
            print("error: set " + PASSPHRASE_ENV + " to use --vault", file=sys.stderr)
            return 2
        result = store_records_in_vault(result, passphrase, args.vault_dir)

    print(format_report(result))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("\nfull result written to " + str(args.output))
    return 0 if result["ledger"]["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
