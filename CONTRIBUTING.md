# Contributing

Contributions are welcome once the licence is set (pending). Until then, open an issue first.

- Run `pytest` before every pull request. Add a test for any change to scoring, the event gate, or privacy behaviour.
- A change to the formula needs a new `FORMULA_VERSION`, a methodology update, and a note on what it does to every material's score.
- Data changes need the source page and table cited, and a second person to check the transcription.
- Do not add free-text fields, IP logging, analytics scripts or third-party requests without a written privacy review.
- Do not enable `PUBLISH_EVENTS` in a pull request.
