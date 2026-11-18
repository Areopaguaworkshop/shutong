"""Shutong translation pipeline — EN→ZH-Simplified with mandatory glossary injection."""

from shutong_backend.translation.pipeline import run
from shutong_backend.translation.pipeline import render
from shutong_backend.translation.pipeline import run_url
from shutong_backend.translation.pipeline import resolve_source
from shutong_backend.translation.pipeline import segment_document
from shutong_backend.translation.pipeline import build_system_prompt
from shutong_backend.translation.pipeline import flag_untranslated
from shutong_backend.translation.pipeline import render_interleaved
from shutong_backend.translation.glossary import load_all_glossaries, lookup, add_entry, list_all, copy_file