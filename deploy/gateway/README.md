---
title: RabbitSoftware.inc model gateway
emoji: 🐇
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# RabbitSoftware.inc model gateway

The public front door to the RabbitSoftware.inc model. It forwards questions to the hosted model with
limits per person and per day, and never records questions or answers.

API (OpenAI-compatible): `POST /v1/chat/completions` with `{"messages": [{"role": "user", "content": "..."}]}`.

Built with Llama.
