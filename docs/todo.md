# Maintenance to-do

This list holds real repairs and features only. Anything that needs the owner goes
here with its reason, not in a plan or the PKM. Sign-offs, acceptance checks and
evidence gaps are not tracked; breakage found in use gets fixed then.

## Transcription: replace the deprecated whisper-1 fallback model
When local Whisper fails and `OPENAI_API_KEY` is set, `transcribe_audio` in `transcription/app.py` sends the audio to OpenAI with `model="whisper-1"`, and the model selector's help text names that model. The openai 3.55 SDK lists `whisper-1` as deprecated with a shutdown date of 2027-02-26; after that date the fallback fails. The local Whisper path is unaffected.
- Options: (a) switch the fallback and its help text to `gpt-transcribe` before 2027-02-26, checking that its `response_format="text"` output still matches what the app expects; (b) remove the OpenAI fallback and rely on local Whisper only; (c) leave it and accept that the fallback stops working after the shutdown.
- Recommendation: (a). It keeps the existing recovery path and is a one-line model change plus its help text and tests.
