"""The pep-talk renderer and delivery tools, one module per job.

    common      errors, logging, where files live, .env loading, HTTP retries, redaction
    speech      the speech file: front matter, segments and pauses, estimates, talk facts
    elevenlabs  voice settings, text-to-speech requests and their errors
    audio       ffmpeg: mock tones, PCM and WAV, loudness, the noise bed, the final MP3
    build       the ``build`` command
    telegram    the ``telegram`` command
    gitrepo     the local git repository and its GitHub remote: parsing, commits, pushes
    github_pr   the ``pr`` command
    doctor      the ``doctor`` command

scripts/pep_talk.py is the command line in front of them.
"""
