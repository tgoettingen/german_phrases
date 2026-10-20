"""Speak German, English and Chinese text with the operating system's built-in voices.

No extra packages are needed.

Windows: the newer OneCore voices (Katja, Stefan, Hedda) through Windows.Media.SpeechSynthesis,
         falling back to System.Speech (Hedda Desktop) on older systems. Both run in PowerShell.
macOS: `say` with a German voice (Anna, ...) if installed.
Linux: espeak-ng or espeak, if installed.

The German voice and the speed can be chosen; `Speaker.voices` lists the German voices found.
English and Chinese (used by Auto play) get the best voice of their language, if one is installed.
"""
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_RATE = 0.9  # a little slower than normal, easier to follow for learners
MIN_RATE, MAX_RATE = 0.5, 1.5
WORDS_PER_MINUTE = 175  # normal speed of `say` and espeak

_POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]

LANGS = ("de", "en", "zh")

# Prints the engine to use ("winrt" or "sapi"), then one "name|gender|language" line per
# German, English or Chinese voice.
_WINDOWS_VOICES_SCRIPT = """
try {
  $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
  $v = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.Language -match '^(de|en|zh)' }
  if ($v) { 'winrt'; $v | ForEach-Object { $_.DisplayName + '|' + $_.Gender + '|' + $_.Language }; exit }
} catch {}
Add-Type -AssemblyName System.Speech
'sapi'
(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() |
  Where-Object { $_.VoiceInfo.Culture.Name -match '^(de|en|zh)' } |
  ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Gender + '|' + $_.VoiceInfo.Culture.Name }
"""

# Text, voice and rate go through environment variables, never into the scripts themselves.
_WINRT_SCRIPT = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
$s = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
$v = $all | Where-Object { $_.DisplayName -eq $env:PHRASE_TTS_VOICE } | Select-Object -First 1
if (-not $v) { $v = $all | Where-Object { $_.Language -like "$env:PHRASE_TTS_LANG*" } | Select-Object -First 1 }
if ($v) { $s.Voice = $v }
$s.Options.SpeakingRate = [double]$env:PHRASE_TTS_RATE
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$task = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke(
  $null, @($s.SynthesizeTextToStreamAsync($env:PHRASE_TTS_TEXT)))
$audio = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($task.Result)
(New-Object System.Media.SoundPlayer $audio).PlaySync()
"""

_SAPI_SCRIPT = """
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$all = $s.GetInstalledVoices()
$v = $all | Where-Object { $_.VoiceInfo.Name -eq $env:PHRASE_TTS_VOICE } | Select-Object -First 1
if (-not $v) { $v = $all | Where-Object { $_.VoiceInfo.Culture.Name -like "$env:PHRASE_TTS_LANG*" } | Select-Object -First 1 }
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Rate = [int]$env:PHRASE_TTS_RATE
$s.Speak($env:PHRASE_TTS_TEXT)
"""


_ABBREVIATIONS = {"etw.": "etwas", "jdn.": "jemanden", "jdm.": "jemandem", "jds.": "jemandes"}


def speakable(text: str) -> str:
    """Expand dictionary abbreviations so they are read as words."""
    for short, full in _ABBREVIATIONS.items():
        text = text.replace(short, full)
    return text


@dataclass(frozen=True)
class Voice:
    name: str         # what the speech engine calls it
    gender: str = ""  # "female", "male" or "" if unknown
    lang: str = "de"  # "de", "en" or "zh"

    @property
    def label(self) -> str:
        """e.g. "Katja (female)"."""
        short = self.name.removeprefix("Microsoft ").removesuffix(" Desktop")
        return f"{short} ({self.gender})" if self.gender else short


def parse_voices(output: str) -> list[Voice]:
    """Read the "name|gender|language" lines printed by the Windows voice listing."""
    voices = []
    for line in output.splitlines():
        parts = line.strip().split("|")
        lang = parts[2][:2].lower() if len(parts) == 3 else ""
        if parts[0] and lang in LANGS:
            gender = parts[1].lower()
            voices.append(Voice(parts[0], gender if gender in ("female", "male") else "", lang))
    return voices


def default_voice(voices: list[Voice], lang: str = "de") -> Voice | None:
    """The best voice for `lang`, female voices first. German: Katja sounds most natural,
    Hedda worst."""
    ranked = sorted((v for v in voices if v.lang == lang),
                    key=lambda v: ("Katja" not in v.name, "Hedda" in v.name, v.gender != "female"))
    return ranked[0] if ranked else None


def sapi_rate(rate: float) -> int:
    """Speed factor (1.0 = normal) as a System.Speech rate from -10 to 10."""
    return max(-10, min(10, round((rate - 1.0) * 10)))


class Speaker:
    def __init__(self, voice: str = "", rate: float = DEFAULT_RATE):
        self._proc: subprocess.Popen | None = None
        self.engine, self.all_voices = self._find_engine()
        self.voices = [v for v in self.all_voices if v.lang == "de"]  # the choice in the settings
        self.voice: Voice | None = None
        self.rate = DEFAULT_RATE
        self.set_voice(voice)
        self.set_rate(rate)

    @property
    def available(self) -> bool:
        return self.engine is not None

    @property
    def busy(self) -> bool:
        """True while the last text is still being spoken."""
        return self._proc is not None and self._proc.poll() is None

    def voice_for(self, lang: str) -> Voice | None:
        """The chosen German voice, or the best voice for English or Chinese."""
        return self.voice if lang == "de" else default_voice(self.all_voices, lang)

    def has_voice(self, lang: str) -> bool:
        """True if text in `lang` can be spoken (German is tried even without a German voice)."""
        return self.available and (lang == "de" or self.voice_for(lang) is not None)

    def set_voice(self, name: str) -> None:
        """Use the voice called `name`, or the best German voice if there is none by that name."""
        self.voice = next((v for v in self.voices if v.name == name), None) or default_voice(self.voices)

    def set_rate(self, rate) -> None:
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            rate = DEFAULT_RATE
        self.rate = round(min(MAX_RATE, max(MIN_RATE, rate)), 1)

    def _find_engine(self) -> tuple[str | None, list[Voice]]:
        if sys.platform == "darwin" and shutil.which("say"):
            try:
                listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                                         timeout=5).stdout
            except (OSError, subprocess.SubprocessError):
                listing = ""
            # Lines look like "Anna (Enhanced)    de_DE    # Hallo! Ich heiße Anna."
            found = re.findall(r"^(.+?)\s+(de_DE|en_US|en_GB|zh_CN|zh_TW)\s", listing, re.MULTILINE)
            return "say", [Voice(name, "", lang[:2]) for name, lang in found]
        if sys.platform == "win32" and shutil.which("powershell"):
            try:
                lines = subprocess.run([*_POWERSHELL, _WINDOWS_VOICES_SCRIPT], capture_output=True,
                                       text=True, timeout=15,
                                       creationflags=subprocess.CREATE_NO_WINDOW).stdout
            except (OSError, subprocess.SubprocessError):
                lines = ""
            engine = "winrt" if lines.lstrip().startswith("winrt") else "sapi"
            return engine, parse_voices(lines)
        for exe in ("espeak-ng", "espeak"):
            if shutil.which(exe):
                return exe, [Voice("de"), Voice("de+f3", "female"), Voice("de+m3", "male"),
                             Voice("en", "", "en"), Voice("cmn", "", "zh")]
        return None, []

    def _command(self, text: str, lang: str) -> tuple[list[str], dict]:
        env = dict(os.environ)
        voice = self.voice_for(lang)
        name = voice.name if voice else ""
        if self.engine in ("winrt", "sapi"):
            env["PHRASE_TTS_TEXT"] = text
            env["PHRASE_TTS_VOICE"] = name
            env["PHRASE_TTS_LANG"] = lang
            env["PHRASE_TTS_RATE"] = str(self.rate if self.engine == "winrt" else sapi_rate(self.rate))
            return [*_POWERSHELL, _WINRT_SCRIPT if self.engine == "winrt" else _SAPI_SCRIPT], env
        voice = ["-v", name] if name else []
        speed = ["-r" if self.engine == "say" else "-s", str(round(WORDS_PER_MINUTE * self.rate))]
        return [self.engine, *voice, *speed, text], env

    def speak(self, text: str, lang: str = "de") -> None:
        """Speak `text` in German, or in English or Chinese ("en", "zh") if such a voice exists."""
        if not self.has_voice(lang) or not text.strip():
            return
        self.stop()
        args, env = self._command(speakable(text) if lang == "de" else text, lang)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError:
            self.engine = None

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
