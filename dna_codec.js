#!/usr/bin/env node
/*
 * ============================================================================
 *  SPDX-License-Identifier: UPL-1.0
 *
 *  Copyright (c) 2026 Chase Allen Ringquist
 *
 *  This file is part of an operating system, software, and network Work
 *  conceived and authored by Chase Allen Ringquist. The Author retains
 *  copyright and authorship. Use of this file is licensed as follows.
 *
 *  ----------------------------------------------------------------------------
 *  The Universal Permissive License (UPL), Version 1.0
 *
 *  Subject to the condition set forth below, permission is hereby granted to
 *  any person obtaining a copy of this software, associated documentation
 *  and/or data (collectively the "Software"), free of charge and under any
 *  and all copyright rights in the Software, and any and all patent rights
 *  owned or freely licensable by each licensor hereunder covering either
 *  (i) the unmodified Software as contributed to or provided by such
 *  licensor, or (ii) the Larger Works (as defined below), to deal in both
 *
 *  (a) the Software, and
 *
 *  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
 *  if one is included with the Software (each a "Larger Work" to which the
 *  Software is contributed by such licensors),
 *
 *  without restriction, including without limitation the rights to copy,
 *  create derivative works of, display, perform, and distribute the Software
 *  and make, use, sell, offer for sale, import, export, have made, and have
 *  sold the Software and the Larger Work(s), and to sublicense the foregoing
 *  rights on either these or other terms.
 *
 *  This license is subject to the following condition:
 *
 *  The above copyright notice and either this complete permission notice or
 *  at a minimum a reference to the UPL must be included in all copies or
 *  substantial portions of the Software.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 *  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 *  DEALINGS IN THE SOFTWARE.
 *  ----------------------------------------------------------------------------
 *
 *  Do not remove or alter this notice or any record of origin.
 *  See NOTICE.md in the project root for authorship and ownership terms.
 *
 *  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
 *            Bixby, OK, United States
 * ============================================================================
 */

/**
 * dna_codec.js
 * =============
 * A REAL, independent JavaScript port of dna_binary_codec.py's algorithm —
 * not a call into Python, a separate implementation in a separate language
 * runtime (Node.js), to prove the identity/DNA computation is a real
 * algorithm (bytes -> 2-bit codons -> A/C/G/T) and not something tied to
 * one programming language.
 *
 * If this and the Python version produce byte-identical output for the
 * same input, that is real cross-language proof, not an assertion.
 * (tests/test_dna_codec_js.py runs exactly that comparison when Node.js
 * is installed, and skips cleanly when it isn't.)
 */

'use strict';
const crypto = require('crypto');

const BASE_MAP = { '00': 'A', '01': 'C', '10': 'G', '11': 'T' };
const REVERSE_MAP = { A: '00', C: '01', G: '10', T: '11' };
const COMPLEMENT = { A: 'T', T: 'A', C: 'G', G: 'C' };

function encodeToDna(buf) {
  let bits = '';
  for (const byte of buf) {
    bits += byte.toString(2).padStart(8, '0');
  }
  let out = '';
  for (let i = 0; i < bits.length; i += 2) {
    out += BASE_MAP[bits.slice(i, i + 2)];
  }
  return out;
}

function decodeFromDna(seq) {
  seq = seq.toUpperCase();
  for (const ch of seq) {
    if (!(ch in REVERSE_MAP)) throw new Error(`Invalid symbol: ${ch}`);
  }
  if (seq.length % 4 !== 0) throw new Error(`Invalid length: ${seq.length}`);
  let bits = '';
  for (const ch of seq) bits += REVERSE_MAP[ch];
  const bytes = [];
  for (let i = 0; i < bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return Buffer.from(bytes);
}

function complementStrand(seq) {
  seq = seq.toUpperCase();
  let out = '';
  for (const ch of seq) {
    if (!(ch in COMPLEMENT)) throw new Error(`Invalid symbol: ${ch}`);
    out += COMPLEMENT[ch];
  }
  return out;
}

function gcContent(seq) {
  seq = seq.toUpperCase();
  if (seq.length === 0) return 0.0;
  let gc = 0;
  for (const ch of seq) if (ch === 'G' || ch === 'C') gc++;
  return gc / seq.length;
}

function identityFingerprint(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest();
}

module.exports = { encodeToDna, decodeFromDna, complementStrand, gcContent, identityFingerprint };

// ---------------------------------------------------------------------------
// Self-test + cross-language proof, run when invoked directly
// ---------------------------------------------------------------------------
if (require.main === module) {
  const IDENTITY_TEXT = 'Chase Allen Ringquist | Bixby, Oklahoma | dna-chain-project';

  console.log('='.repeat(78));
  console.log('dna_codec.js — independent JavaScript (Node.js) implementation');
  console.log('='.repeat(78));

  let failures = 0;
  function check(label, cond) {
    console.log(`  [${cond ? 'PASS' : 'FAIL'}] ${label}`);
    if (!cond) failures++;
  }

  // Round-trip
  const sample = Buffer.from('Hello from Node.js, not Python.', 'utf8');
  const dna = encodeToDna(sample);
  const back = decodeFromDna(dna);
  check('round-trip through DNA letters', Buffer.compare(sample, back) === 0);

  // Helix property
  const complement = complementStrand(dna);
  const complementBytes = decodeFromDna(complement);
  const bitwiseNot = Buffer.from(sample.map((b) => b ^ 0xff));
  check('complement == bitwise NOT (real helix property)', Buffer.compare(complementBytes, bitwiseNot) === 0);

  // The actual cross-language claim: compute the SAME identity fingerprint
  // and DNA strand Python computed, independently, in this JS runtime.
  const fingerprint = identityFingerprint(IDENTITY_TEXT);
  const strand = encodeToDna(fingerprint);
  const strandComplement = complementStrand(strand);

  console.log(`\n  Identity text: ${JSON.stringify(IDENTITY_TEXT)}`);
  console.log(`  Fingerprint (computed in Node.js): ${fingerprint.toString('hex')}`);
  console.log(`  DNA strand   (computed in Node.js): ${strand}`);
  console.log(`  Complement   (computed in Node.js): ${strandComplement}`);
  console.log(`  GC content: ${gcContent(strand).toFixed(4)}`);

  console.log('\n' + '='.repeat(78));
  if (failures > 0) {
    console.log(`RESULT: ${failures} check(s) FAILED`);
    process.exit(1);
  } else {
    console.log('RESULT: all checks PASSED in Node.js, independently of Python.');
  }
  console.log('='.repeat(78));
}
