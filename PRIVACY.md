# Privacy policy

**RabbitSoftware** (the OS, its nodes and chain, RabbitSoftware.inc and its model). Effective 2026.
Operator: Chase Allen Ringquist, ringquistchase@gmail.com.

RabbitSoftware is local-first. Data stays on the device unless a specific feature sends it, and every
feature that sends data asks the user first and writes the action to the device's activity log
(`system_audit.jsonl`).

## What stays on the device

Conversations, settings, research records, integrity reports, node keys, chains and the local AI model.
None of it is sent anywhere by default. The software uses no analytics, no advertising and no tracking
cookies. The local web page uses only a session it creates for itself on `127.0.0.1`.

## What leaves the device, and only after a yes

| Feature | What is sent | Where |
|---|---|---|
| Public research search | the search words | PubMed, ClinicalTrials.gov, NIH RePORTER, Europe PMC. Only a SHA-256 of the words is logged locally. |
| Abstract retrieval | record numbers (e.g. PubMed IDs) | the same public sources |
| Hosted model | the question and the public records it is answered from | the RabbitSoftware model (Hugging Face Inference Endpoint) through the Cloudflare gateway. The gateway stores no questions or answers; it keeps only daily request counts and a hashed network address held in memory. |
| Account sync: history | chat history, **encrypted on the device** (AES-256-GCM) | Cloudflare R2. The service stores only ciphertext it cannot read. |
| Account sync: research | public research records | Cloudflare R2, shared with every device |
| Share for training | one question and its answer, chosen by the user, checked first for personal information, and stored **without any name, account or device** | Cloudflare R2, then the operator's private Hugging Face dataset |
| Chain entries (notes, fingerprints) | the note text, or only a SHA-256 fingerprint | the public RabbitSoftware chain |

## The chain is public and permanent

Anything published to the chain is copied to every node and cannot be deleted; it can only be answered
with a later entry. Notes are checked for personal information (email addresses, phone and ID numbers,
dates of birth, street addresses, long DNA sequences), and anything that matches is refused. Personal
data belongs in the encrypted digital-twin vault on the device, which is never published.

## Service providers

Cloudflare (gateway and sync service) and Hugging Face (model hosting and the private training dataset)
process data only as described above.

## Your choices

- Answer **no** to any request to send data.
- Turn off the hosted model (`rabbit model-server --off`), chain notes, or daily integrity publishing at any time.
- Remove any device from a sync account ("remove device").
- To have your synced data deleted from the service, email the operator.

## Changes

Changes to this policy are listed in `CHANGELOG.md` and take effect with the release that includes them.
