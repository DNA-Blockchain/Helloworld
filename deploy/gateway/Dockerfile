# The RabbitSoftware.inc model gateway as a Hugging Face Space (Docker SDK). Standard library only.
FROM python:3.12-slim
RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/app
COPY --chown=user app.py .
ENV PORT=7860
EXPOSE 7860
CMD ["python", "app.py"]
